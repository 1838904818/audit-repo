#!/usr/bin/env python3
"""Unit tests for collect_repo_signals.py."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("collect_repo_signals.py")
SPEC = importlib.util.spec_from_file_location("collect_repo_signals", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CollectRepoSignalsTests(unittest.TestCase):
    def test_collects_expected_inventory_without_reading_secret_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("Example", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='example'", encoding="utf-8")
            (root / ".env").write_text("SECRET=do-not-print", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("# TODO: test\nprint('ok')", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("def test_ok(): pass", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI", encoding="utf-8")

            data = MODULE.collect(root, 100)
            rendered = MODULE.to_markdown(data)

            self.assertEqual(data["test_file_count"], 1)
            self.assertEqual(data["manifests"], ["pyproject.toml"])
            self.assertEqual(data["documentation"], ["README.md"])
            self.assertEqual(data["ci_files"], [".github/workflows/ci.yml"])
            self.assertEqual(data["work_markers"]["TODO"], 1)
            self.assertEqual(data["sensitive_looking_files"][0]["path"], ".env")
            self.assertNotIn("do-not-print", rendered)

    def test_scan_limit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                (root / f"file-{index}.txt").write_text("data", encoding="utf-8")

            data = MODULE.collect(root, 2)

            self.assertEqual(data["file_count"], 2)
            self.assertTrue(data["scan_truncated"])


if __name__ == "__main__":
    unittest.main()
