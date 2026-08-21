#!/usr/bin/env python3
"""Integration tests for the one-command audit runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_repo.py")


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


if __name__ == "__main__":
    unittest.main()
