#!/usr/bin/env python3
"""Integration tests for the one-command audit runner."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import importlib.util


SCRIPT = Path(__file__).with_name("check_repo.py")
SPEC = importlib.util.spec_from_file_location("check_repo", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CheckRepoTests(unittest.TestCase):
    def run_check(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], text=True, capture_output=True, check=False)

    def test_collector_nonzero_status_is_an_execution_error(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            first = MODULE.collect_snapshot([sys.executable, "-c", "raise SystemExit(1)"])
            second = MODULE.collect_snapshot([sys.executable, "-c", "raise SystemExit(17)"])
        self.assertEqual(first, (2, None, None))
        self.assertEqual(second, (2, None, None))
        self.assertIn("exit status 1", errors.getvalue())
        self.assertIn("exit status 17", errors.getvalue())

    def test_leading_hyphen_collection_values_round_trip_to_collector(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            repository.joinpath("--generated", "excluded").mkdir(parents=True)
            repository.joinpath("--generated", "keep.txt").write_text("keep\n", encoding="utf-8")
            repository.joinpath("--generated", "excluded", "drop.txt").write_text("drop\n", encoding="utf-8")
            repository.joinpath("--cache").mkdir()
            repository.joinpath("--cache", "hidden.txt").write_text("hidden\n", encoding="utf-8")

            result = self.run_check(
                repository_dir,
                "--scan-mode=filesystem",
                "--scope-id=--scope",
                "--include-path=*",
                "--include-path=--generated/*",
                "--exclude-path=--generated/excluded/*",
                "--exclude-dir=--cache",
                f"--output-dir={output_dir}",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(Path(output_dir, "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["scope_id"], "--scope")
            self.assertEqual(snapshot["include_path_patterns"], ["*", "--generated/*"])
            self.assertEqual(snapshot["exclude_path_patterns"], ["--generated/excluded/*"])
            self.assertEqual(snapshot["excluded_directory_names"], ["--cache"])
            self.assertEqual(snapshot["file_count"], 2)
            self.assertEqual(snapshot["documentation"], ["README.md"])

    def test_creates_snapshot_and_report_without_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            result = self.run_check(repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(Path(output_dir, "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["file_count"], 1)
            self.assertIsNone(snapshot["scope_id"])
            report = Path(output_dir, "report.md").read_text(encoding="utf-8")
            self.assertIn("# Repository signals", report)
            self.assertIn("Files scanned: 1", report)

    def test_compares_baseline_and_writes_action_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", first_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            github_output = Path(second_dir, "github-output.txt")
            baseline = Path(first_dir, "snapshot.json")
            baseline_sha256 = hashlib.sha256(baseline.read_bytes()).hexdigest().upper()
            second = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", second_dir, "--baseline", str(baseline),
                "--baseline-sha256", baseline_sha256,
                "--fail-on-attention", "--require-comparable", "--github-output", str(github_output),
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(Path(second_dir, "comparison.json").is_file())
            sarif = json.loads(Path(second_dir, "comparison.sarif").read_text(encoding="utf-8"))
            self.assertEqual(sarif["version"], "2.1.0")
            outputs = github_output.read_text(encoding="utf-8")
            self.assertIn("attention-count=0\n", outputs)
            self.assertIn("comparable=true\n", outputs)
            self.assertIn("sarif=", outputs)
            self.assertIn("tool-version=1.10.4\n", outputs)
            self.assertIn("scan-semantics-version=3\n", outputs)
            self.assertIn("tool_version=1.10.4\n", second.stdout)

    def test_comparison_gates_require_baseline_before_output_cleanup(self) -> None:
        gate_combinations = (
            ("--fail-on-attention",),
            ("--require-comparable",),
            ("--fail-on-attention", "--require-comparable"),
        )
        for gates in gate_combinations:
            with self.subTest(gates=gates), tempfile.TemporaryDirectory() as repository_dir, \
                    tempfile.TemporaryDirectory() as output_dir:
                Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
                sentinels = {
                    name: f"preserve {name}\n"
                    for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
                }
                for name, content in sentinels.items():
                    Path(output_dir, name).write_text(content, encoding="utf-8")

                result = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir, *gates,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("requires --baseline", result.stderr)
                for name, content in sentinels.items():
                    self.assertEqual(Path(output_dir, name).read_text(encoding="utf-8"), content)

    def test_collection_option_preflight_has_no_output_side_effects(self) -> None:
        cases = (
            ("max-files", ("--max-files", "0"), "--max-files must be positive"),
            ("large-nan", ("--large-file-mib", "nan"), "--large-file-mib must be positive"),
            ("large-infinity", ("--large-file-mib", "inf"), "--large-file-mib must be positive"),
            ("large-zero", ("--large-file-mib", "0"), "--large-file-mib must be positive"),
            ("large-negative", ("--large-file-mib", "-1"), "--large-file-mib must be positive"),
            ("large-overflow", ("--large-file-mib", "1e308"), "--large-file-mib is too large"),
            ("include", ("--include-path", "../secret/*"), "path patterns"),
            ("exclude", ("--exclude-path", "/absolute/*"), "path patterns"),
            ("exclude-dir", ("--exclude-dir", "nested/name"), "--exclude-dir values"),
            ("scope", ("--scope-id", "   "), "--scope-id"),
        )
        for label, invalid_arguments, message in cases:
            for output_mode in ("existing", "missing", "temporary"):
                with self.subTest(label=label, output_mode=output_mode), \
                        tempfile.TemporaryDirectory() as repository_dir, \
                        tempfile.TemporaryDirectory() as parent_dir:
                    repository = Path(repository_dir)
                    repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
                    parent = Path(parent_dir)
                    github_output = parent / "github-output.txt"
                    original_github_output = b"preserve github output\n"
                    github_output.write_bytes(original_github_output)

                    sentinels: dict[str, bytes] = {}
                    if output_mode == "temporary":
                        output_arguments = ("--temporary-output-parent", str(parent / "temporary"))
                        temporary_parent = parent / "temporary"
                        temporary_parent.mkdir()
                        children_before = sorted(temporary_parent.iterdir())
                    else:
                        output_dir = parent / "results"
                        output_arguments = ("--output-dir", str(output_dir))
                        if output_mode == "existing":
                            output_dir.mkdir()
                            sentinels = {
                                name: f"preserve {name}\n".encode()
                                for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
                            }
                            for name, content in sentinels.items():
                                output_dir.joinpath(name).write_bytes(content)

                    result = self.run_check(
                        repository_dir,
                        "--scan-mode", "filesystem",
                        *output_arguments,
                        *invalid_arguments,
                        "--github-output", str(github_output),
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(github_output.read_bytes(), original_github_output)
                    if output_mode == "temporary":
                        self.assertEqual(sorted(temporary_parent.iterdir()), children_before)
                    elif output_mode == "missing":
                        self.assertFalse(output_dir.exists())
                    else:
                        for name, content in sentinels.items():
                            self.assertEqual(output_dir.joinpath(name).read_bytes(), content)

    def test_collector_failures_preserve_outputs_and_do_not_allocate_temporary_results(self) -> None:
        cases = (
            ("missing-root", "filesystem", "not a directory"),
            ("tracked-non-git", "tracked", "requires a Git working tree"),
        )
        for label, scan_mode, message in cases:
            for output_mode in ("existing", "temporary"):
                with self.subTest(label=label, output_mode=output_mode), \
                        tempfile.TemporaryDirectory() as root_dir, \
                        tempfile.TemporaryDirectory() as output_parent_dir:
                    root = Path(root_dir)
                    repository = root / "repository"
                    if label == "tracked-non-git":
                        repository.mkdir()
                        repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
                    output_parent = Path(output_parent_dir)
                    github_output = output_parent / "github-output.txt"
                    original_github_output = b"preserve github output\n"
                    github_output.write_bytes(original_github_output)

                    sentinels: dict[str, bytes] = {}
                    if output_mode == "existing":
                        output_dir = output_parent / "results"
                        output_dir.mkdir()
                        sentinels = {
                            name: f"preserve {name}\n".encode()
                            for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
                        }
                        for name, content in sentinels.items():
                            output_dir.joinpath(name).write_bytes(content)
                        output_arguments = ("--output-dir", str(output_dir))
                    else:
                        temporary_parent = output_parent / "temporary"
                        temporary_parent.mkdir()
                        unrelated = temporary_parent / "keep.txt"
                        unrelated.write_text("preserve me\n", encoding="utf-8")
                        children_before = sorted(temporary_parent.iterdir())
                        output_arguments = ("--temporary-output-parent", str(temporary_parent))

                    result = self.run_check(
                        str(repository),
                        "--scan-mode", scan_mode,
                        *output_arguments,
                        "--github-output", str(github_output),
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(github_output.read_bytes(), original_github_output)
                    if output_mode == "existing":
                        for name, content in sentinels.items():
                            self.assertEqual(output_dir.joinpath(name).read_bytes(), content)
                    else:
                        self.assertEqual(sorted(temporary_parent.iterdir()), children_before)
                        self.assertEqual(list(temporary_parent.glob("audit-repo-*")), [])

    def test_baseline_digest_requires_baseline_before_output_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as github_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            sentinels = {
                name: f"preserve {name}\n"
                for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
            }
            for name, content in sentinels.items():
                Path(output_dir, name).write_text(content, encoding="utf-8")
            github_output = Path(github_dir, "github-output.txt")
            github_output.write_text("preserve github output\n", encoding="utf-8")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir,
                "--baseline-sha256", "0" * 64, "--github-output", str(github_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("--baseline-sha256 requires --baseline", result.stderr)
            for name, content in sentinels.items():
                self.assertEqual(Path(output_dir, name).read_text(encoding="utf-8"), content)
            self.assertEqual(github_output.read_text(encoding="utf-8"), "preserve github output\n")

    def test_rejects_malformed_baseline_digest_before_output_cleanup(self) -> None:
        invalid_values = (
            "", "0" * 63, "0" * 65, "g" * 64, f" {'0' * 64}",
            f"{'0' * 64} ", f"{'0' * 64}\n", f"sha256:{'0' * 64}",
        )
        for invalid in invalid_values:
            with self.subTest(invalid=repr(invalid)), tempfile.TemporaryDirectory() as repository_dir, \
                    tempfile.TemporaryDirectory() as baseline_dir, tempfile.TemporaryDirectory() as output_dir, \
                    tempfile.TemporaryDirectory() as github_dir:
                Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
                created = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--output-dir", baseline_dir,
                )
                self.assertEqual(created.returncode, 0, created.stderr)
                sentinel = Path(output_dir, "snapshot.json")
                sentinel.write_text("preserve snapshot\n", encoding="utf-8")
                github_output = Path(github_dir, "github-output.txt")
                github_output.write_text("preserve github output\n", encoding="utf-8")

                result = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir,
                    "--baseline", str(Path(baseline_dir, "snapshot.json")),
                    "--baseline-sha256", invalid, "--github-output", str(github_output),
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("must be exactly 64 hexadecimal characters", result.stderr)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve snapshot\n")
                self.assertEqual(github_output.read_text(encoding="utf-8"), "preserve github output\n")

    def test_rejects_wrong_baseline_digest_before_any_managed_output_changes(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as github_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            created = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", baseline_dir,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            actual = hashlib.sha256(baseline.read_bytes()).hexdigest()
            wrong = ("1" if actual[0] == "0" else "0") + actual[1:]
            sentinels = {
                name: f"preserve {name}\n"
                for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
            }
            for name, content in sentinels.items():
                Path(output_dir, name).write_text(content, encoding="utf-8")
            github_output = Path(github_dir, "github-output.txt")
            github_output.write_text("preserve github output\n", encoding="utf-8")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(baseline),
                "--baseline-sha256", wrong, "--github-output", str(github_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("baseline SHA-256 mismatch", result.stderr)
            for name, content in sentinels.items():
                self.assertEqual(Path(output_dir, name).read_text(encoding="utf-8"), content)
            self.assertEqual(github_output.read_text(encoding="utf-8"), "preserve github output\n")

    def test_loaded_baseline_is_frozen_after_digest_verification(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            created = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", baseline_dir,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
            loaded = MODULE.load_baseline(baseline, digest.upper())
            original_root = loaded["root"]
            replacement = json.loads(baseline.read_text(encoding="utf-8"))
            replacement["root"] = "/changed-after-verification"
            baseline.write_text(json.dumps(replacement), encoding="utf-8")

            self.assertEqual(loaded["root"], original_root)
            with self.assertRaisesRegex(MODULE.BaselineError, "baseline SHA-256 mismatch"):
                MODULE.load_baseline(baseline, digest)

    def test_baseline_preflight_failures_create_no_output_and_preserve_github_output(self) -> None:
        cases = {
            "missing": None,
            "non-utf8": b"\xff",
            "invalid-json": b"{",
            "invalid-schema": b'{"schema_version":999}',
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as repository_dir, \
                    tempfile.TemporaryDirectory() as baseline_dir, tempfile.TemporaryDirectory() as parent_dir:
                Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
                baseline = Path(baseline_dir, f"{label}.json")
                arguments = ["--baseline", str(baseline)]
                if content is not None:
                    baseline.write_bytes(content)
                    arguments.extend(("--baseline-sha256", hashlib.sha256(content).hexdigest()))
                output_dir = Path(parent_dir, "not-created")
                github_output = Path(parent_dir, "github-output.txt")
                original_github_output = b"preserve github output\n"
                github_output.write_bytes(original_github_output)

                result = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--output-dir", str(output_dir),
                    *arguments, "--github-output", str(github_output),
                )

                self.assertEqual(result.returncode, 2)
                self.assertFalse(output_dir.exists())
                self.assertEqual(github_output.read_bytes(), original_github_output)

    def test_duplicate_key_baseline_with_matching_digest_has_no_output_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            created = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", baseline_dir,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            valid = baseline.read_bytes()
            ambiguous = b'{"root":"review-visible-root",' + valid[1:]
            self.assertNotEqual(ambiguous, valid)
            baseline.write_bytes(ambiguous)
            digest = hashlib.sha256(ambiguous).hexdigest()

            for output_mode in ("existing", "missing", "temporary"):
                with self.subTest(output_mode=output_mode), tempfile.TemporaryDirectory() as parent_dir:
                    parent = Path(parent_dir)
                    github_output = parent / "github-output.txt"
                    original_github_output = b"preserve github output\n"
                    github_output.write_bytes(original_github_output)
                    sentinels: dict[str, bytes] = {}
                    if output_mode == "temporary":
                        temporary_parent = parent / "temporary"
                        temporary_parent.mkdir()
                        output_arguments = ("--temporary-output-parent", str(temporary_parent))
                        children_before = sorted(temporary_parent.iterdir())
                    else:
                        output_dir = parent / "results"
                        output_arguments = ("--output-dir", str(output_dir))
                        if output_mode == "existing":
                            output_dir.mkdir()
                            sentinels = {
                                name: f"preserve {name}\r\n".encode()
                                for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
                            }
                            for name, content in sentinels.items():
                                output_dir.joinpath(name).write_bytes(content)

                    result = self.run_check(
                        repository_dir,
                        "--scan-mode", "filesystem",
                        *output_arguments,
                        "--baseline", str(baseline),
                        "--baseline-sha256", digest,
                        "--github-output", str(github_output),
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertIn("duplicate JSON object key 'root'", result.stderr)
                    self.assertNotIn("SHA-256 mismatch", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(github_output.read_bytes(), original_github_output)
                    if output_mode == "temporary":
                        self.assertEqual(sorted(temporary_parent.iterdir()), children_before)
                    elif output_mode == "missing":
                        self.assertFalse(output_dir.exists())
                    else:
                        for name, content in sentinels.items():
                            self.assertEqual(output_dir.joinpath(name).read_bytes(), content)

    def test_oversized_baseline_has_no_output_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            baseline = Path(baseline_dir, "oversized.json")
            with baseline.open("wb") as stream:
                stream.truncate(MODULE.comparer.MAX_SNAPSHOT_BYTES + 1)

            for output_mode in ("existing", "missing", "temporary"):
                for expected_digest in (None, "0" * 64):
                    with self.subTest(
                        output_mode=output_mode, digest=expected_digest is not None,
                    ), tempfile.TemporaryDirectory() as parent_dir:
                        digest_arguments = () if expected_digest is None else (
                            "--baseline-sha256", expected_digest,
                        )
                        parent = Path(parent_dir)
                        github_output = parent / "github-output.txt"
                        original_github_output = b"preserve github output\n"
                        github_output.write_bytes(original_github_output)
                        sentinels: dict[str, bytes] = {}
                        if output_mode == "temporary":
                            temporary_parent = parent / "temporary"
                            temporary_parent.mkdir()
                            output_arguments = ("--temporary-output-parent", str(temporary_parent))
                            children_before = sorted(temporary_parent.iterdir())
                        else:
                            output_dir = parent / "results"
                            output_arguments = ("--output-dir", str(output_dir))
                            if output_mode == "existing":
                                output_dir.mkdir()
                                sentinels = {
                                    name: f"preserve {name}\r\n".encode()
                                    for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
                                }
                                for name, content in sentinels.items():
                                    output_dir.joinpath(name).write_bytes(content)

                        result = self.run_check(
                            repository_dir,
                            "--scan-mode", "filesystem",
                            *output_arguments,
                            "--baseline", str(baseline),
                            *digest_arguments,
                            "--github-output", str(github_output),
                        )

                        self.assertEqual(result.returncode, 2)
                        self.assertIn("67108864-byte limit", result.stderr)
                        self.assertNotIn("SHA-256 mismatch", result.stderr)
                        self.assertNotIn("Traceback", result.stderr)
                        self.assertEqual(github_output.read_bytes(), original_github_output)
                        if output_mode == "temporary":
                            self.assertEqual(sorted(temporary_parent.iterdir()), children_before)
                        elif output_mode == "missing":
                            self.assertFalse(output_dir.exists())
                        else:
                            for name, content in sentinels.items():
                                self.assertEqual(output_dir.joinpath(name).read_bytes(), content)

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain control characters")
    def test_runner_escapes_control_characters_in_baseline_error_paths(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as parent_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            parent = Path(parent_dir)
            github_output = parent / "github-output.txt"
            original_github_output = b"preserve github output\n"
            github_output.write_bytes(original_github_output)
            cases = {"oversized": None, "invalid-json": b"{"}
            for label, content in cases.items():
                with self.subTest(label=label):
                    baseline = parent / f"{label}.json\n::warning title=forged::{label}"
                    if content is None:
                        with baseline.open("wb") as stream:
                            stream.truncate(MODULE.comparer.MAX_SNAPSHOT_BYTES + 1)
                    else:
                        baseline.write_bytes(content)
                    output_dir = parent / f"results-{label}"
                    result = self.run_check(
                        repository_dir,
                        "--scan-mode", "filesystem",
                        "--output-dir", str(output_dir),
                        "--baseline", str(baseline),
                        "--github-output", str(github_output),
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                    self.assertIn(r"\n::warning title=forged::", result.stderr)
                    self.assertNotIn("\n::warning title=forged::", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertFalse(output_dir.exists())
                    self.assertEqual(github_output.read_bytes(), original_github_output)

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain control characters")
    def test_runner_escapes_control_characters_in_repository_and_output_errors(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as parent_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            parent = Path(parent_dir)
            github_output = parent / "github-output.txt"
            original_github_output = b"preserve github output\n"
            github_output.write_bytes(original_github_output)

            missing_root = parent / "missing\n::warning title=forged::scan-root"
            missing_output = parent / "missing-root-results"
            missing = self.run_check(
                str(missing_root), "--scan-mode", "filesystem",
                "--output-dir", str(missing_output),
                "--github-output", str(github_output),
            )

            collision_output = parent / "results\n::warning title=forged::managed-output"
            collision_output.mkdir()
            collision_output.joinpath("snapshot.json").mkdir()
            collision = self.run_check(
                repository_dir, "--scan-mode", "filesystem",
                "--output-dir", str(collision_output),
                "--github-output", str(github_output),
            )

            for result, marker in (
                (missing, "scan-root"), (collision, "managed-output"),
            ):
                with self.subTest(marker=marker):
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                    self.assertIn(rf"\n::warning title=forged::{marker}", result.stderr)
                    self.assertNotIn(f"\n::warning title=forged::{marker}", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(missing_output.exists())
            self.assertTrue(collision_output.joinpath("snapshot.json").is_dir())
            self.assertEqual(github_output.read_bytes(), original_github_output)

    def test_baseline_digest_covers_trailing_newline_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as parent_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            created = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", baseline_dir,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            digest_before = hashlib.sha256(baseline.read_bytes()).hexdigest()
            baseline.write_bytes(baseline.read_bytes() + b"\n")
            output_dir = Path(parent_dir, "not-created")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", str(output_dir),
                "--baseline", str(baseline), "--baseline-sha256", digest_before,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("baseline SHA-256 mismatch", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_wrong_digest_allocates_no_temporary_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as temporary_parent:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            created = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", baseline_dir,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            before = sorted(Path(temporary_parent).iterdir())

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem",
                "--temporary-output-parent", temporary_parent,
                "--baseline", str(baseline), "--baseline-sha256", "0" * 64,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("baseline SHA-256 mismatch", result.stderr)
            self.assertEqual(sorted(Path(temporary_parent).iterdir()), before)

    def test_temporary_output_parent_allocates_unique_output_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as temporary_parent:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem",
                "--temporary-output-parent", temporary_parent,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            children = list(Path(temporary_parent).iterdir())
            self.assertEqual(len(children), 1)
            output_dir = children[0]
            self.assertTrue(output_dir.name.startswith("audit-repo-"))
            self.assertTrue(output_dir.joinpath("snapshot.json").is_file())
            self.assertTrue(output_dir.joinpath("report.md").is_file())
            stdout_values = dict(line.split("=", 1) for line in result.stdout.splitlines())
            self.assertEqual(
                Path(stdout_values["snapshot"]).resolve(),
                output_dir.joinpath("snapshot.json").resolve(),
            )

    def test_rejects_temporary_output_parent_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            temporary_parent = repository / "untrusted-temp"

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem",
                "--temporary-output-parent", str(temporary_parent),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("temporary output parent must be outside", result.stderr)
            self.assertFalse(temporary_parent.exists())

    def test_github_outputs_use_multiline_records_for_untrusted_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir, "github-output.txt")
            value = "/tmp/report\nforged=true\rsecond-line"

            self.assertTrue(MODULE.write_github_outputs(output, {"report": value, "comparable": "true"}))
            rendered = output.read_text(encoding="utf-8")
            first_line, *lines = rendered.splitlines()
            key, delimiter = first_line.split("<<", 1)

            self.assertEqual(key, "report")
            self.assertTrue(delimiter.startswith("audit_repo_"))
            self.assertEqual(lines[-2], delimiter)
            self.assertEqual(lines[-1], "comparable=true")
            self.assertNotIn("report=/tmp/report\n", rendered)

    def test_rejects_baseline_that_is_any_generated_output(self) -> None:
        for output_name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif"):
            with self.subTest(output_name=output_name), tempfile.TemporaryDirectory() as repository_dir, \
                    tempfile.TemporaryDirectory() as baseline_dir, tempfile.TemporaryDirectory() as output_dir:
                repository = Path(repository_dir)
                repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
                first = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                    "--output-dir", baseline_dir,
                )
                self.assertEqual(first.returncode, 0, first.stderr)
                original = Path(baseline_dir, "snapshot.json").read_bytes()
                baseline = Path(output_dir, output_name)
                baseline.write_bytes(original)
                repository.joinpath(".env").write_text("", encoding="utf-8")

                second = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                    "--output-dir", output_dir, "--baseline", str(baseline), "--fail-on-attention",
                )

                self.assertEqual(second.returncode, 2)
                self.assertIn("baseline must not alias any generated output", second.stderr)
                self.assertEqual(baseline.read_bytes(), original)

    def test_rejects_hard_link_alias_of_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", baseline_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            generated = Path(output_dir, "snapshot.json")
            generated.write_bytes(Path(baseline_dir, "snapshot.json").read_bytes())
            baseline = Path(baseline_dir, "hard-link-baseline.json")
            try:
                os.link(generated, baseline)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")
            original = baseline.read_bytes()

            second = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(baseline),
            )

            self.assertEqual(second.returncode, 2)
            self.assertIn("baseline must not alias any generated output", second.stderr)
            self.assertEqual(baseline.read_bytes(), original)

    def test_rejects_github_output_that_is_any_generated_output(self) -> None:
        for output_name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif"):
            with self.subTest(output_name=output_name), tempfile.TemporaryDirectory() as repository_dir, \
                    tempfile.TemporaryDirectory() as output_dir:
                Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
                github_output = Path(output_dir, output_name)
                github_output.write_text("preserve me\n", encoding="utf-8")

                result = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir,
                    "--github-output", str(github_output),
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("GitHub output must not alias any generated output", result.stderr)
                self.assertEqual(github_output.read_text(encoding="utf-8"), "preserve me\n")

    def test_rejects_hard_link_alias_for_github_output(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as github_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            generated = Path(output_dir, "snapshot.json")
            generated.write_text("preserve me\n", encoding="utf-8")
            github_output = Path(github_dir, "github-output.txt")
            try:
                os.link(generated, github_output)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir,
                "--github-output", str(github_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("GitHub output must not alias any generated output", result.stderr)
            self.assertEqual(generated.read_text(encoding="utf-8"), "preserve me\n")
            self.assertEqual(github_output.read_text(encoding="utf-8"), "preserve me\n")

    def test_rejects_baseline_that_is_the_github_output(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", baseline_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            original = baseline.read_bytes()

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(baseline),
                "--github-output", str(baseline),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("GitHub output must not alias the baseline", result.stderr)
            self.assertEqual(baseline.read_bytes(), original)
            self.assertEqual(list(Path(output_dir).iterdir()), [])

    def test_rejects_hard_link_alias_between_baseline_and_github_output(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as github_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", baseline_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            github_output = Path(github_dir, "github-output.txt")
            try:
                os.link(baseline, github_output)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")
            original = baseline.read_bytes()

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(baseline),
                "--github-output", str(github_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("GitHub output must not alias the baseline", result.stderr)
            self.assertEqual(baseline.read_bytes(), original)
            self.assertEqual(github_output.read_bytes(), original)
            self.assertEqual(list(Path(output_dir).iterdir()), [])

    def test_reused_output_dir_removes_stale_comparison_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", baseline_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            compared = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(baseline),
            )
            self.assertEqual(compared.returncode, 0, compared.stderr)
            keep = Path(output_dir, "keep.txt")
            keep.write_text("preserve me\n", encoding="utf-8")

            current = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", output_dir,
            )

            self.assertEqual(current.returncode, 0, current.stderr)
            self.assertTrue(Path(output_dir, "snapshot.json").is_file())
            self.assertTrue(Path(output_dir, "report.md").is_file())
            self.assertFalse(Path(output_dir, "comparison.json").exists())
            self.assertFalse(Path(output_dir, "comparison.sarif").exists())
            self.assertEqual(keep.read_text(encoding="utf-8"), "preserve me\n")

    def test_in_repository_output_rerun_clears_managed_files_before_filesystem_scan(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir:
            repository = Path(repository_dir).resolve()
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            output_dir = repository / "audit-repo-results"

            first = self.run_check(
                str(repository), "--scan-mode", "filesystem", "--output-dir", str(output_dir),
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(output_dir.joinpath("snapshot.json").read_text(encoding="utf-8"))["file_count"], 1)

            for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif"):
                output_dir.joinpath(name).write_text(f"stale {name}\n", encoding="utf-8")

            second = self.run_check(
                str(repository), "--scan-mode", "filesystem", "--output-dir", str(output_dir),
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            snapshot = json.loads(output_dir.joinpath("snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["file_count"], 1)
            self.assertEqual(Path(snapshot["root"]), repository)
            self.assertFalse(output_dir.joinpath("comparison.json").exists())
            self.assertFalse(output_dir.joinpath("comparison.sarif").exists())
            stdout_values = dict(line.split("=", 1) for line in second.stdout.splitlines())
            self.assertEqual(Path(stdout_values["snapshot"]), output_dir / "snapshot.json")
            self.assertEqual(Path(stdout_values["report"]), output_dir / "report.md")

    def test_invalid_baseline_preserves_prior_outputs_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as baseline_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", baseline_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            baseline = Path(baseline_dir, "snapshot.json")
            compared = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(baseline),
            )
            self.assertEqual(compared.returncode, 0, compared.stderr)
            invalid = Path(baseline_dir, "invalid.json")
            invalid.write_text("{", encoding="utf-8")
            preserved = {
                name: Path(output_dir, name).read_bytes()
                for name in ("snapshot.json", "report.md", "comparison.json", "comparison.sarif")
            }

            failed = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(invalid),
            )

            self.assertEqual(failed.returncode, 2)
            self.assertIn("invalid JSON", failed.stderr)
            for name, content in preserved.items():
                self.assertEqual(Path(output_dir, name).read_bytes(), content)

    def test_managed_output_directory_collision_fails_without_recursive_removal(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            sentinels = {
                "snapshot.json": "preserve snapshot\n",
                "report.md": "preserve report\n",
                "comparison.sarif": "preserve sarif\n",
            }
            for name, content in sentinels.items():
                Path(output_dir, name).write_text(content, encoding="utf-8")
            collision = Path(output_dir, "comparison.json")
            collision.mkdir()
            child = collision / "keep.txt"
            child.write_text("preserve me\n", encoding="utf-8")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("could not remove stale generated output", result.stderr)
            self.assertEqual(child.read_text(encoding="utf-8"), "preserve me\n")
            for name, content in sentinels.items():
                self.assertEqual(Path(output_dir, name).read_text(encoding="utf-8"), content)

    def test_rejects_output_directory_symlink_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as external_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = Path(external_dir)
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            linked_output = repository / "audit-repo-results"
            try:
                linked_output.symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", str(linked_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not traverse a symbolic link or reparse point", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    @unittest.skipUnless(os.name == "posix", "missing-parent redirect regression requires POSIX")
    def test_rejects_symlink_reached_after_missing_parent_segment(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as external_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = Path(external_dir)
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            linked_output = repository / "results"
            try:
                linked_output.symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")
            requested_output = repository / "does-not-exist" / ".." / "results"

            result = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--output-dir", str(requested_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not traverse a symbolic link or reparse point", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    @unittest.skipUnless(os.name == "nt", "junction boundary test requires Windows")
    def test_rejects_output_directory_junction_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as external_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = Path(external_dir)
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            junction = repository / "audit-repo-results"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(external)],
                text=True,
                capture_output=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junctions unavailable: {created.stderr or created.stdout}")
            try:
                self.assertTrue(junction.exists())
                self.assertTrue(
                    junction.lstat().st_file_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                )

                result = self.run_check(
                    repository_dir, "--scan-mode", "filesystem", "--output-dir", str(junction),
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("must not traverse a symbolic link or reparse point", result.stderr)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")
            finally:
                if junction.exists():
                    junction.rmdir()

    @unittest.skipUnless(os.name == "posix", "monorepo symlink boundary test requires POSIX")
    def test_rejects_output_symlink_in_scanned_subdirectory_worktree_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as worktree_dir, tempfile.TemporaryDirectory() as external_dir:
            worktree = Path(worktree_dir)
            worktree.joinpath(".git").mkdir()
            repository = worktree / "packages" / "app"
            repository.mkdir(parents=True)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = Path(external_dir)
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            linked_output = worktree / "audit-output"
            linked_output.symlink_to(external, target_is_directory=True)

            result = self.run_check(
                str(repository), "--scan-mode", "filesystem", "--output-dir", str(linked_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("containing Git worktree", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    @unittest.skipUnless(os.name == "nt", "monorepo junction boundary test requires Windows")
    def test_rejects_output_junction_in_scanned_subdirectory_worktree_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as worktree_dir, tempfile.TemporaryDirectory() as external_dir:
            worktree = Path(worktree_dir)
            worktree.joinpath(".git").mkdir()
            repository = worktree / "packages" / "app"
            repository.mkdir(parents=True)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = Path(external_dir)
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            junction = worktree / "audit-output"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(external)],
                text=True,
                capture_output=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junctions unavailable: {created.stderr or created.stdout}")
            try:
                result = self.run_check(
                    str(repository), "--scan-mode", "filesystem", "--output-dir", str(junction),
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("containing Git worktree", result.stderr)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")
            finally:
                if junction.exists():
                    junction.rmdir()

    def test_rejects_repo_output_symlink_through_repository_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / "repository"
            repository.mkdir()
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = root / "external"
            external.mkdir()
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            linked_output = repository / "results"
            repository_alias = root / "repository-alias"
            try:
                linked_output.symlink_to(external, target_is_directory=True)
                repository_alias.symlink_to(repository, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            result = self.run_check(
                str(repository_alias), "--scan-mode", "filesystem",
                "--output-dir", str(repository_alias / "results"),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not traverse a symbolic link or reparse point", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_rejects_repo_output_symlink_through_different_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / "repository"
            repository.mkdir()
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = root / "external"
            external.mkdir()
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            linked_output = repository / "results"
            other_alias = root / "other-repository-alias"
            try:
                linked_output.symlink_to(external, target_is_directory=True)
                other_alias.symlink_to(repository, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            result = self.run_check(
                str(repository), "--scan-mode", "filesystem",
                "--output-dir", str(other_alias / "results"),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not traverse a symbolic link or reparse point", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_rejects_repo_output_symlink_through_case_variant(self) -> None:
        test_parent = SCRIPT.resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=test_parent) as temp_dir:
            root = Path(temp_dir).resolve()
            repository = root / "CaseRepo"
            repository.mkdir()
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = root / "external"
            external.mkdir()
            sentinel = external / "snapshot.json"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            linked_output = repository / "OutputLink"
            try:
                linked_output.symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")
            variant_output = root / "CASEREPO" / "OUTPUTLINK"
            if not variant_output.is_symlink():
                self.skipTest("test volume is case-sensitive")

            result = self.run_check(
                str(repository), "--scan-mode", "filesystem", "--output-dir", str(variant_output),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not traverse a symbolic link or reparse point", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_preserves_parent_segments_after_repository_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repository = root / "repository"
            subdirectory = repository / "subdirectory"
            subdirectory.mkdir(parents=True)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            alias = root / "subdirectory-alias"
            try:
                alias.symlink_to(subdirectory, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            requested_output = alias / ".." / "results"
            resolved_output = requested_output.resolve()
            result = self.run_check(
                str(repository), "--scan-mode", "filesystem", "--output-dir", str(requested_output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((resolved_output / "snapshot.json").is_file())
            self.assertFalse((subdirectory / "results").exists())

    @unittest.skipUnless(os.name == "posix", "Git symlink boundary test requires POSIX")
    def test_runner_never_executes_git_from_lexical_symlink_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            repository = Path(temp_dir).resolve()
            repository.joinpath(".git").mkdir()
            external = Path(external_dir).resolve()
            scan_link = repository / "scan"
            tools = repository / "tools"
            tools.mkdir()
            marker = repository / "fake-git-invoked"
            fake_git = tools / "git"
            fake_git.write_text(
                "#!/bin/sh\n: > \"$AUDIT_REPO_FAKE_GIT_MARKER\"\nexit 0\n",
                encoding="utf-8",
            )
            fake_git.chmod(fake_git.stat().st_mode | 0o111)
            scan_link.symlink_to(external, target_is_directory=True)
            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join((str(tools), environment.get("PATH", "")))
            environment["AUDIT_REPO_FAKE_GIT_MARKER"] = str(marker)

            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), str(scan_link), "--scan-mode", "tracked",
                    "--output-dir", output_dir,
                ],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("requires a Git working tree", result.stderr)
            self.assertFalse(marker.exists())

    def test_default_scope_does_not_authorize_cross_root_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as first_repository, tempfile.TemporaryDirectory() as second_repository, \
                tempfile.TemporaryDirectory() as baseline_dir, tempfile.TemporaryDirectory() as output_dir:
            Path(first_repository, "README.md").write_text("# First\n", encoding="utf-8")
            Path(second_repository, "README.md").write_text("# Second\n", encoding="utf-8")
            first = self.run_check(
                first_repository, "--scan-mode", "filesystem", "--output-dir", baseline_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = self.run_check(
                second_repository, "--scan-mode", "filesystem", "--output-dir", output_dir,
                "--baseline", str(Path(baseline_dir, "snapshot.json")), "--require-comparable",
            )

            self.assertEqual(second.returncode, 1, second.stderr)
            comparison = json.loads(Path(output_dir, "comparison.json").read_text(encoding="utf-8"))
            self.assertFalse(comparison["summary"]["comparable"])
            self.assertTrue(any("roots differ" in item for item in comparison["limitations"]))


if __name__ == "__main__":
    unittest.main()
