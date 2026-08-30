#!/usr/bin/env python3
"""Unit tests for package_skill.py."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("package_skill.py")
SPEC = importlib.util.spec_from_file_location("package_skill", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ORIGINAL_ROOT = MODULE.ROOT


class PackageSkillTests(unittest.TestCase):
    def test_builds_deterministic_minimal_archive_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            version = MODULE.runtime_tool_version()
            first_archive, first_checksum, first_digest = MODULE.build_archive(f"v{version}", Path(first_dir))
            second_archive, _, second_digest = MODULE.build_archive(version, Path(second_dir))

            self.assertEqual(first_digest, second_digest)
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            self.assertEqual(hashlib.sha256(first_archive.read_bytes()).hexdigest(), first_digest)
            self.assertEqual(first_checksum.read_text(encoding="utf-8"), f"{first_digest}  {first_archive.name}\n")

            with zipfile.ZipFile(first_archive) as bundle:
                names = bundle.namelist()
                expected = [f"audit-repo/{path.as_posix()}" for path in MODULE.RUNTIME_FILES]
                self.assertEqual(names, expected)
                self.assertTrue(all(info.date_time == MODULE.FIXED_TIMESTAMP for info in bundle.infolist()))
                self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in bundle.infolist()))
                self.assertTrue(all((info.external_attr >> 16) & 0o777 == 0o644 for info in bundle.infolist()))
                self.assertNotIn("audit-repo/.github/workflows/ci.yml", names)
                self.assertFalse(any("test_" in name or "__pycache__" in name for name in names))

                packaged = set(names)
                markdown_link = re.compile(r"\[[^]]*\]\(([^)]+)\)")
                for name in names:
                    if not name.endswith(".md"):
                        continue
                    source = bundle.read(name).decode("utf-8")
                    for target in markdown_link.findall(source):
                        if target.startswith(("https://", "http://", "mailto:", "#")):
                            continue
                        resolved = (Path(name).parent / target.split("#", 1)[0]).as_posix()
                        self.assertIn(resolved, packaged, f"broken packaged link in {name}: {target}")

    def test_normalizes_text_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "example.txt"
            path.write_bytes(b"first\r\nsecond\rthird\n")

            self.assertEqual(MODULE.archive_bytes(path), b"first\nsecond\nthird\n")

    def test_archive_is_independent_of_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as lf_dir, tempfile.TemporaryDirectory() as crlf_dir, tempfile.TemporaryDirectory() as output_dir:
            lf_root = Path(lf_dir)
            crlf_root = Path(crlf_dir)
            for relative in MODULE.RUNTIME_FILES:
                canonical = (ORIGINAL_ROOT / relative).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                for root, data in ((lf_root, canonical), (crlf_root, canonical.replace(b"\n", b"\r\n"))):
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)

            try:
                MODULE.ROOT = lf_root
                version = MODULE.runtime_tool_version()
                lf_archive, _, lf_digest = MODULE.build_archive(f"v{version}", Path(output_dir) / "lf")
                MODULE.ROOT = crlf_root
                crlf_archive, _, crlf_digest = MODULE.build_archive(f"v{version}", Path(output_dir) / "crlf")
            finally:
                MODULE.ROOT = ORIGINAL_ROOT

            self.assertEqual(lf_digest, crlf_digest)
            self.assertEqual(lf_archive.read_bytes(), crlf_archive.read_bytes())

    def test_rejects_invalid_version(self) -> None:
        with self.assertRaises(MODULE.PackageError):
            MODULE.normalize_version("latest")

    def test_rejects_release_version_that_differs_from_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(MODULE.PackageError, "does not match runtime TOOL_VERSION"):
                MODULE.build_archive("v9.9.9", Path(output_dir))


if __name__ == "__main__":
    unittest.main()
