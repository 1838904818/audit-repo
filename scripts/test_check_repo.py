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
            self.assertIn("tool-version=1.9.0\n", outputs)
            self.assertIn("scan-semantics-version=2\n", outputs)
            self.assertIn("tool_version=1.9.0\n", second.stdout)

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

    def test_failed_comparison_does_not_leave_prior_reports(self) -> None:
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

            failed = self.run_check(
                repository_dir, "--scan-mode", "filesystem", "--scope-id", "test",
                "--output-dir", output_dir, "--baseline", str(invalid),
            )

            self.assertEqual(failed.returncode, 2)
            self.assertTrue(Path(output_dir, "snapshot.json").is_file())
            for stale_name in ("report.md", "comparison.json", "comparison.sarif"):
                self.assertFalse(Path(output_dir, stale_name).exists())

    def test_managed_output_directory_collision_fails_without_recursive_removal(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as output_dir:
            Path(repository_dir, "README.md").write_text("# Example\n", encoding="utf-8")
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
            self.assertIn("must not traverse a symbolic link inside the repository", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

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
            self.assertIn("must not traverse a symbolic link inside the repository", result.stderr)
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
            self.assertIn("must not traverse a symbolic link inside the repository", result.stderr)
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
            self.assertIn("must not traverse a symbolic link inside the repository", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_preserves_parent_segments_after_repository_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
            result = self.run_check(
                str(repository), "--scan-mode", "filesystem", "--output-dir", str(requested_output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((repository / "results" / "snapshot.json").is_file())
            self.assertFalse((root / "results").exists())

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
