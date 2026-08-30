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
        "tool_version": "1.8.1",
        "scan_semantics_version": 1,
        "root": "/repo",
        "file_count": 10,
        "scan_mode": "filesystem",
        "include_path_patterns": [],
        "exclude_path_patterns": [],
        "scope_id": None,
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

    def test_renders_attention_and_limitations_as_sarif_signals(self) -> None:
        result = MODULE.compare(
            snapshot(),
            snapshot(scan_file_limit=100_000, work_markers={"TODO": 2}),
        )

        sarif = MODULE.to_sarif(result)
        run = sarif["runs"][0]
        rendered = run["results"]

        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(run["tool"]["driver"]["name"], "audit-repo")
        self.assertEqual(run["properties"]["beforeProvenance"]["tool_version"], "1.8.1")
        self.assertEqual(run["properties"]["afterProvenance"]["scan_semantics_version"], 1)
        self.assertEqual({item["ruleId"] for item in rendered}, {"work-markers-increased", "comparison-limitation"})
        self.assertEqual({item["level"] for item in rendered}, {"warning", "note"})
        self.assertIn("not confirmed vulnerabilities", run["properties"]["notice"])

    def test_reports_scan_file_limit_mismatch(self) -> None:
        result = MODULE.compare(snapshot(scan_file_limit=50_000), snapshot(scan_file_limit=100_000))

        self.assertFalse(result["summary"]["comparable"])
        self.assertTrue(result["summary"]["logical_scope_comparable"])
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

    def test_scan_semantics_provenance_controls_comparability(self) -> None:
        same = MODULE.compare(snapshot(tool_version="1.7.0"), snapshot(tool_version="1.8.0"))
        self.assertTrue(same["summary"]["comparable"])

        changed = MODULE.compare(snapshot(), snapshot(scan_semantics_version=2, ci_files=[]))
        self.assertFalse(changed["summary"]["logical_scope_comparable"])
        self.assertEqual(changed["attention"], [])
        self.assertTrue(any("semantics versions differ" in item for item in changed["limitations"]))

        legacy = snapshot()
        legacy.pop("scan_semantics_version")
        mixed = MODULE.compare(legacy, snapshot())
        self.assertFalse(mixed["summary"]["comparable"])
        self.assertTrue(any("unavailable in one snapshot" in item for item in mixed["limitations"]))

        older_before = snapshot()
        older_after = snapshot()
        older_before.pop("scan_semantics_version")
        older_after.pop("scan_semantics_version")
        self.assertTrue(MODULE.compare(older_before, older_after)["summary"]["comparable"])

    def test_different_unreached_scan_limits_do_not_suppress_attention(self) -> None:
        result = MODULE.compare(
            snapshot(scan_file_limit=50_000),
            snapshot(scan_file_limit=100_000, work_markers={"TODO": 2}, ci_files=[]),
        )
        codes = {item["code"] for item in result["attention"]}

        self.assertFalse(result["summary"]["comparable"])
        self.assertTrue(result["summary"]["logical_scope_comparable"])
        self.assertTrue(result["summary"]["scans_complete"])
        self.assertIn("work-markers-increased", codes)
        self.assertIn("ci_files-removed", codes)
        self.assertFalse(any("logical scan scopes" in item for item in result["limitations"]))

    def test_scan_scope_mismatch_suppresses_unreliable_attention(self) -> None:
        before = snapshot()
        after = snapshot(
            scan_mode="tracked",
            include_path_patterns=["packages/api/*"],
            scope_id="api",
            ci_files=[],
            test_file_count=0,
            work_markers={"TODO": 9},
            sensitive_looking_files=[{"path": ".env", "tracked": True}],
            large_files=[{"path": "new.bin", "bytes": 10_000_000}],
        )

        result = MODULE.compare(before, after)
        codes = {item["code"] for item in result["attention"]}

        self.assertFalse(result["summary"]["comparable"])
        self.assertEqual(codes, set())
        self.assertTrue(any("scan modes differ" in item for item in result["limitations"]))
        self.assertTrue(any("included path globs differ" in item for item in result["limitations"]))
        self.assertTrue(any("scope IDs differ" in item for item in result["limitations"]))

    def test_legacy_scope_defaults_match_new_filesystem_defaults(self) -> None:
        legacy = snapshot()
        for field in ("scan_mode", "include_path_patterns", "exclude_path_patterns", "scope_id"):
            legacy.pop(field)

        result = MODULE.compare(legacy, snapshot())

        self.assertTrue(result["summary"]["comparable"])
        self.assertEqual(result["limitations"], [])

    def test_shared_scope_id_allows_equivalent_checkouts_at_different_roots(self) -> None:
        without_id = MODULE.compare(snapshot(root="/runner-a/repo"), snapshot(root="/runner-b/repo"))
        with_id = MODULE.compare(
            snapshot(root="/runner-a/repo", scope_id="whole-repository"),
            snapshot(root="/runner-b/repo", scope_id="whole-repository"),
        )

        self.assertFalse(without_id["summary"]["comparable"])
        self.assertTrue(any("roots differ" in item for item in without_id["limitations"]))
        self.assertTrue(with_id["summary"]["comparable"])

    def test_comparison_markdown_displays_both_complete_path_scopes(self) -> None:
        result = MODULE.compare(
            snapshot(scope_id="api", include_path_patterns=["packages/api/*"]),
            snapshot(scope_id="web", exclude_path_patterns=["packages/web/generated/*"]),
        )

        rendered = MODULE.to_markdown(result)

        self.assertIn("Before scope ID: `api`", rendered)
        self.assertIn("After scope ID: `web`", rendered)
        self.assertIn("Before collector version: `1.8.1`", rendered)
        self.assertIn("After scan semantics version: `1`", rendered)
        self.assertIn("Before included path globs: `packages/api/*`", rendered)
        self.assertIn("After excluded path globs: `packages/web/generated/*`", rendered)

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

    def test_explicit_incomplete_scan_suppresses_scope_dependent_attention(self) -> None:
        result = MODULE.compare(
            snapshot(),
            snapshot(
                scan_incomplete_reasons=["permission-denied"],
                work_markers={"TODO": 9},
                test_file_count=0,
                ci_files=[],
                sensitive_looking_files=[{"path": ".env", "tracked": True}],
                large_files=[{"path": "new.bin", "bytes": 10_000_000}],
            ),
        )

        self.assertFalse(result["summary"]["comparable"])
        self.assertTrue(result["summary"]["logical_scope_comparable"])
        self.assertFalse(result["summary"]["scans_complete"])
        self.assertEqual(result["attention"], [])
        self.assertTrue(any("reports an incomplete scan" in item for item in result["limitations"]))

    def test_sensitive_tracking_attention_requires_false_to_true_transition(self) -> None:
        unknown_to_tracked = MODULE.compare(
            snapshot(sensitive_looking_files=[{"path": ".env", "tracked": None}]),
            snapshot(sensitive_looking_files=[{"path": ".env", "tracked": True}]),
        )
        untracked_to_tracked = MODULE.compare(
            snapshot(sensitive_looking_files=[{"path": ".env", "tracked": False}]),
            snapshot(sensitive_looking_files=[{"path": ".env", "tracked": True}]),
        )

        self.assertNotIn(
            "sensitive-file-now-tracked",
            {item["code"] for item in unknown_to_tracked["attention"]},
        )
        self.assertIn(
            "sensitive-file-now-tracked",
            {item["code"] for item in untracked_to_tracked["attention"]},
        )

    def test_reports_significant_growth_of_existing_large_file(self) -> None:
        before = snapshot(large_files=[{"path": "model.bin", "bytes": 6_000_000}])
        after = snapshot(large_files=[{"path": "model.bin", "bytes": 6_000_000_000}])

        result = MODULE.compare(before, after)
        codes = {item["code"] for item in result["attention"]}
        change = next(item for item in result["changes"] if item["field"] == "large_files")

        self.assertIn("large-file-grew-significantly", codes)
        self.assertEqual(change["resized"][0]["path"], "model.bin")
        self.assertIn("5.6 GiB", MODULE.to_markdown(result))

    def test_threshold_mismatch_keeps_common_growth_but_suppresses_inventory_deltas(self) -> None:
        result = MODULE.compare(
            snapshot(
                large_file_threshold_bytes=5 * 1024 * 1024,
                large_files=[{"path": "model.bin", "bytes": 6 * 1024 * 1024}],
            ),
            snapshot(
                large_file_threshold_bytes=1024 * 1024,
                large_files=[
                    {"path": "model.bin", "bytes": 12 * 1024 * 1024},
                    {"path": "threshold-only.bin", "bytes": 2 * 1024 * 1024},
                ],
            ),
        )

        change = next(item for item in result["changes"] if item["field"] == "large_files")
        self.assertEqual(change["added"], [])
        self.assertEqual(change["resized"][0]["path"], "model.bin")
        self.assertIn("large-file-grew-significantly", {item["code"] for item in result["attention"]})
        self.assertTrue(any("additions and removals" in item for item in result["limitations"]))

    def test_arbitrarily_large_byte_counts_do_not_use_floats(self) -> None:
        huge = 10**400
        result = MODULE.compare(
            snapshot(large_files=[{"path": "model.bin", "bytes": huge}]),
            snapshot(large_files=[{"path": "model.bin", "bytes": huge * 2}]),
        )

        self.assertIn(
            "large-file-grew-significantly",
            {item["code"] for item in result["attention"]},
        )
        self.assertIn("YiB", MODULE.to_markdown(result))
        self.assertIn("YiB", MODULE.human_bytes(10**10_000))
        self.assertIn("YiB", MODULE.human_bytes(-(10**10_000)))

    def test_loads_legacy_snapshot_and_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            legacy = snapshot(root="/legacy")
            legacy.pop("schema_version")
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertEqual(MODULE.load_snapshot(path)["root"], "/legacy")

            for impostor in ({}, {"schema_version": 1}, {"root": "/not-a-snapshot"}):
                with self.subTest(impostor=impostor):
                    path.write_text(json.dumps(impostor), encoding="utf-8")
                    with self.assertRaises(MODULE.SnapshotError):
                        MODULE.load_snapshot(path)

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

            for invalid_mode in ("unknown", 1, []):
                with self.subTest(scan_mode=invalid_mode):
                    path.write_text(json.dumps({"schema_version": 1, "scan_mode": invalid_mode}), encoding="utf-8")
                    with self.assertRaises(MODULE.SnapshotError):
                        MODULE.load_snapshot(path)

            for invalid_scope_id in ("", "   ", "\N{NO-BREAK SPACE}", "line\nfeed", "x" * 201, 1, []):
                with self.subTest(scope_id=invalid_scope_id):
                    path.write_text(
                        json.dumps({"schema_version": 1, "scope_id": invalid_scope_id}),
                        encoding="utf-8",
                    )
                    with self.assertRaises(MODULE.SnapshotError):
                        MODULE.load_snapshot(path)

            for invalid_tool_version in ("", "   ", "line\nfeed", "x" * 101, 1, []):
                with self.subTest(tool_version=invalid_tool_version):
                    path.write_text(
                        json.dumps(snapshot(tool_version=invalid_tool_version)),
                        encoding="utf-8",
                    )
                    with self.assertRaises(MODULE.SnapshotError):
                        MODULE.load_snapshot(path)

            for invalid_semantics_version in (0, -1, True, "1", None):
                with self.subTest(scan_semantics_version=invalid_semantics_version):
                    path.write_text(
                        json.dumps(snapshot(scan_semantics_version=invalid_semantics_version)),
                        encoding="utf-8",
                    )
                    with self.assertRaises(MODULE.SnapshotError):
                        MODULE.load_snapshot(path)

            for invalid_reasons in (None, "permission-denied", [1]):
                with self.subTest(scan_incomplete_reasons=invalid_reasons):
                    path.write_text(
                        json.dumps({"schema_version": 1, "scan_incomplete_reasons": invalid_reasons}),
                        encoding="utf-8",
                    )
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

    def test_cli_require_comparable_handles_limitations_only_and_combines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before_path = Path(temp_dir) / "before.json"
            after_path = Path(temp_dir) / "after.json"
            before_path.write_text(json.dumps(snapshot()), encoding="utf-8")
            after_path.write_text(
                json.dumps(snapshot(scan_incomplete_reasons=["permission-denied"])),
                encoding="utf-8",
            )

            without_gate = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(before_path), str(after_path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            with_gate = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    str(before_path),
                    str(after_path),
                    "--require-comparable",
                    "--fail-on-attention",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(without_gate.returncode, 0)
            self.assertEqual(with_gate.returncode, 1)
            self.assertIn("Attention items: 0", with_gate.stdout)
            self.assertIn("Directly comparable: no", with_gate.stdout)
            self.assertEqual(with_gate.stderr, "")

            after_path.write_text(
                json.dumps(snapshot(sensitive_looking_files=[{"path": ".env", "tracked": True}])),
                encoding="utf-8",
            )
            comparable_with_attention = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    str(before_path),
                    str(after_path),
                    "--require-comparable",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            both_gates = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    str(before_path),
                    str(after_path),
                    "--require-comparable",
                    "--fail-on-attention",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(comparable_with_attention.returncode, 0)
            self.assertEqual(both_gates.returncode, 1)

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

            before_path.write_text("[" * 1200 + "0" + "]" * 1200, encoding="utf-8")
            nested = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(before_path), str(after_path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(nested.returncode, 2)
            self.assertIn("error:", nested.stderr)
            self.assertNotIn("Traceback", nested.stderr)

    def test_cli_rejects_oversized_marker_counts_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before_path = Path(temp_dir) / "before.json"
            after_path = Path(temp_dir) / "after.json"
            before_path.write_text(json.dumps(snapshot()), encoding="utf-8")
            huge_marker = 10**4299
            after_path.write_text(
                json.dumps(snapshot(work_markers={str(index): huge_marker for index in range(10)})),
                encoding="utf-8",
            )

            for output_format in ("markdown", "json", "sarif"):
                with self.subTest(output_format=output_format):
                    result = subprocess.run(
                        [
                            sys.executable, str(MODULE_PATH), str(before_path), str(after_path),
                            "--format", output_format,
                        ],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("work_markers", result.stderr)
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

    def test_cli_safely_compares_collector_surrogate_paths_in_each_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before_path = Path(temp_dir) / "before.json"
            after_path = Path(temp_dir) / "after.json"
            before_path.write_text(json.dumps(snapshot(root="\ud800")), encoding="utf-8")
            after_path.write_text(json.dumps(snapshot()), encoding="utf-8")

            for output_format in ("markdown", "json", "sarif"):
                with self.subTest(output_format=output_format):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(MODULE_PATH),
                            str(before_path),
                            str(after_path),
                            "--format",
                            output_format,
                        ],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=10,
                    )

                    self.assertEqual(result.returncode, 0)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(result.stderr, "")
                    result.stdout.encode("utf-8")
                    if output_format in ("json", "sarif"):
                        self.assertIn("\\ud800", result.stdout)
                    else:
                        self.assertIn("?", result.stdout)

    def test_markdown_escapes_untrusted_snapshot_fields(self) -> None:
        before = snapshot(root="repo`\n\n## Forged result")
        after = snapshot(
            root="after",
            sensitive_looking_files=[{"path": ".env`\n- forged", "tracked": True}],
        )

        rendered = MODULE.to_markdown(MODULE.compare(before, after))

        self.assertNotIn("\n## Forged result", rendered)
        self.assertNotIn("\n- forged", rendered)

    def test_markdown_escapes_new_scope_fields_and_surrogates(self) -> None:
        malicious_scope = "api`\n\n## Forged scope"
        malicious_glob = "packages/*`\n- forged scope item"
        result = MODULE.compare(
            snapshot(scope_id=malicious_scope, include_path_patterns=[malicious_glob]),
            snapshot(scope_id=malicious_scope, include_path_patterns=[malicious_glob]),
        )

        rendered = MODULE.to_markdown(result)

        self.assertNotIn("\n## Forged scope", rendered)
        self.assertNotIn("\n- forged scope item", rendered)
        self.assertEqual(MODULE.markdown_code("bad\ud800value"), "`bad?value`")


if __name__ == "__main__":
    unittest.main()
