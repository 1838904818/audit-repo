#!/usr/bin/env python3
"""Unit tests for collect_repo_signals.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
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
            (root / "pyproject.toml").write_text(
                "[project]\nname='example'\n[tool.pytest.ini_options]\naddopts='-q'",
                encoding="utf-8",
            )
            (root / "package.json").write_text(
                '{"scripts":{"test":"pytest","lint":"ruff check ."}}',
                encoding="utf-8",
            )
            (root / ".env").write_text("SECRET=do-not-print", encoding="utf-8")
            (root / ".env.production").write_text("SECRET=also-private", encoding="utf-8")
            (root / ".env.example").write_text("SECRET=placeholder", encoding="utf-8")
            (root / "credentials.json").write_text('{"note":"# TODO private"}', encoding="utf-8")
            (root / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
            (root / "Makefile").write_text("test:\n\tpython -m unittest\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("# TODO: test\nprint('ok')", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("# FIXME: fixture\ndef test_ok(): pass", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\nsteps:\n  - uses: actions/checkout@v7",
                encoding="utf-8",
            )
            (root / ".github" / "dependabot.yml").write_text("version: 2", encoding="utf-8")
            (root / ".github" / "CODEOWNERS").write_text("* @example", encoding="utf-8")

            data = MODULE.collect(root, 100)
            rendered = MODULE.to_markdown(data)

            self.assertFalse(data["git_repository"])
            self.assertEqual(data["test_file_count"], 1)
            self.assertEqual(data["manifests"], ["package.json", "pyproject.toml"])
            self.assertEqual(data["documentation"], ["README.md"])
            self.assertEqual(data["ci_files"], [".github/workflows/ci.yml"])
            self.assertEqual(data["work_markers"]["TODO"], 1)
            self.assertNotIn("FIXME", data["work_markers"])
            self.assertEqual(
                [item["path"] for item in data["sensitive_looking_files"]],
                [".env", ".env.production", "credentials.json"],
            )
            self.assertEqual(data["environment_examples"], [".env.example"])
            self.assertEqual(data["automation"]["package_scripts"]["package.json"], ["lint", "test"])
            self.assertEqual(data["automation"]["make_targets"]["Makefile"], ["test"])
            self.assertIn("pytest", data["automation"]["configured_tools"])
            self.assertEqual(data["ci_action_references"], ["actions/checkout@v7"])
            self.assertEqual(data["dependency_update_config"], [".github/dependabot.yml"])
            self.assertEqual(data["codeowners"], [".github/CODEOWNERS"])
            self.assertEqual(data["container_files"], ["Dockerfile"])
            self.assertNotIn("do-not-print", rendered)
            self.assertNotIn("also-private", rendered)

    def test_scan_limit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                (root / f"file-{index}.txt").write_text("data", encoding="utf-8")

            data = MODULE.collect(root, 2)

            self.assertEqual(data["file_count"], 2)
            self.assertTrue(data["scan_truncated"])

    def test_exact_scan_limit_is_not_reported_as_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(2):
                (root / f"file-{index}.txt").write_text("data", encoding="utf-8")

            data = MODULE.collect(root, 2)

            self.assertEqual(data["file_count"], 2)
            self.assertFalse(data["scan_truncated"])

    def test_custom_directory_exclusion_and_large_file_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "keep.py").write_text("print('ok')", encoding="utf-8")
            (root / "generated").mkdir()
            (root / "generated" / "ignored.py").write_text("# TODO: generated", encoding="utf-8")

            data = MODULE.collect(root, 100, exclude_dirs=["generated"], large_file_bytes=1)

            self.assertEqual(data["file_count"], 1)
            self.assertEqual(data["excluded_directory_names"], ["generated"])
            self.assertEqual(data["large_files"][0]["path"], "keep.py")
            self.assertEqual(data["work_markers"], {})

    def test_markdown_escapes_untrusted_paths(self) -> None:
        data = MODULE.collect(Path(__file__).parent, 100)
        data["root"] = "repo`\n\n## Forged result\u2028still forged"
        data["sensitive_looking_files"] = [{"path": "secret`\n- fake.md", "tracked": True}]

        rendered = MODULE.to_markdown(data)

        self.assertNotIn("\n## Forged result", rendered)
        self.assertNotIn("\n- fake.md", rendered)
        self.assertNotIn("\u2028", rendered)
        self.assertIn("Forged result", rendered)

    def test_cli_rejects_non_finite_large_file_threshold(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), ".", "--large-file-mib", "nan"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must be positive", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

        huge = subprocess.run(
            [sys.executable, str(MODULE_PATH), ".", "--large-file-mib", "1e308"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(huge.returncode, 2)
        self.assertIn("too large", huge.stderr)
        self.assertNotIn("Traceback", huge.stderr)


if __name__ == "__main__":
    unittest.main()
