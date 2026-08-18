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
            root = Path(temp_dir)
            (root / "ok.py").write_text("print('ok')", encoding="utf-8")

            def walk_with_error(_root: Path, *, followlinks: bool, onerror: object):
                self.assertFalse(followlinks)
                assert callable(onerror)
                onerror(PermissionError("denied"))
                yield str(root), [], ["ok.py"]

            with mock.patch.object(MODULE.os, "walk", side_effect=walk_with_error):
                data = MODULE.collect(root, 100)

            self.assertEqual(data["file_count"], 1)
            self.assertEqual(
                data["scan_incomplete_reasons"],
                ["filesystem_directories_unavailable_during_scan"],
            )

    def test_file_becoming_unavailable_during_analysis_marks_scan_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
