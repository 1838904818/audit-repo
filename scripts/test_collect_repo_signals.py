#!/usr/bin/env python3
"""Unit tests for collect_repo_signals.py."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("collect_repo_signals.py")
SPEC = importlib.util.spec_from_file_location("collect_repo_signals", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CollectRepoSignalsTests(unittest.TestCase):
    def test_git_resolution_ignores_current_directory_and_repo_path_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            fake_git = root / ("git.exe" if os.name == "nt" else "git")
            shutil.copy2(sys.executable, fake_git)
            if os.name != "nt":
                fake_git.chmod(fake_git.stat().st_mode | 0o111)
            original_path = os.environ.get("PATH", "")
            poisoned_path = os.pathsep.join(("", ".", str(root), original_path))
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with mock.patch.dict(os.environ, {"PATH": poisoned_path}, clear=False):
                    resolved = MODULE.resolve_git_executable(root)
            finally:
                os.chdir(previous_cwd)

            if resolved is None:
                self.skipTest("trusted Git executable unavailable outside the test repository")
            self.assertTrue(resolved.is_absolute())
            self.assertNotEqual(resolved, fake_git.resolve())
            self.assertFalse(MODULE.path_is_within(resolved, root))

    def test_git_resolution_excludes_entire_containing_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir).resolve()
            repository.joinpath(".git").mkdir()
            target = repository / "packages" / "api"
            target.mkdir(parents=True)
            target.joinpath(".git").write_text("spoofed nested marker\n", encoding="utf-8")
            tools = repository / "tools"
            tools.mkdir()
            fake_git = tools / ("git.exe" if os.name == "nt" else "git")
            shutil.copy2(sys.executable, fake_git)
            if os.name != "nt":
                fake_git.chmod(fake_git.stat().st_mode | 0o111)
            poisoned_path = os.pathsep.join((str(tools), os.environ.get("PATH", "")))

            with mock.patch.dict(os.environ, {"PATH": poisoned_path}, clear=False):
                resolved = MODULE.resolve_git_executable(target)

            if resolved is None:
                self.skipTest("trusted Git executable unavailable outside the test worktree")
            self.assertEqual(MODULE.git_worktree_boundary(target), repository)
            self.assertFalse(MODULE.path_is_within(resolved, repository))
            self.assertNotEqual(resolved, fake_git.resolve())

    def test_git_resolution_excludes_lexical_symlink_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            repository = Path(temp_dir).resolve()
            repository.joinpath(".git").mkdir()
            external = Path(external_dir).resolve()
            scan_link = repository / "scan"
            tools = repository / "tools"
            tools.mkdir()
            fake_git = tools / ("git.exe" if os.name == "nt" else "git")
            shutil.copy2(sys.executable, fake_git)
            if os.name != "nt":
                fake_git.chmod(fake_git.stat().st_mode | 0o111)
            try:
                scan_link.symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")
            poisoned_path = os.pathsep.join((str(tools), os.environ.get("PATH", "")))

            with mock.patch.dict(os.environ, {"PATH": poisoned_path}, clear=False):
                resolved = MODULE.resolve_git_executable(
                    scan_link.resolve(), git_untrusted_roots=(scan_link,),
                )

            if resolved is None:
                self.skipTest("trusted Git executable unavailable outside the test worktree")
            self.assertFalse(MODULE.path_is_within(resolved, repository))
            self.assertNotEqual(resolved, fake_git.resolve())

    def test_git_resolution_uses_filesystem_identity_for_case_variants(self) -> None:
        test_parent = MODULE_PATH.resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=test_parent) as temp_dir:
            root = Path(temp_dir).resolve()
            repository = root / "CaseRepo"
            repository.mkdir()
            repository.joinpath(".git").mkdir()
            tools = repository / "Tools"
            tools.mkdir()
            fake_git = tools / ("git.exe" if os.name == "nt" else "git")
            shutil.copy2(sys.executable, fake_git)
            if os.name != "nt":
                fake_git.chmod(fake_git.stat().st_mode | 0o111)
            variant_tools = root / "CASEREPO" / "TOOLS"
            if not variant_tools.is_dir():
                self.skipTest("test volume is case-sensitive")
            if MODULE.git_worktree_boundary(repository) != repository:
                self.skipTest("test repository is nested inside another worktree boundary")
            poisoned_path = os.pathsep.join((str(variant_tools), os.environ.get("PATH", "")))

            with mock.patch.dict(os.environ, {"PATH": poisoned_path}, clear=False):
                resolved = MODULE.resolve_git_executable(repository)

            if resolved is None:
                self.skipTest("trusted Git executable unavailable outside the test repository")
            self.assertTrue(MODULE.path_is_within(variant_tools.resolve() / fake_git.name, repository))
            self.assertNotEqual(resolved, fake_git.resolve())

    @unittest.skipUnless(os.name == "posix" and shutil.which("git"), "case-variant CLI test requires POSIX Git")
    def test_collector_cli_never_executes_case_variant_worktree_git(self) -> None:
        test_parent = MODULE_PATH.resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=test_parent) as temp_dir:
            root = Path(temp_dir).resolve()
            repository = root / "CaseRepo"
            repository.mkdir()
            trusted_git = Path(shutil.which("git") or "").resolve()
            subprocess.run(
                [str(trusted_git), "-C", str(repository), "init", "-q"],
                check=True,
                timeout=10,
            )
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            subprocess.run(
                [str(trusted_git), "-C", str(repository), "add", "README.md"],
                check=True,
                timeout=10,
            )
            tools = repository / "Tools"
            tools.mkdir()
            marker = repository / "fake-git-invoked"
            fake_git = tools / "git"
            fake_git.write_text(
                "#!/bin/sh\n: > \"$AUDIT_REPO_FAKE_GIT_MARKER\"\nexit 0\n",
                encoding="utf-8",
            )
            fake_git.chmod(fake_git.stat().st_mode | 0o111)
            variant_tools = root / "CASEREPO" / "TOOLS"
            if not variant_tools.is_dir():
                self.skipTest("test volume is case-sensitive")
            if MODULE.git_worktree_boundary(repository) != repository:
                self.skipTest("test repository is nested inside another worktree boundary")
            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join((str(variant_tools), environment.get("PATH", "")))
            environment["AUDIT_REPO_FAKE_GIT_MARKER"] = str(marker)

            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(repository), "--scan-mode", "tracked"],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix" and shutil.which("git"), "Git symlink boundary test requires POSIX")
    def test_collector_cli_never_executes_git_from_lexical_symlink_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
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
                [sys.executable, str(MODULE_PATH), str(scan_link), "--scan-mode", "tracked"],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("requires a Git working tree", result.stderr)
            self.assertFalse(marker.exists())

    def test_git_commands_disable_repo_execution_and_optional_locks(self) -> None:
        trusted_git = Path("C:/trusted/git.exe") if os.name == "nt" else Path("/trusted/git")
        completed = subprocess.CompletedProcess([], 0, stdout=b"")
        with mock.patch.object(MODULE, "resolve_git_executable", return_value=trusted_git), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run_mock:
            self.assertEqual(MODULE.git_tracked_files(Path("/audit-target")), set())

        command = run_mock.call_args.args[0]
        environment = run_mock.call_args.kwargs["env"]
        self.assertEqual(command[0], str(trusted_git))
        self.assertIn(f"core.hooksPath={MODULE.DISABLED_GIT_HOOKS_PATH}", command)
        self.assertIn("core.fsmonitor=false", command)
        self.assertEqual(environment["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")

        with mock.patch.dict(os.environ, {"GIT_DIR": "attacker-controlled", "GIT_CONFIG_COUNT": "1"}):
            sanitized = MODULE.git_environment()
        self.assertNotIn("GIT_DIR", sanitized)
        self.assertNotIn("GIT_CONFIG_COUNT", sanitized)
        self.assertEqual(sanitized["GIT_PAGER"], "cat")

    def test_collection_target_uses_hardened_git_probe_and_wraps_os_errors(self) -> None:
        trusted_git = Path("C:/trusted/git.exe") if os.name == "nt" else Path("/trusted/git")
        completed = subprocess.CompletedProcess([], 0, stdout=b"true\n")
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(MODULE, "resolve_git_executable", return_value=trusted_git), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run_mock, \
                mock.patch.dict(os.environ, {"GIT_DIR": "attacker-controlled"}):
            root = Path(temp_dir).resolve()
            self.assertEqual(MODULE.validate_collection_target(root, "tracked"), root)

        command = run_mock.call_args.args[0]
        environment = run_mock.call_args.kwargs["env"]
        self.assertEqual(command[0], str(trusted_git))
        self.assertEqual(command[-2:], ["rev-parse", "--is-inside-work-tree"])
        self.assertIn(f"core.hooksPath={MODULE.DISABLED_GIT_HOOKS_PATH}", command)
        self.assertIn("core.fsmonitor=false", command)
        self.assertNotIn("GIT_DIR", environment)
        self.assertEqual(environment["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(MODULE, "resolve_git_executable", return_value=trusted_git), \
                mock.patch.object(MODULE.subprocess, "run", side_effect=PermissionError("blocked")):
            with self.assertRaisesRegex(MODULE.CollectionError, "could not run Git working-tree validation"):
                MODULE.validate_collection_target(Path(temp_dir), "tracked")

    def test_git_metadata_never_runs_status(self) -> None:
        root = Path("/audit-target")
        with mock.patch.object(MODULE, "git_output", return_value="main") as git_output:
            metadata = MODULE.git_metadata(root, {"README.md"})

        self.assertEqual(metadata["working_tree"], "unknown")
        git_output.assert_called_once_with(
            root, "branch", "--show-current", git_untrusted_roots=(),
        )

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
            (root / ".env.production.example").write_text("SECRET=placeholder", encoding="utf-8")
            (root / "credentials.json").write_text('{"note":"# TODO private"}', encoding="utf-8")
            (root / "client_secret.json").write_text('{"note":"# TODO oauth-secret"}', encoding="utf-8")
            (root / "secrets.yml").write_text("# TODO private", encoding="utf-8")
            (root / "terraform.tfstate.backup").write_text("# TODO private", encoding="utf-8")
            (root / ".aws").mkdir()
            (root / ".aws" / "credentials").write_text("# TODO private", encoding="utf-8")
            (root / ".cargo").mkdir()
            (root / ".cargo" / "credentials.toml").write_text("# TODO cargo-secret", encoding="utf-8")
            (root / ".config" / "gh").mkdir(parents=True)
            (root / ".config" / "gh" / "hosts.yml").write_text("# TODO gh-secret", encoding="utf-8")
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
            (root / ".github" / "workflows" / "secrets.yml").write_text(
                "# TODO private\nsteps:\n  - uses: private-sentinel/action@secret",
                encoding="utf-8",
            )
            (root / ".github" / "dependabot.yml").write_text("version: 2", encoding="utf-8")
            (root / ".github" / "CODEOWNERS").write_text("* @example", encoding="utf-8")

            data = MODULE.collect(root, 100)
            rendered = MODULE.to_markdown(data)

            self.assertEqual(data["tool_version"], "1.10.5")
            self.assertEqual(data["scan_semantics_version"], 3)
            self.assertIn("Collector version: `1.10.5`", rendered)
            self.assertIn("Scan semantics version: 3", rendered)
            self.assertFalse(data["git_repository"])
            self.assertEqual(data["test_file_count"], 1)
            self.assertEqual(data["manifests"], ["package.json", "pyproject.toml"])
            self.assertEqual(data["documentation"], ["README.md"])
            self.assertEqual(data["ci_files"], [".github/workflows/ci.yml", ".github/workflows/secrets.yml"])
            self.assertEqual(data["work_markers"]["TODO"], 1)
            self.assertNotIn("FIXME", data["work_markers"])
            self.assertEqual(
                [item["path"] for item in data["sensitive_looking_files"]],
                [
                    ".aws/credentials",
                    ".cargo/credentials.toml",
                    ".config/gh/hosts.yml",
                    ".env",
                    ".env.production",
                    ".github/workflows/secrets.yml",
                    "client_secret.json",
                    "credentials.json",
                    "secrets.yml",
                    "terraform.tfstate.backup",
                ],
            )
            self.assertEqual(data["environment_examples"], [".env.example", ".env.production.example"])
            self.assertEqual(data["automation"]["package_scripts"]["package.json"], ["lint", "test"])
            self.assertEqual(data["automation"]["make_targets"]["Makefile"], ["test"])
            self.assertIn("pytest", data["automation"]["configured_tools"])
            self.assertEqual(data["ci_action_references"], ["actions/checkout@v7"])
            self.assertEqual(data["dependency_update_config"], [".github/dependabot.yml"])
            self.assertEqual(data["codeowners"], [".github/CODEOWNERS"])
            self.assertEqual(data["container_files"], ["Dockerfile"])
            self.assertNotIn("do-not-print", rendered)
            self.assertNotIn("also-private", rendered)
            serialized = json.dumps(data)
            self.assertNotIn("do-not-print", serialized)
            self.assertNotIn("also-private", serialized)
            self.assertNotIn("private-sentinel", serialized)
            self.assertNotIn("oauth-secret", serialized)
            self.assertNotIn("cargo-secret", serialized)
            self.assertNotIn("gh-secret", serialized)

    def test_classifies_ci_tests_manifests_and_lockfiles_precisely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contents = {
                ".github/workflows/ci.yml": (
                    "steps:\n"
                    "  - run: |\n"
                    "      echo 'uses: fake/run-block@main'\n"
                    "      uses: fake/indented-run-block@main\n"
                    "  - run: >- # folded script\n"
                    "      uses: fake/folded-block@main\n"
                    "  - run: &shared |\n"
                    "      uses: fake/anchored-block@main\n"
                    "  - run: !!str &tagged >+\n"
                    "      uses: fake/tagged-block@main\n"
                    "  - uses: >-\n"
                    "      slackapi/slack-github-action@v2\n"
                    "  - uses: >-\n"
                    "      fake/multiline\n"
                    "      action@main\n"
                    "  - name: |\n"
                    "      Checkout source\n"
                    "    uses: actions/checkout@v7\n"
                    "  - uses: \"actions/setup-python@v5\"\n"
                    "  - uses: 'github/codeql-action/init@v3' # quoted and commented\n"
                    "  - uses : owner/action@v1 # space before colon\n"
                    "  - \"uses\" : actions/cache@v4\n"
                ),
                ".github/workflows/deploy.yaml": "name: Deploy\n",
                ".circleci/config.yml": "version: 2.1\n",
                ".gitlab-ci.yml": "test: {}\n",
                "azure-pipelines.yml": "steps: []\n",
                "bitbucket-pipelines.yml": "pipelines: {}\n",
                "Jenkinsfile": "pipeline {}\n",
                ".github/workflows/README.md": "- uses: fake/readme@main\n",
                ".github/workflows/ci.yml.disabled": "- uses: fake/disabled@main\n",
                ".github/workflows/archive/old.yml": "- uses: fake/archive@main\n",
                ".circleci/README.md": "- uses: fake/circle-readme@main\n",
                ".circleci/jobs/build.yml": "- uses: fake/circle-job@main\n",
                "docs/.github/workflows/ci.yml": "- uses: fake/docs@main\n",
            }
            test_files = ("tests.py", "app/tests.py", "CalculatorTests.cs", "Tests.cs")
            non_test_files = (
                "Tests.py", "Contests.cs", "Protests.cs", "Latest.cs", "WidgetTests.md",
                "Tests.csproj", "tests.py.example",
            )
            manifests = (
                "Pipfile", "Package.swift", "packages/api/App.csproj", "Core.fsproj",
                "Tool.vbproj", "Repo.sln", "Repo.slnx", "Package@swift-5.swift",
                "Package@swift-5.10.1.swift",
            )
            non_manifests = (
                "App.csproj.user", "Repo.sln.bak", "Package.swift.example", "Pipfile.md", ".sln",
                "pipfile", "package.swift", "App.CSPROJ", "Package@swift-5.10.1.2.swift",
                "Package@swift-x.swift",
            )
            lockfiles = (
                "Pipfile.lock", "Package.resolved", "packages.lock.json",
                "packages.Widget.lock.json", "packages/My.App/packages.My.App.lock.json",
                "bun.lock", "bun.lockb",
            )
            non_lockfiles = (
                "packages.lock.json.bak", "packages..lock.json", "packages.Widget.lock.json.bak",
                "PIPFILE.LOCK", "PACKAGE.RESOLVED", "bun.lock.old", "random.lock",
            )
            for relative, content in contents.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            for relative in (*test_files, *non_test_files, *manifests, *non_manifests, *lockfiles, *non_lockfiles):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            data = MODULE.collect(root, 200)

            self.assertFalse(MODULE.is_ci_file(".github/workflows/CI.YML"))
            self.assertEqual(data["ci_files"], sorted((
                ".github/workflows/ci.yml", ".github/workflows/deploy.yaml", ".circleci/config.yml",
                ".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile",
            )))
            self.assertEqual(data["ci_action_references"], [
                "actions/cache@v4", "actions/checkout@v7", "actions/setup-python@v5",
                "github/codeql-action/init@v3", "owner/action@v1",
                "slackapi/slack-github-action@v2",
            ])
            self.assertEqual(data["test_file_count"], len(test_files))
            self.assertEqual(data["test_file_examples"], sorted(test_files))
            self.assertEqual(data["manifests"], sorted((*manifests, "Tests.csproj")))
            self.assertEqual(data["lockfiles"], sorted(lockfiles))

    def test_sensitive_path_patterns_and_environment_examples(self) -> None:
        sensitive = (
            ".env.local",
            ".env.production",
            "AuthKey.p8",
            "release.JKS",
            "debug.keystore",
            "vault.kdbx",
            "terraform.tfstate",
            "terraform.tfstate.backup",
            "nested/.aws/credentials",
            "nested/.cargo/credentials.toml",
            "nested/.config/gh/hosts.yml",
            "nested/.docker/config.json",
            "nested/.kube/config",
        )
        safe_examples = (
            ".env.example",
            ".env.production.example",
            ".env.sample",
            "example.env",
            "id_rsa.pub",
        )

        for path in sensitive:
            with self.subTest(sensitive=path):
                self.assertTrue(MODULE.is_sensitive_filename(path))
        for path in safe_examples:
            with self.subTest(safe=path):
                self.assertFalse(MODULE.is_sensitive_filename(path))

    def test_scan_limit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                (root / f"file-{index}.txt").write_text("data", encoding="utf-8")

            data = MODULE.collect(root, 2)

            self.assertEqual(data["file_count"], 2)
            self.assertEqual(data["scan_file_limit"], 2)
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

    def test_filesystem_enumeration_errors_mark_scan_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            (root / "ok.py").write_text("print('ok')", encoding="utf-8")

            def walk_with_error(_root: Path, *, followlinks: bool, onerror: object):
                self.assertFalse(followlinks)
                assert callable(onerror)
                onerror(PermissionError("denied"))
                yield str(_root), [], ["ok.py"]

            with mock.patch.object(MODULE.os, "walk", side_effect=walk_with_error):
                data = MODULE.collect(root, 100)

            self.assertEqual(data["file_count"], 1)
            self.assertEqual(
                data["scan_incomplete_reasons"],
                ["filesystem_directories_unavailable_during_scan"],
            )

    def test_file_becoming_unavailable_during_analysis_marks_scan_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            readme = root / "README.md"
            readme.write_text("# Example", encoding="utf-8")
            original_stat = Path.stat
            readme_stat_calls = 0

            def flaky_stat(path: Path, *args: object, **kwargs: object):
                nonlocal readme_stat_calls
                if path == readme:
                    readme_stat_calls += 1
                    if readme_stat_calls >= 2:
                        raise PermissionError("became unavailable")
                return original_stat(path, *args, **kwargs)

            with mock.patch.object(Path, "stat", new=flaky_stat):
                data = MODULE.collect(root, 100)

            self.assertEqual(data["file_count"], 1)
            self.assertIn("README.md", data["documentation"])
            self.assertEqual(data["scan_incomplete_reasons"], ["paths_unavailable_during_analysis"])

    def test_malformed_package_json_complexity_does_not_abort_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package.json"
            for content in (
                '{"oversized":' + "9" * 5000 + "}",
                '{"nested":' + "[" * 1200 + "0" + "]" * 1200 + "}",
            ):
                with self.subTest(kind=content[:20]):
                    package.write_text(content, encoding="utf-8")
                    data = MODULE.collect(root, 100)
                    self.assertEqual(data["automation"]["package_scripts"], {"package.json": []})

    def test_json_keeps_complete_large_file_inventory_while_markdown_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(23):
                (root / f"large-{index:02}.bin").write_bytes(b"x" * (index + 1))

            data = MODULE.collect(root, 100, large_file_bytes=1)
            rendered = MODULE.to_markdown(data)

            self.assertEqual(len(data["large_files"]), 23)
            self.assertTrue(data["large_files_complete"])
            self.assertEqual(data["large_files"][0]["path"], "large-22.bin")
            self.assertIn("3 more recorded in JSON output", rendered)
            self.assertNotIn("`large-00.bin`", rendered)

    @unittest.skipUnless(os.name == "nt", "junction traversal regression requires Windows")
    def test_scan_modes_skip_repository_junctions(self) -> None:
        with tempfile.TemporaryDirectory() as repository_dir, tempfile.TemporaryDirectory() as external_dir:
            repository = Path(repository_dir)
            repository.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            external = Path(external_dir)
            external.joinpath("outside.py").write_text("# TODO must stay outside\n", encoding="utf-8")
            external.joinpath(".env").write_text("EXAMPLE_ONLY=not-a-secret\n", encoding="utf-8")
            junction = repository / "external-junction"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(external)],
                text=True,
                capture_output=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junctions unavailable: {created.stderr or created.stdout}")
            try:
                modes = ["filesystem"]
                if shutil.which("git"):
                    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True, timeout=10)
                    subprocess.run(
                        ["git", "-C", str(repository), "add", "README.md"], check=True, timeout=10,
                    )
                    modes.extend(("git-visible", "tracked"))

                for mode in modes:
                    with self.subTest(mode=mode):
                        data = MODULE.collect(repository, 100, scan_mode=mode)
                        self.assertEqual(data["file_count"], 1)
                        self.assertEqual(data["languages_by_file_count"].get("Python", 0), 0)
                        self.assertEqual(data["work_markers"], {})
                        self.assertEqual(data["sensitive_looking_files"], [])
            finally:
                if junction.exists():
                    junction.rmdir()

    @unittest.skipUnless(shutil.which("git"), "Git is required for scan-mode coverage")
    def test_git_scan_modes_distinguish_visible_tracked_and_ignored_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, timeout=10)
            (root / ".gitignore").write_text("ignored.py\n.env.local\n", encoding="utf-8")
            (root / "tracked.py").write_text("print('tracked')", encoding="utf-8")
            (root / "visible.py").write_text("print('visible')", encoding="utf-8")
            (root / "ignored.py").write_text("print('ignored')", encoding="utf-8")
            (root / ".env.local").write_text("SECRET=force-added", encoding="utf-8")
            (root / "packages" / "api").mkdir(parents=True)
            (root / "packages" / "api" / "app.py").write_text("print('api')", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", ".gitignore", "tracked.py", "packages/api/app.py"],
                check=True,
                timeout=10,
            )
            subprocess.run(
                ["git", "-C", str(root), "add", "-f", ".env.local"],
                check=True,
                timeout=10,
            )

            filesystem = MODULE.collect(root, 100, scan_mode="filesystem")
            visible = MODULE.collect(root, 100, scan_mode="git-visible")
            tracked = MODULE.collect(root, 100, scan_mode="tracked")
            subdirectory = MODULE.collect(root / "packages" / "api", 100, scan_mode="tracked")

            self.assertEqual(filesystem["languages_by_file_count"]["Python"], 4)
            self.assertEqual(visible["languages_by_file_count"]["Python"], 3)
            self.assertEqual(tracked["languages_by_file_count"]["Python"], 2)
            self.assertEqual(subdirectory["languages_by_file_count"]["Python"], 1)
            self.assertEqual(subdirectory["scan_mode"], "tracked")
            for snapshot in (filesystem, visible, tracked):
                sensitive = {item["path"]: item["tracked"] for item in snapshot["sensitive_looking_files"]}
                self.assertTrue(sensitive[".env.local"])
            self.assertEqual(visible["scan_incomplete_reasons"], [])
            self.assertEqual(tracked["scan_incomplete_reasons"], [])

    @unittest.skipUnless(os.name == "posix" and shutil.which("git"), "Git fsmonitor test requires POSIX")
    def test_git_collection_does_not_execute_repo_configured_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            git_executable = MODULE.resolve_git_executable(root)
            if git_executable is None:
                self.skipTest("trusted Git executable unavailable")
            subprocess.run([str(git_executable), "-C", str(root), "init", "-q"], check=True, timeout=10)
            root.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            subprocess.run([str(git_executable), "-C", str(root), "add", "README.md"], check=True, timeout=10)
            fsmonitor = root / "malicious-fsmonitor"
            fsmonitor.write_text(
                "#!/bin/sh\n: > \"$PWD/fsmonitor-invoked\"\nprintf '\\n'\n",
                encoding="utf-8",
            )
            fsmonitor.chmod(fsmonitor.stat().st_mode | 0o111)
            subprocess.run(
                [str(git_executable), "-C", str(root), "config", "core.fsmonitor", str(fsmonitor)],
                check=True,
                timeout=10,
            )

            data = MODULE.collect(root, 100, scan_mode="tracked")

            self.assertTrue(data["git_repository"])
            self.assertFalse((root / "fsmonitor-invoked").exists())

    @unittest.skipUnless(shutil.which("git"), "Git is required for scan-limit coverage")
    def test_git_limit_counts_only_files_after_path_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, timeout=10)
            for relative in ("outside.py", "keep/a.py", "keep/b.py", "keep/c.py"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("print('ok')", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, timeout=10)

            exact = MODULE.collect(
                root,
                2,
                scan_mode="tracked",
                include_paths=["keep/*"],
                exclude_paths=["keep/c.py"],
            )
            over_limit = MODULE.collect(root, 2, scan_mode="tracked", include_paths=["keep/*"])

            self.assertEqual(exact["file_count"], 2)
            self.assertFalse(exact["scan_truncated"])
            self.assertEqual(over_limit["file_count"], 2)
            self.assertTrue(over_limit["scan_truncated"])

    @unittest.skipUnless(shutil.which("git"), "Git is required for incomplete-scan coverage")
    def test_git_scan_reports_enumerated_paths_missing_from_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, timeout=10)
            (root / "present.py").write_text("print('present')", encoding="utf-8")
            missing = root / "missing.py"
            missing.write_text("print('missing')", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, timeout=10)
            missing.unlink()

            data = MODULE.collect(root, 100, scan_mode="tracked")
            rendered = MODULE.to_markdown(data)

            self.assertEqual(data["file_count"], 1)
            self.assertEqual(
                data["scan_incomplete_reasons"],
                ["git_enumerated_paths_missing_from_worktree"],
            )
            self.assertIn("Scan incomplete reasons", rendered)

    def test_path_globs_define_a_deterministic_case_sensitive_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative in (
                "packages/api/app.py",
                "packages/api/generated.py",
                "packages/api/README.md",
                "packages/web/app.py",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("content", encoding="utf-8")

            data = MODULE.collect(
                root,
                100,
                include_paths=["packages/api/*"],
                exclude_paths=["packages/api/generated*"],
                scope_id="api-package",
            )

            self.assertEqual(data["file_count"], 2)
            self.assertEqual(data["languages_by_file_count"], {"Python": 1})
            self.assertEqual(data["include_path_patterns"], ["packages/api/*"])
            self.assertEqual(data["exclude_path_patterns"], ["packages/api/generated*"])
            self.assertEqual(data["scope_id"], "api-package")
            self.assertIn("Scope ID: `api-package`", MODULE.to_markdown(data))
            self.assertFalse(MODULE.path_selected("packages/API/upper.py", ["packages/api/*"], []))

    def test_rejects_unsafe_path_globs_and_git_mode_outside_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(MODULE.normalize_path_patterns(["./packages/*"]), ["packages/*"])
            for pattern in (
                "", "/absolute/*", "C:/absolute/*", "../secret/*", "windows\\path\\*",
                "./C:/absolute/*", ".//absolute/*", "./../secret/*",
            ):
                with self.subTest(pattern=pattern):
                    with self.assertRaises(MODULE.CollectionError):
                        MODULE.collect(root, 100, include_paths=[pattern])
            with self.assertRaises(MODULE.CollectionError):
                MODULE.collect(root, 100, scope_id="   ")
            with self.assertRaises(MODULE.CollectionError):
                MODULE.collect(root, 100, scan_mode="tracked")

            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(root), "--scan-mode", "tracked"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires a Git working tree", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_shared_collection_option_validation_normalizes_and_rejects_invalid_values(self) -> None:
        threshold_bytes, includes, excludes, scope_id = MODULE.validate_collection_options(
            5,
            5.0,
            include_paths=["./packages/*", "packages/*"],
            exclude_paths=["./packages/generated/*", "packages/generated/*"],
            scope_id="api-package",
        )

        self.assertEqual(threshold_bytes, 5 * 1_048_576)
        self.assertEqual(includes, ["packages/*"])
        self.assertEqual(excludes, ["packages/generated/*"])
        self.assertEqual(scope_id, "api-package")

        cases = (
            ("max-files", 0, 5.0, (), (), None, "--max-files must be positive"),
            ("large-nan", 5, float("nan"), (), (), None, "--large-file-mib must be positive"),
            ("large-infinity", 5, float("inf"), (), (), None, "--large-file-mib must be positive"),
            ("large-zero", 5, 0.0, (), (), None, "--large-file-mib must be positive"),
            ("large-negative", 5, -1.0, (), (), None, "--large-file-mib must be positive"),
            ("large-overflow", 5, 1e308, (), (), None, "--large-file-mib is too large"),
            ("include", 5, 5.0, ("../secret/*",), (), None, "path patterns"),
            ("exclude", 5, 5.0, (), ("/absolute/*",), None, "path patterns"),
            ("scope", 5, 5.0, (), (), "   ", "--scope-id"),
        )
        for label, max_files, large_file_mib, include_paths, exclude_paths, candidate_scope, message in cases:
            with self.subTest(label=label), self.assertRaisesRegex(MODULE.CollectionError, message):
                MODULE.validate_collection_options(
                    max_files,
                    large_file_mib,
                    include_paths=include_paths,
                    exclude_paths=exclude_paths,
                    scope_id=candidate_scope,
                )

    def test_excluded_directory_names_are_normalized_and_strictly_validated(self) -> None:
        self.assertEqual(
            MODULE.normalize_excluded_directory_names(["Build", "build", "--cache"]),
            ["--cache", "build"],
        )

        for name in ("", "   ", ".", "..", "nested/name", "nested\\name", "line\nfeed", "bad\x7f"):
            with self.subTest(name=repr(name)), self.assertRaisesRegex(
                MODULE.CollectionError, "--exclude-dir values"
            ):
                MODULE.normalize_excluded_directory_names([name])

        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaisesRegex(
            MODULE.CollectionError, "--exclude-dir values"
        ):
            MODULE.collect(Path(temp_dir), 100, exclude_dirs=["nested/name"])

    def test_collector_rejects_invalid_excluded_directory_before_overwriting_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
            output = root / "existing.json"
            original = b"preserve existing output\r\n"
            output.write_bytes(original)

            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    str(root),
                    "--exclude-dir=nested/name",
                    "--format=json",
                    f"--output={output}",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("--exclude-dir values", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(output.read_bytes(), original)

    def test_markdown_escapes_untrusted_paths(self) -> None:
        data = MODULE.collect(Path(__file__).parent, 100)
        data["root"] = "repo`\n\n## Forged result\u2028still forged"
        data["scope_id"] = "scope`\n## Forged scope"
        data["include_path_patterns"] = ["src/*`\n## Forged include"]
        data["exclude_path_patterns"] = ["dist/*`\n## Forged exclude"]
        data["scan_incomplete_reasons"] = ["missing`\n## Forged reason"]
        data["git"]["branch"] = "main`\n## Forged branch"
        data["sensitive_looking_files"] = [{"path": "secret`\n- fake.md", "tracked": True}]

        rendered = MODULE.to_markdown(data)

        self.assertNotIn("\n## Forged result", rendered)
        self.assertNotIn("\n## Forged scope", rendered)
        self.assertNotIn("\n## Forged include", rendered)
        self.assertNotIn("\n## Forged exclude", rendered)
        self.assertNotIn("\n## Forged reason", rendered)
        self.assertNotIn("\n## Forged branch", rendered)
        self.assertNotIn("\n- fake.md", rendered)
        self.assertNotIn("\u2028", rendered)
        self.assertIn("Forged result", rendered)

    def test_surrogate_git_paths_are_lossless_internally_and_safe_to_render(self) -> None:
        raw_path = b"test_invalid_\xff.py"
        decoded = MODULE.decode_git_path(raw_path)

        self.assertEqual(decoded.encode(sys.getfilesystemencoding(), "surrogateescape"), raw_path)
        data = MODULE.collect(Path(__file__).parent, 100)
        data["root"] = decoded
        data["test_file_examples"] = [decoded]
        json_output = MODULE.to_json(data)
        markdown_output = MODULE.to_markdown(data)

        self.assertEqual(json.loads(json_output)["root"], decoded)
        self.assertNotIn("\udcff", json_output)
        self.assertNotIn("\udcff", markdown_output)
        self.assertIn("\\udcff", json_output)
        self.assertIn("\ufffd", markdown_output)
        json_output.encode("utf-8")
        markdown_output.encode("utf-8")

    @unittest.skipUnless(os.name == "posix" and shutil.which("git"), "raw byte paths require POSIX and Git")
    def test_tracked_scan_round_trips_a_non_utf8_filesystem_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_root = os.fsencode(root)
            raw_name = b"test_invalid_\xff.py"
            subprocess.run([b"git", b"-C", raw_root, b"init", b"-q"], check=True, timeout=10)
            try:
                descriptor = os.open(os.path.join(raw_root, raw_name), os.O_WRONLY | os.O_CREAT, 0o600)
            except OSError as error:
                self.skipTest(f"filesystem rejects non-UTF-8 byte paths: {error}")
            try:
                os.write(descriptor, b"print('ok')\n")
            finally:
                os.close(descriptor)
            subprocess.run([b"git", b"-C", raw_root, b"add", b"--", raw_name], check=True, timeout=10)

            data = MODULE.collect(root, 100, scan_mode="tracked")
            expected = os.fsdecode(raw_name)

            self.assertEqual(data["test_file_examples"], [expected])
            self.assertEqual(json.loads(MODULE.to_json(data))["test_file_examples"], [expected])
            MODULE.to_markdown(data).encode("utf-8")

    def test_cli_preflights_all_collection_options_before_writing_output(self) -> None:
        cases = (
            ("max-files", ("--max-files", "0"), "--max-files must be positive"),
            ("large-nan", ("--large-file-mib", "nan"), "--large-file-mib must be positive"),
            ("large-infinity", ("--large-file-mib", "inf"), "--large-file-mib must be positive"),
            ("large-zero", ("--large-file-mib", "0"), "--large-file-mib must be positive"),
            ("large-negative", ("--large-file-mib", "-1"), "--large-file-mib must be positive"),
            ("large-overflow", ("--large-file-mib", "1e308"), "--large-file-mib is too large"),
            ("include", ("--include-path", "../secret/*"), "path patterns"),
            ("exclude", ("--exclude-path", "/absolute/*"), "path patterns"),
            ("scope", ("--scope-id", "   "), "--scope-id"),
        )
        for label, arguments, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir, "repository")
                root.mkdir()
                root.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
                output = Path(temp_dir, "collector-output.json")
                original = b"preserve collector output\n"
                output.write_bytes(original)

                result = subprocess.run(
                    [sys.executable, str(MODULE_PATH), str(root), *arguments, "--output", str(output)],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(output.read_bytes(), original)

    def test_cli_preflights_collection_target_before_writing_output(self) -> None:
        cases = (
            ("missing-root", "filesystem", "not a directory"),
            ("tracked-non-git", "tracked", "requires a Git working tree"),
        )
        for label, scan_mode, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir, "repository")
                if label == "tracked-non-git":
                    root.mkdir()
                    root.joinpath("README.md").write_text("# Example\n", encoding="utf-8")
                output = Path(temp_dir, "collector-output.json")
                original = b"preserve collector output\n"
                output.write_bytes(original)

                result = subprocess.run(
                    [
                        sys.executable, str(MODULE_PATH), str(root),
                        "--scan-mode", scan_mode, "--output", str(output),
                    ],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(output.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain control characters")
    def test_cli_escapes_control_characters_in_scan_root_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "missing\n::warning title=forged::scan-root")
            output = Path(temp_dir, "collector-output.json")
            original = b"preserve collector output\n"
            output.write_bytes(original)
            result = subprocess.run(
                [sys.executable, "-I", str(MODULE_PATH), str(root), "--output", str(output)],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
            self.assertIn(r"\n::warning title=forged::scan-root", result.stderr)
            self.assertNotIn("\n::warning title=forged::scan-root", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(output.read_bytes(), original)

    def test_cli_reports_stdout_encoding_failure_without_traceback(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "ascii"
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), ".", "--format", "markdown", "--scope-id", "中文"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            env=environment,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("could not write output", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
