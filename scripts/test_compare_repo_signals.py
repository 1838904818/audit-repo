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
        "scan_file_limit": 50_000,
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
        "large_files_complete": True,
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

    def test_reports_scan_file_limit_mismatch(self) -> None:
        result = MODULE.compare(snapshot(scan_file_limit=50_000), snapshot(scan_file_limit=100_000))

        self.assertFalse(result["summary"]["comparable"])
        self.assertEqual(result["summary"]["attention_count"], 0)
        self.assertIn("scan file limits differ", result["limitations"][0])

        legacy = snapshot()
        legacy.pop("scan_file_limit")
        mixed_result = MODULE.compare(legacy, snapshot())
        self.assertTrue(any("unavailable in one snapshot" in item for item in mixed_result["limitations"]))

        older_before = snapshot()
        older_after = snapshot()
        older_before.pop("scan_file_limit")
        older_after.pop("scan_file_limit")
        self.assertTrue(MODULE.compare(older_before, older_after)["summary"]["comparable"])

    def test_legacy_top_20_large_file_list_suppresses_unreliable_additions(self) -> None:
        legacy_files = [{"path": f"large-{index:02}.bin", "bytes": 10_000_000 + index} for index in range(20)]
        before = snapshot(large_files=legacy_files)
        before.pop("large_files_complete")
        after = snapshot(large_files=legacy_files + [{"path": "possibly-old.bin", "bytes": 11_000_000}])

        result = MODULE.compare(before, after)
        codes = {item["code"] for item in result["attention"]}

        self.assertNotIn("large-file-added", codes)
        self.assertFalse(result["summary"]["comparable"])
        self.assertTrue(any("legacy top-20" in item for item in result["limitations"]))

    def test_truncated_scan_suppresses_unreliable_large_file_additions(self) -> None:
        before = snapshot(scan_truncated=True, large_files=[])
        after = snapshot(scan_truncated=True, large_files=[{"path": "already-there.bin", "bytes": 10_000_000}])

        result = MODULE.compare(before, after)
        codes = {item["code"] for item in result["attention"]}

        self.assertNotIn("large-file-added", codes)
        self.assertIn("scan-truncated", codes)
        self.assertFalse(any(change["field"] == "large_files" for change in result["changes"]))

    def test_reports_significant_growth_of_existing_large_file(self) -> None:
        before = snapshot(large_files=[{"path": "model.bin", "bytes": 6_000_000}])
        after = snapshot(large_files=[{"path": "model.bin", "bytes": 6_000_000_000}])

        result = MODULE.compare(before, after)
        codes = {item["code"] for item in result["attention"]}
        change = next(item for item in result["changes"] if item["field"] == "large_files")

        self.assertIn("large-file-grew-significantly", codes)
        self.assertEqual(change["resized"][0]["path"], "model.bin")
        self.assertIn("5.6 GiB", MODULE.to_markdown(result))

    def test_loads_legacy_snapshot_and_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            path.write_text(json.dumps({"root": "/legacy"}), encoding="utf-8")
            self.assertEqual(MODULE.load_snapshot(path)["root"], "/legacy")

            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.load_snapshot(path)

            path.write_text(json.dumps({"schema_version": 1, "scan_file_limit": 0}), encoding="utf-8")
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.load_snapshot(path)

            for invalid in (-1, True, "50000", None):
                with self.subTest(scan_file_limit=invalid):
                    path.write_text(json.dumps({"schema_version": 1, "scan_file_limit": invalid}), encoding="utf-8")
                    with self.assertRaises(MODULE.SnapshotError):
                        MODULE.load_snapshot(path)

    def test_markdown_bounds_large_change_lists_but_json_remains_complete(self) -> None:
        added = [{"path": f"large-{index:02}.bin", "bytes": 10_000_000} for index in range(25)]
        result = MODULE.compare(snapshot(), snapshot(large_files=added))
        change = next(item for item in result["changes"] if item["field"] == "large_files")
        rendered = MODULE.to_markdown(result)

        self.assertEqual(len(change["added"]), 25)
        self.assertEqual(result["summary"]["attention_count"], 25)
        self.assertIn("and 5 more in JSON output", rendered)

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

    def test_cli_rejects_malformed_snapshot_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before_path = Path(temp_dir) / "before.json"
            after_path = Path(temp_dir) / "after.json"
            before_path.write_text(json.dumps(snapshot(large_files=None)), encoding="utf-8")
            after_path.write_text(json.dumps(snapshot()), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(before_path), str(after_path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must be a list", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_non_finite_json_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before_path = Path(temp_dir) / "before.json"
            after_path = Path(temp_dir) / "after.json"
            before_path.write_text('{"schema_version":1,"file_count":NaN}', encoding="utf-8")
            after_path.write_text(json.dumps(snapshot()), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(before_path), str(after_path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("non-finite JSON number", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_markdown_escapes_untrusted_snapshot_fields(self) -> None:
        before = snapshot(root="repo`\n\n## Forged result")
        after = snapshot(
            root="after",
            sensitive_looking_files=[{"path": ".env`\n- forged", "tracked": True}],
        )

        rendered = MODULE.to_markdown(MODULE.compare(before, after))

        self.assertNotIn("\n## Forged result", rendered)
        self.assertNotIn("\n- forged", rendered)


if __name__ == "__main__":
    unittest.main()
