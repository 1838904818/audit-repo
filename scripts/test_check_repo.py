#!/usr/bin/env python3
"""Integration tests for the one-command audit runner."""

from __future__ import annotations

import json
import os
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

    def test_creates_snapshot_and_report_without_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            result = self.run_check(repository_dir, "--scan-mode", "filesystem", "--output-dir", output_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(Path(output_dir, "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["file_count"], 1)
            report = Path(output_dir, "report.md").read_text(encoding="utf-8")
            self.assertIn("# Repository signals", report)
            self.assertIn("Files scanned: 1", report)

    def test_compares_baseline_and_writes_action_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
            first = self.run_check(repository_dir, "--scan-mode", "filesystem", "--scope-id", "test", "--output-dir", first_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            github_output = Path(second_dir, "github-output.txt")
            second = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", second_dir, "--baseline", str(Path(first_dir, "snapshot.json")),
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
            self.assertIn("tool-version=1.8.1\n", outputs)
            self.assertIn("scan-semantics-version=1\n", outputs)
            self.assertIn("tool_version=1.8.1\n", second.stdout)

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


if __name__ == "__main__":
    unittest.main()
