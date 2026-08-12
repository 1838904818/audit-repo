#!/usr/bin/env python3
"""Unit tests for compare_repo_signals.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("compare_repo_signals.py")
SPEC = importlib.util.spec_from_file_location("compare_repo_signals", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def snapshot(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "root": "/repo",
        "file_count": 10,
        "scan_truncated": False,
        "excluded_directory_names": [],
        "large_file_threshold_bytes": 5 * 1024 * 1024,
        "test_file_count": 2,
        "work_markers": {"TODO": 1},
        "ci_files": [".github/workflows/ci.yml"],
        "documentation": ["README.md"],
        "license_files": ["LICENSE"],
        "manifests": ["pyproject.toml"],
        "lockfiles": [],
        "ci_action_references": ["actions/checkout@v7"],
        "dependency_update_config": [],
        "codeowners": [],
        "container_files": [],
        "environment_examples": [],
        "sensitive_looking_files": [],
        "large_files": [],
        "automation": {"configured_tools": ["pytest"]},
    }
    base.update(overrides)
    return base


class CompareRepoSignalsTests(unittest.TestCase):
    def test_reports_high_confidence_attention_items(self) -> None:
        before = snapshot()
        after = snapshot(
            file_count=12,
            test_file_count=0,
            work_markers={"TODO": 3},
            ci_files=[],
            sensitive_looking_files=[{"path": ".env", "tracked": True}],
            large_files=[{"path": "model.bin", "bytes": 8_000_000}],
        )

        result = MODULE.compare(before, after)
        codes = {item["code"] for item in result["attention"]}
        rendered = MODULE.to_markdown(result)

        self.assertIn("tests-disappeared", codes)
        self.assertIn("ci_files-removed", codes)
        self.assertIn("sensitive-filename-added", codes)
        self.assertIn("large-file-added", codes)
        self.assertIn("work-markers-increased", codes)
        self.assertIn("`.env`", rendered)
        self.assertEqual(result["summary"]["attention_count"], 5)

    def test_reports_configuration_mismatch_as_limit(self) -> None:
        before = snapshot(excluded_directory_names=["generated"])
        after = snapshot(large_file_threshold_bytes=1_048_576, scan_truncated=True)

        result = MODULE.compare(before, after)

        self.assertFalse(result["summary"]["comparable"])
        self.assertEqual(len(result["limitations"]), 3)
        self.assertIn("scan-truncated", {item["code"] for item in result["attention"]})

    def test_loads_legacy_snapshot_and_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            path.write_text(json.dumps({"root": "/legacy"}), encoding="utf-8")
            self.assertEqual(MODULE.load_snapshot(path)["root"], "/legacy")

            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.load_snapshot(path)

    def test_cli_fail_on_attention_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before_path = Path(temp_dir) / "before.json"
            after_path = Path(temp_dir) / "after.json"
            before_path.write_text(json.dumps(snapshot()), encoding="utf-8")
            after_path.write_text(
                json.dumps(snapshot(sensitive_looking_files=[{"path": ".env", "tracked": True}])),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(before_path), str(after_path), "--fail-on-attention"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Sensitive-looking filename added", result.stdout)
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
