#!/usr/bin/env python3
"""Unit tests for package_skill.py."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("package_skill.py")
SPEC = importlib.util.spec_from_file_location("package_skill", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PackageSkillTests(unittest.TestCase):
    def test_builds_deterministic_minimal_archive_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_archive, first_checksum, first_digest = MODULE.build_archive("v1.2.3", Path(first_dir))
            second_archive, _, second_digest = MODULE.build_archive("1.2.3", Path(second_dir))

            self.assertEqual(first_digest, second_digest)
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            self.assertEqual(hashlib.sha256(first_archive.read_bytes()).hexdigest(), first_digest)
            self.assertEqual(first_checksum.read_text(encoding="utf-8"), f"{first_digest}  {first_archive.name}\n")

            with zipfile.ZipFile(first_archive) as bundle:
                names = bundle.namelist()
                expected = [f"audit-repo/{path.as_posix()}" for path in MODULE.RUNTIME_FILES]
                self.assertEqual(names, expected)
                self.assertTrue(all(info.date_time == MODULE.FIXED_TIMESTAMP for info in bundle.infolist()))
                self.assertNotIn("audit-repo/.github/workflows/ci.yml", names)
                self.assertFalse(any("test_" in name or "__pycache__" in name for name in names))

    def test_rejects_invalid_version(self) -> None:
        with self.assertRaises(MODULE.PackageError):
            MODULE.normalize_version("latest")


if __name__ == "__main__":
    unittest.main()
