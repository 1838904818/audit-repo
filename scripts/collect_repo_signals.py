#!/usr/bin/env python3
"""Collect read-only, reproducible repository health signals."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable


SKIP_DIRS = {
    ".git", ".hg", ".svn", ".cache", ".idea", ".next", ".tox",
    ".venv", ".vscode", "__pycache__", "build", "coverage", "dist",
    "node_modules", "target", "vendor", "venv",
}
MANIFESTS = {
    "Cargo.toml", "Gemfile", "go.mod", "package.json", "pom.xml",
    "pyproject.toml", "requirements.txt", "setup.cfg", "setup.py",
    "build.gradle", "build.gradle.kts", "composer.json", "Pipfile",
    "Package.swift",
}
MANIFEST_SUFFIXES = (".csproj", ".fsproj", ".vbproj", ".sln", ".slnx")
LOCKFILES = {
    "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum", "package-lock.json",
    "pnpm-lock.yaml", "poetry.lock", "uv.lock", "yarn.lock", "Pipfile.lock",
    "Package.resolved", "packages.lock.json", "bun.lock", "bun.lockb",
}
SWIFTPM_VERSIONED_MANIFEST_RE = re.compile(
    r"^Package@swift-[1-9][0-9]*(?:\.[0-9]+){0,2}\.swift$"
)
NUGET_PROJECT_LOCK_RE = re.compile(r"^packages\..+\.lock\.json$")
DOC_FILES = {"readme", "readme.md", "readme.rst", "readme.txt", "skill.md"}
POLICY_FILES = {
    "contributing": {"contributing", "contributing.md", "contributing.rst"},
    "security": {"security", "security.md", "security.rst"},
    "code_of_conduct": {"code_of_conduct.md", "code-of-conduct.md"},
}
LANGUAGE_BY_SUFFIX = {
    ".c": "C", ".cc": "C++", ".cpp": "C++", ".cs": "C#", ".css": "CSS",
    ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir", ".go": "Go",
    ".html": "HTML", ".java": "Java", ".js": "JavaScript", ".jsx": "JavaScript",
    ".kt": "Kotlin", ".kts": "Kotlin", ".lua": "Lua", ".php": "PHP",
    ".py": "Python", ".rb": "Ruby", ".rs": "Rust", ".scala": "Scala",
    ".sh": "Shell", ".sql": "SQL", ".swift": "Swift", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".vue": "Vue",
}
TEXT_SUFFIXES = set(LANGUAGE_BY_SUFFIX) | {
    ".cfg", ".conf", ".graphql", ".h", ".hpp", ".ini", ".json", ".md",
    ".rst", ".toml", ".txt", ".xml", ".yaml", ".yml",
}
SENSITIVE_NAMES = {
    ".env", ".envrc", ".netrc", ".npmrc", ".pypirc", "application_default_credentials.json",
    "auth.json", "client-secret.json", "client-secrets.json", "client_secret.json",
    "client_secrets.json", "credentials", "credentials.ini", "credentials.json",
    "credentials.toml", "credentials.yaml", "credentials.yml", "id_dsa",
    "id_ecdsa", "id_ed25519", "id_rsa", "secrets.json", "secrets.yaml",
    "secrets.yml", "service-account-key.json", "service-account.json",
    "service_account.json", "service_account_key.json",
}
SENSITIVE_SUFFIXES = {".jks", ".kdbx", ".key", ".keystore", ".p12", ".p8", ".pfx", ".pem", ".tfstate"}
SENSITIVE_PATHS = {
    ".aws/credentials",
    ".cargo/credentials",
    ".cargo/credentials.toml",
    ".config/gcloud/application_default_credentials.json",
    ".config/gcloud/credentials.db",
    ".config/gh/hosts.yaml",
    ".config/gh/hosts.yml",
    ".config/glab-cli/config.yml",
    ".docker/config.json",
    ".kube/config",
    ".terraform.d/credentials.tfrc.json",
}
ENV_EXAMPLE_NAMES = {".env.dist", ".env.example", ".env.sample", ".env.template", "example.env"}
ENV_EXAMPLE_SUFFIXES = (".dist", ".example", ".sample", ".template")
CI_ROOT_FILES = {"azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile", ".gitlab-ci.yml"}
DEPENDENCY_UPDATE_PATHS = {
    ".github/dependabot.yaml", ".github/dependabot.yml", ".renovaterc",
    ".renovaterc.json", "renovate.json", "renovate.json5",
}
CODEOWNER_PATHS = {".github/codeowners", "codeowners", "docs/codeowners"}
TOOL_CONFIG_NAMES = {
    ".eslintrc": "eslint", ".pre-commit-config.yaml": "pre-commit",
    ".pre-commit-config.yml": "pre-commit", ".ruff.toml": "ruff",
    "eslint.config.js": "eslint", "eslint.config.mjs": "eslint",
    "jest.config.js": "jest", "jest.config.ts": "jest", "mypy.ini": "mypy",
    "noxfile.py": "nox", "pytest.ini": "pytest", "ruff.toml": "ruff",
    "tox.ini": "tox", "tsconfig.json": "typescript", "vitest.config.js": "vitest",
    "vitest.config.ts": "vitest",
}
LARGE_FILE_BYTES = 5 * 1024 * 1024
SCHEMA_VERSION = 1
TOOL_VERSION = "1.10.7"
SCAN_SEMANTICS_VERSION = 3
MAX_ERROR_VALUE_CHARS = 500
DISABLED_GIT_HOOKS_PATH = Path(__file__).resolve().as_posix()
SCAN_MODES = {"filesystem", "git-visible", "tracked"}
WORK_MARKER_RE = re.compile(r"(?im)(?:#|//|/\*+|<!--|;|--)\s*(TODO|FIXME|HACK|XXX)\b")
CI_ACTION_RE = re.compile(
    r"^\s*-?\s*(?P<key_quote>['\"]?)uses(?P=key_quote)\s*:"
    r"\s*(?P<quote>['\"]?)(?P<value>[^'\"#\s]+)(?P=quote)"
    r"\s*(?:#.*)?$"
)
YAML_BLOCK_SCALAR_RE = re.compile(
    r"^(?P<indent> *)(?P<sequence>-\s+)?(?P<key>[^#:\n]+?)\s*:\s*"
    r"(?:[!&][^\s#]+\s+)*[|>]"
    r"(?:[+-]?[1-9]?|[1-9][+-]?)?\s*(?:#.*)?$"
)
ACTION_REFERENCE_VALUE_RE = re.compile(r"^[^'\"#\s]+$")
GITHUB_WORKFLOW_RE = re.compile(r"^\.github/workflows/[^/]+\.(?:yml|yaml)$")
MAKE_TARGET_RE = re.compile(r"(?m)^([A-Za-z0-9_.-]+)\s*:(?!=)")
PYPROJECT_TOOL_RE = re.compile(r"(?m)^\[tool\.([A-Za-z0-9_-]+)(?:\.[^]]+)?\]\s*$")


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class CollectionError(ValueError):
    """Raised when a requested collection scope cannot be evaluated safely."""


def safe_error_value(value: object) -> str:
    """Render untrusted error context on one bounded ASCII-only line."""
    rendered = ascii(str(value))
    if len(rendered) > MAX_ERROR_VALUE_CHARS:
        return rendered[:MAX_ERROR_VALUE_CHARS - 3] + "..."
    return rendered


def normalize_path_patterns(patterns: Iterable[str]) -> list[str]:
    normalized: set[str] = set()
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise CollectionError("path patterns must be strings")
        while pattern.startswith("./"):
            pattern = pattern[2:]
        if (
            not pattern
            or pattern.startswith("/")
            or re.match(r"^[A-Za-z]:/", pattern)
            or "\\" in pattern
            or "\0" in pattern
        ):
            raise CollectionError("path patterns must be non-empty relative POSIX globs")
        if not pattern or any(part == ".." for part in pattern.split("/")):
            raise CollectionError("path patterns cannot be absolute or contain '..'")
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in pattern):
            raise CollectionError("path patterns cannot contain control characters")
        normalized.add(pattern)
    return sorted(normalized)


def normalize_scope_id(scope_id: str | None) -> str | None:
    if scope_id is None:
        return None
    if not isinstance(scope_id, str) or not scope_id.strip() or len(scope_id) > 200 or any(
        ord(char) < 32 or 127 <= ord(char) <= 159 for char in scope_id
    ):
        raise CollectionError("--scope-id must be 1-200 characters without control characters")
    return scope_id


def normalize_excluded_directory_names(names: Iterable[str]) -> list[str]:
    """Return validated, case-insensitive directory-name exclusions."""
    normalized: set[str] = set()
    for name in names:
        if not isinstance(name, str):
            raise CollectionError("--exclude-dir values must be strings")
        if (
            not name
            or not name.strip()
            or name in (".", "..")
            or "/" in name
            or "\\" in name
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)
        ):
            raise CollectionError(
                "--exclude-dir values must be non-empty single directory names without "
                "path separators, dot segments, or control characters"
            )
        normalized.add(name.lower())
    return sorted(normalized)


def validate_collection_options(
    max_files: int,
    large_file_mib: float,
    include_paths: Iterable[str] = (),
    exclude_paths: Iterable[str] = (),
    scope_id: str | None = None,
) -> tuple[int, list[str], list[str], str | None]:
    """Validate and normalize collection options before any output side effect."""
    if max_files < 1:
        raise CollectionError("--max-files must be positive")
    if not math.isfinite(large_file_mib) or large_file_mib <= 0:
        raise CollectionError("--large-file-mib must be positive")
    threshold_bytes = large_file_mib * 1_048_576
    if not math.isfinite(threshold_bytes):
        raise CollectionError("--large-file-mib is too large")
    included_patterns = normalize_path_patterns(include_paths)
    excluded_patterns = normalize_path_patterns(exclude_paths)
    normalized_scope_id = normalize_scope_id(scope_id)
    return (
        max(1, int(threshold_bytes)),
        included_patterns,
        excluded_patterns,
        normalized_scope_id,
    )


def path_selected(relative_path: str, include_paths: Iterable[str], exclude_paths: Iterable[str]) -> bool:
    includes = list(include_paths)
    return (
        (not includes or any(fnmatchcase(relative_path, pattern) for pattern in includes))
        and not any(fnmatchcase(relative_path, pattern) for pattern in exclude_paths)
    )


def has_excluded_directory(relative_path: str, excluded: set[str]) -> bool:
    return any(part.lower() in excluded for part in relative_path.split("/")[:-1])


def metadata_is_link_or_reparse_point(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def path_is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return metadata_is_link_or_reparse_point(metadata)


def walk_files(
    root: Path,
    max_files: int,
    exclude_dirs: Iterable[str] = (),
    include_paths: Iterable[str] = (),
    exclude_paths: Iterable[str] = (),
) -> tuple[list[Path], bool, list[str]]:
    files: list[Path] = []
    truncated = False
    directory_error_count = 0
    missing_count = 0
    unavailable_count = 0
    skipped = SKIP_DIRS | {name.lower() for name in exclude_dirs}

    def record_directory_error(_error: OSError) -> None:
        nonlocal directory_error_count
        directory_error_count += 1

    for current, dirs, names in os.walk(root, followlinks=False, onerror=record_directory_error):
        safe_directories = []
        for directory_name in sorted(dirs):
            if directory_name.lower() in skipped:
                continue
            try:
                if path_is_link_or_reparse_point(Path(current) / directory_name):
                    continue
            except (OSError, UnicodeError):
                directory_error_count += 1
                continue
            safe_directories.append(directory_name)
        dirs[:] = safe_directories
        for name in sorted(names):
            path = Path(current) / name
            try:
                metadata = path.lstat()
            except (FileNotFoundError, NotADirectoryError):
                missing_count += 1
                continue
            except (OSError, UnicodeError):
                unavailable_count += 1
                continue
            if metadata_is_link_or_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode):
                continue
            rel = relative(path, root)
            if not path_selected(rel, include_paths, exclude_paths):
                continue
            files.append(path)
            if len(files) > max_files:
                truncated = True
                files = files[:max_files]
                break
        if truncated:
            break
    incomplete_reasons = []
    if directory_error_count:
        incomplete_reasons.append("filesystem_directories_unavailable_during_scan")
    if missing_count:
        incomplete_reasons.append("filesystem_paths_missing_during_scan")
    if unavailable_count:
        incomplete_reasons.append("filesystem_paths_unavailable_during_scan")
    return files, truncated, incomplete_reasons


def decode_git_path(value: bytes) -> str:
    """Decode a NUL-delimited Git path without losing undecodable bytes."""
    try:
        return os.fsdecode(value)
    except UnicodeDecodeError:
        # Windows normally receives valid UTF-8 paths, but retain malformed Git
        # output losslessly so it can be reported instead of silently omitted.
        return value.decode(sys.getfilesystemencoding(), "surrogateescape")


def normalize_git_path(value: bytes) -> str | None:
    normalized = decode_git_path(value)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("/") or any(part == ".." for part in normalized.split("/")):
        return None
    return normalized


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        directory_stat = directory.stat()
    except (OSError, ValueError):
        directory_stat = None
    if directory_stat is not None:
        for candidate in (path, *path.parents):
            try:
                if os.path.samestat(candidate.stat(), directory_stat):
                    return True
            except (OSError, ValueError):
                continue
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def absolute_without_symlink_resolution(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.drive and not expanded.is_absolute():
        raise ValueError("drive-relative paths are not supported")
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


def git_worktree_boundary(root: Path) -> Path:
    try:
        lexical_root = absolute_without_symlink_resolution(root)
    except (OSError, RuntimeError, ValueError):
        lexical_root = root
    boundary = lexical_root
    for candidate in (lexical_root, *lexical_root.parents):
        try:
            candidate.joinpath(".git").lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            boundary = candidate
            continue
        boundary = candidate
    try:
        return boundary.resolve(strict=False)
    except (OSError, RuntimeError):
        return boundary


def resolve_git_executable(
    root: Path, git_untrusted_roots: Iterable[Path] = (),
) -> Path | None:
    untrusted_boundaries: set[Path] = set()
    for source in (root, *tuple(git_untrusted_roots)):
        untrusted_boundaries.add(git_worktree_boundary(source))
        try:
            untrusted_boundaries.add(git_worktree_boundary(source.resolve()))
        except (OSError, RuntimeError):
            pass
    path_value = os.environ.get("PATH", "")
    executable_names = ("git.exe", "git.com") if os.name == "nt" else ("git",)
    for raw_directory in path_value.split(os.pathsep):
        directory_text = raw_directory.strip().strip('"')
        if not directory_text:
            continue
        directory = Path(directory_text)
        if not directory.is_absolute():
            continue
        for executable_name in executable_names:
            candidate = directory / executable_name
            try:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if any(path_is_within(resolved, boundary) for boundary in untrusted_boundaries):
                continue
            if os.name != "nt" and not os.access(resolved, os.X_OK):
                continue
            return resolved
    return None


def git_command(git_executable: Path, root: Path, *arguments: str) -> list[str]:
    return [
        str(git_executable),
        "-c", f"core.hooksPath={DISABLED_GIT_HOOKS_PATH}",
        "-c", "core.fsmonitor=false",
        "-c", "core.pager=cat",
        "-C", str(root),
        *arguments,
    ]


def git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_PAGER"] = "cat"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def validate_collection_target(
    root_candidate: Path,
    scan_mode: str,
    git_untrusted_roots: Iterable[Path] = (),
) -> Path:
    """Resolve and validate the collection target without changing repository state."""
    try:
        root = root_candidate.resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise CollectionError(
            f"could not resolve the scan root: {safe_error_value(error)}"
        ) from error
    if not root.is_dir():
        raise CollectionError(f"not a directory: {safe_error_value(root)}")
    if scan_mode not in SCAN_MODES:
        raise CollectionError(f"unsupported scan mode: {safe_error_value(scan_mode)}")
    if scan_mode == "filesystem":
        return root

    untrusted_roots = (root_candidate, *tuple(git_untrusted_roots))
    git_executable = resolve_git_executable(root, untrusted_roots)
    if git_executable is None:
        raise CollectionError("Git is required for the requested scan mode")
    try:
        result = subprocess.run(
            git_command(git_executable, root, "rev-parse", "--is-inside-work-tree"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            env=git_environment(),
        )
    except FileNotFoundError as error:
        raise CollectionError("Git is required for the requested scan mode") from error
    except OSError as error:
        raise CollectionError(
            f"could not run Git working-tree validation: {safe_error_value(error)}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise CollectionError("Git working-tree validation timed out") from error
    if result.returncode != 0 or result.stdout.strip() != b"true":
        raise CollectionError(
            f"--scan-mode {safe_error_value(scan_mode)} requires a Git working tree"
        )
    return root


def git_file_names(
    root: Path, mode: str, *options: str, git_untrusted_roots: Iterable[Path] = (),
) -> set[str]:
    git_executable = resolve_git_executable(root, git_untrusted_roots)
    if git_executable is None:
        raise CollectionError("Git is required for the requested scan mode")
    arguments = git_command(git_executable, root, "ls-files", "-z", *options, "--", ".")
    try:
        result = subprocess.run(
            arguments,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            env=git_environment(),
        )
    except FileNotFoundError as error:
        raise CollectionError("Git is required for the requested scan mode") from error
    except subprocess.TimeoutExpired as error:
        raise CollectionError("Git file enumeration timed out") from error
    if result.returncode != 0:
        raise CollectionError(
            f"--scan-mode {safe_error_value(mode)} requires a Git working tree"
        )

    names: set[str] = set()
    for item in result.stdout.split(b"\0"):
        if item:
            normalized = normalize_git_path(item)
            if normalized is not None:
                names.add(normalized)
    return names


def git_scan_files(
    root: Path,
    mode: str,
    max_files: int,
    exclude_dirs: Iterable[str] = (),
    include_paths: Iterable[str] = (),
    exclude_paths: Iterable[str] = (),
    git_untrusted_roots: Iterable[Path] = (),
) -> tuple[list[Path], bool, set[str], list[str]]:
    untrusted_roots = tuple(git_untrusted_roots)
    tracked = git_file_names(root, mode, "--cached", git_untrusted_roots=untrusted_roots)
    names = set(tracked)
    if mode == "git-visible":
        names.update(git_file_names(
            root, mode, "--others", "--exclude-standard", git_untrusted_roots=untrusted_roots,
        ))
    skipped = SKIP_DIRS | {name.lower() for name in exclude_dirs}
    selected: list[Path] = []
    redirect_cache: dict[Path, bool] = {}
    missing_count = 0
    unavailable_count = 0
    truncated = False
    for normalized in sorted(names):
        if has_excluded_directory(normalized, skipped):
            continue
        if not path_selected(normalized, include_paths, exclude_paths):
            continue
        parts = normalized.split("/")
        path = root / Path(*parts)
        try:
            current = root
            redirected = False
            for part in parts[:-1]:
                current /= part
                if current not in redirect_cache:
                    redirect_cache[current] = path_is_link_or_reparse_point(current)
                if redirect_cache[current]:
                    redirected = True
                    break
            if redirected:
                continue
            metadata = path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            missing_count += 1
            continue
        except (OSError, UnicodeError):
            unavailable_count += 1
            continue
        if metadata_is_link_or_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode):
            continue
        if len(selected) < max_files:
            selected.append(path)
        else:
            truncated = True
    incomplete_reasons = []
    if missing_count:
        incomplete_reasons.append("git_enumerated_paths_missing_from_worktree")
    if unavailable_count:
        incomplete_reasons.append("git_enumerated_paths_unavailable_in_worktree")
    return selected, truncated, tracked, incomplete_reasons


def git_tracked_files(root: Path, git_untrusted_roots: Iterable[Path] = ()) -> set[str] | None:
    git_executable = resolve_git_executable(root, git_untrusted_roots)
    if git_executable is None:
        return None
    try:
        result = subprocess.run(
            git_command(git_executable, root, "ls-files", "-z", "--cached", "--", "."),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            env=git_environment(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    tracked: set[str] = set()
    for item in result.stdout.split(b"\0"):
        if item:
            normalized = normalize_git_path(item)
            if normalized is not None:
                tracked.add(normalized)
    return tracked


def git_output(
    root: Path, *args: str, git_untrusted_roots: Iterable[Path] = (),
) -> str | None:
    git_executable = resolve_git_executable(root, git_untrusted_roots)
    if git_executable is None:
        return None
    try:
        result = subprocess.run(
            git_command(git_executable, root, *args),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            env=git_environment(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return decode_git_path(result.stdout).strip()


def git_metadata(
    root: Path, tracked: set[str] | None, git_untrusted_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    if tracked is None:
        return {"repository": False, "branch": None, "working_tree": "unknown", "tracked_file_count": None}
    untrusted_roots = tuple(git_untrusted_roots)
    branch = git_output(root, "branch", "--show-current", git_untrusted_roots=untrusted_roots)
    if not branch:
        commit = git_output(
            root, "rev-parse", "--short", "HEAD", git_untrusted_roots=untrusted_roots,
        )
        branch = f"detached@{commit}" if commit else "detached"
    return {
        "repository": True,
        "branch": branch,
        "working_tree": "unknown",
        "tracked_file_count": len(tracked),
    }


def contains_marker(path: Path, unavailable_paths: set[str] | None = None) -> Counter[str]:
    counts: Counter[str] = Counter()
    try:
        size = path.stat().st_size
    except (OSError, UnicodeError):
        if unavailable_paths is not None:
            unavailable_paths.add(str(path))
        return counts
    if path.suffix.lower() not in TEXT_SUFFIXES or size > 1_000_000:
        return counts
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        if unavailable_paths is not None:
            unavailable_paths.add(str(path))
        return counts
    counts.update(match.group(1).upper() for match in WORK_MARKER_RE.finditer(text))
    return counts


def is_test(path_text: str) -> bool:
    parts = path_text.lower().split("/")
    name = parts[-1]
    original_name = path_text.rsplit("/", 1)[-1]
    return (
        any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts[:-1])
        or name.startswith("test_")
        or original_name == "tests.py"
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.go")
        or original_name.endswith("Tests.cs")
    )


def is_github_workflow(path_text: str) -> bool:
    return GITHUB_WORKFLOW_RE.fullmatch(path_text) is not None


def is_ci_file(path_text: str) -> bool:
    return (
        path_text in CI_ROOT_FILES
        or path_text == ".circleci/config.yml"
        or is_github_workflow(path_text)
    )


def is_manifest(path_text: str) -> bool:
    name = exact_path_name(path_text)
    if name in MANIFESTS or SWIFTPM_VERSIONED_MANIFEST_RE.fullmatch(name):
        return True
    return any(len(name) > len(suffix) and name.endswith(suffix) for suffix in MANIFEST_SUFFIXES)


def is_lockfile(path_text: str) -> bool:
    name = exact_path_name(path_text)
    return name in LOCKFILES or NUGET_PROJECT_LOCK_RE.fullmatch(name) is not None


def is_environment_example_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in ENV_EXAMPLE_NAMES or (
        lowered.startswith(".env.") and lowered.endswith(ENV_EXAMPLE_SUFFIXES)
    )


def is_sensitive_filename(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/").lower().strip("/")
    name = normalized.rsplit("/", 1)[-1]
    if is_environment_example_name(name):
        return False
    return (
        name in SENSITIVE_NAMES
        or name.startswith(".env.")
        or Path(name).suffix in SENSITIVE_SUFFIXES
        or name.endswith(".tfstate.backup")
        or any(normalized == path or normalized.endswith(f"/{path}") for path in SENSITIVE_PATHS)
    )


def read_small_text(path: Path, unavailable_paths: set[str] | None = None) -> str | None:
    try:
        if path.stat().st_size > 1_000_000:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        if unavailable_paths is not None:
            unavailable_paths.add(str(path))
        return None


def project_automation(
    files: list[Path], rel_files: list[str], unavailable_paths: set[str] | None = None,
) -> dict[str, Any]:
    package_scripts: dict[str, list[str]] = {}
    make_targets: dict[str, list[str]] = {}
    configured_tools: set[str] = set()

    for path, rel in zip(files, rel_files):
        if is_sensitive_filename(rel):
            continue
        name = path.name.lower()
        if name == "package.json":
            text = read_small_text(path, unavailable_paths)
            if text is not None:
                try:
                    scripts = json.loads(text).get("scripts", {})
                except (ValueError, AttributeError, RecursionError):
                    scripts = {}
                if isinstance(scripts, dict):
                    package_scripts[rel] = sorted(str(key) for key in scripts)[:100]
        elif name in {"makefile", "gnumakefile"}:
            text = read_small_text(path, unavailable_paths)
            if text is not None:
                make_targets[rel] = sorted({target for target in MAKE_TARGET_RE.findall(text) if not target.startswith(".")})[:100]

        if name in TOOL_CONFIG_NAMES:
            configured_tools.add(TOOL_CONFIG_NAMES[name])
        if name == "pyproject.toml":
            text = read_small_text(path, unavailable_paths)
            if text is not None:
                configured_tools.update(PYPROJECT_TOOL_RE.findall(text))

    return {
        "package_scripts": package_scripts,
        "make_targets": make_targets,
        "configured_tools": sorted(configured_tools),
    }


def ci_action_references(
    files: list[Path], rel_files: list[str], unavailable_paths: set[str] | None = None,
) -> list[str]:
    references: set[str] = set()
    for path, rel in zip(files, rel_files):
        if not is_github_workflow(rel) or is_sensitive_filename(rel):
            continue
        text = read_small_text(path, unavailable_paths)
        if text is not None:
            lines = text.splitlines()
            index = 0
            while index < len(lines):
                line = lines[index]
                block_match = YAML_BLOCK_SCALAR_RE.fullmatch(line)
                if block_match:
                    block_parent_indent = len(block_match.group("indent")) + len(
                        block_match.group("sequence") or ""
                    )
                    block_values: list[str] = []
                    index += 1
                    while index < len(lines):
                        block_line = lines[index]
                        if block_line.strip() and len(block_line) - len(block_line.lstrip(" ")) <= block_parent_indent:
                            break
                        if block_line.strip():
                            block_values.append(block_line.strip())
                        index += 1
                    key = block_match.group("key").strip()
                    if len(key) >= 2 and key[0] == key[-1] and key[0] in "'\"":
                        key = key[1:-1]
                    if (
                        key == "uses"
                        and len(block_values) == 1
                        and ACTION_REFERENCE_VALUE_RE.fullmatch(block_values[0])
                    ):
                        references.add(block_values[0])
                    continue
                action_match = CI_ACTION_RE.fullmatch(line)
                if action_match:
                    references.add(action_match.group("value"))
                index += 1
    return sorted(references)


def collect(
    root: Path,
    max_files: int,
    exclude_dirs: Iterable[str] = (),
    large_file_bytes: int = LARGE_FILE_BYTES,
    scan_mode: str = "filesystem",
    include_paths: Iterable[str] = (),
    exclude_paths: Iterable[str] = (),
    scope_id: str | None = None,
    git_untrusted_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    root_candidate = root
    root = validate_collection_target(root_candidate, scan_mode, git_untrusted_roots)
    untrusted_roots = (root_candidate, *tuple(git_untrusted_roots))
    if max_files < 1:
        raise CollectionError("--max-files must be positive")
    excluded = normalize_excluded_directory_names(exclude_dirs)
    included_patterns = normalize_path_patterns(include_paths)
    excluded_patterns = normalize_path_patterns(exclude_paths)
    normalized_scope_id = normalize_scope_id(scope_id)
    scan_incomplete_reasons: list[str] = []
    if scan_mode == "filesystem":
        files, truncated, scan_incomplete_reasons = walk_files(
            root,
            max_files,
            excluded,
            include_paths=included_patterns,
            exclude_paths=excluded_patterns,
        )
        tracked = git_tracked_files(root, git_untrusted_roots=untrusted_roots)
    else:
        files, truncated, tracked, scan_incomplete_reasons = git_scan_files(
            root,
            scan_mode,
            max_files,
            excluded,
            include_paths=included_patterns,
            exclude_paths=excluded_patterns,
            git_untrusted_roots=untrusted_roots,
        )
    rel_files = [relative(path, root) for path in files]

    languages: Counter[str] = Counter()
    markers: Counter[str] = Counter()
    large_files: list[dict[str, Any]] = []
    sensitive: list[dict[str, Any]] = []
    tests: list[str] = []
    analysis_unavailable_paths: set[str] = set()

    for path, rel in zip(files, rel_files):
        suffix = path.suffix.lower()
        if suffix in LANGUAGE_BY_SUFFIX:
            languages[LANGUAGE_BY_SUFFIX[suffix]] += 1
        test_file = is_test(rel)
        sensitive_file = is_sensitive_filename(rel)
        if not test_file and not sensitive_file:
            markers.update(contains_marker(path, analysis_unavailable_paths))
        try:
            size = path.stat().st_size
        except (OSError, UnicodeError):
            analysis_unavailable_paths.add(str(path))
            size = 0
        if size >= large_file_bytes:
            large_files.append({"path": rel, "bytes": size})
        if sensitive_file:
            sensitive.append({
                "path": rel,
                "tracked": None if tracked is None else rel in tracked,
            })
        if test_file:
            tests.append(rel)

    ci_files = [rel for rel in rel_files if is_ci_file(rel)]
    manifests = [rel for rel in rel_files if is_manifest(rel)]
    lockfiles = [rel for rel in rel_files if is_lockfile(rel)]
    license_files = [rel for rel in rel_files if path_name(rel).startswith(("license", "licence", "copying"))]
    env_examples = [rel for rel in rel_files if is_environment_example_name(path_name(rel))]
    automation = project_automation(files, rel_files, analysis_unavailable_paths)
    action_references = ci_action_references(files, rel_files, analysis_unavailable_paths)
    if analysis_unavailable_paths and "paths_unavailable_during_analysis" not in scan_incomplete_reasons:
        scan_incomplete_reasons.append("paths_unavailable_during_analysis")
    git = git_metadata(root, tracked, git_untrusted_roots=untrusted_roots)

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "scan_semantics_version": SCAN_SEMANTICS_VERSION,
        "root": str(root),
        "file_count": len(files),
        "scan_mode": scan_mode,
        "include_path_patterns": included_patterns,
        "exclude_path_patterns": excluded_patterns,
        "scope_id": normalized_scope_id,
        "scan_file_limit": max_files,
        "scan_truncated": truncated,
        "scan_incomplete_reasons": scan_incomplete_reasons,
        "excluded_directory_names": excluded,
        "git_repository": git["repository"],
        "git": git,
        "languages_by_file_count": dict(languages.most_common()),
        "manifests": sorted(manifests),
        "lockfiles": sorted(lockfiles),
        "documentation": sorted(rel for rel in rel_files if path_name(rel) in DOC_FILES),
        "license_files": sorted(license_files),
        "policy_files": {
            key: sorted(rel for rel in rel_files if path_name(rel) in names)
            for key, names in POLICY_FILES.items()
        },
        "ci_files": sorted(ci_files),
        "ci_action_references": action_references,
        "test_file_count": len(tests),
        "test_file_examples": sorted(tests)[:10],
        "ignore_files": sorted(rel for rel in rel_files if path_name(rel) in {".gitignore", ".dockerignore"}),
        "environment_examples": sorted(env_examples),
        "dependency_update_config": sorted(rel for rel in rel_files if rel.lower() in DEPENDENCY_UPDATE_PATHS),
        "codeowners": sorted(rel for rel in rel_files if rel.lower() in CODEOWNER_PATHS),
        "container_files": sorted(
            rel for rel in rel_files
            if path_name(rel).startswith("dockerfile")
            or path_name(rel) in {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
        ),
        "automation": automation,
        "work_markers": dict(markers),
        "work_markers_scope": "non-test, non-sensitive text files up to 1 MiB; comment-style markers only",
        "large_file_threshold_bytes": large_file_bytes,
        "large_files_complete": True,
        "large_files": sorted(large_files, key=lambda item: (-item["bytes"], item["path"])),
        "sensitive_looking_files": sorted(sensitive, key=lambda item: item["path"]),
    }


def path_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1].lower()


def exact_path_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]


def markdown_code(value: object) -> str:
    """Render untrusted data as a single safe Markdown code span."""
    rendered: list[str] = []
    for char in str(value):
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            rendered.append("\ufffd")
        elif char.isspace():
            rendered.append(" ")
        elif codepoint < 32 or 127 <= codepoint <= 159:
            rendered.append("?")
        else:
            rendered.append(char)
    text = "".join(rendered)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if longest or text.startswith(" ") or text.endswith(" ") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def display_list(values: Iterable[str]) -> str:
    items = list(values)
    return ", ".join(markdown_code(item) for item in items) if items else "None found"


def display_mapping(values: dict[str, list[str]]) -> str:
    if not values:
        return "None found"
    return "; ".join(
        f"{markdown_code(path)}: {', '.join(markdown_code(item) for item in items) or '(none)'}"
        for path, items in values.items()
    )


def to_markdown(data: dict[str, Any]) -> str:
    policies = data["policy_files"]
    git = data["git"]
    automation = data["automation"]
    threshold_mib = data["large_file_threshold_bytes"] / 1_048_576
    lines = [
        "# Repository signals",
        "",
        f"- Root: {markdown_code(data['root'])}",
        f"- Collector version: {markdown_code(data.get('tool_version', 'Unknown'))}",
        f"- Scan semantics version: {data.get('scan_semantics_version', 'Unknown')}",
        f"- Files scanned: {data['file_count']}" + (" (limit reached)" if data["scan_truncated"] else ""),
        f"- Scan mode: {markdown_code(data.get('scan_mode', 'filesystem'))}",
        f"- Scope ID: {markdown_code(data['scope_id']) if data.get('scope_id') is not None else 'None'}",
        f"- Included path globs: {display_list(data.get('include_path_patterns', []))}",
        f"- Excluded path globs: {display_list(data.get('exclude_path_patterns', []))}",
        f"- Scan file limit: {data.get('scan_file_limit', 'Unknown')}",
        f"- Scan incomplete reasons: {display_list(data.get('scan_incomplete_reasons', []))}",
        f"- Git repository: {'yes' if git['repository'] else 'no'}",
        f"- Git branch: {markdown_code(git['branch']) if git['branch'] else 'Unknown'}",
        f"- Working tree: {git['working_tree']}",
        f"- Tracked files: {git['tracked_file_count'] if git['tracked_file_count'] is not None else 'Unknown'}",
        f"- Extra excluded directory names: {display_list(data['excluded_directory_names'])}",
        f"- Languages (file count): {', '.join(f'{k} {v}' for k, v in data['languages_by_file_count'].items()) or 'None detected'}",
        "",
        "## Project structure",
        "",
        f"- Manifests: {display_list(data['manifests'])}",
        f"- Lockfiles: {display_list(data['lockfiles'])}",
        f"- Primary documentation: {display_list(data['documentation'])}",
        f"- Licenses: {display_list(data['license_files'])}",
        f"- CI configuration: {display_list(data['ci_files'])}",
        f"- CI action references: {display_list(data['ci_action_references'])}",
        f"- Test files: {data['test_file_count']}",
        f"- Test examples: {display_list(data['test_file_examples'])}",
        f"- Ignore files: {display_list(data['ignore_files'])}",
        f"- Environment examples: {display_list(data['environment_examples'])}",
        f"- Dependency update configuration: {display_list(data['dependency_update_config'])}",
        f"- Container files: {display_list(data['container_files'])}",
        "",
        "## Project automation",
        "",
        f"- Configured tools: {display_list(automation['configured_tools'])}",
        f"- Package scripts: {display_mapping(automation['package_scripts'])}",
        f"- Make targets: {display_mapping(automation['make_targets'])}",
        "",
        "## Repository policies",
        "",
        f"- Contributing: {display_list(policies['contributing'])}",
        f"- Security: {display_list(policies['security'])}",
        f"- Code of conduct: {display_list(policies['code_of_conduct'])}",
        f"- CODEOWNERS: {display_list(data['codeowners'])}",
        "",
        "## Review signals",
        "",
        "- Work markers: " + (", ".join(f"{k} {v}" for k, v in data["work_markers"].items()) or "None found")
        + f" ({data['work_markers_scope']})",
    ]
    if data["large_files"]:
        displayed_large_files = data["large_files"][:20]
        lines.append(f"- Large files (>={threshold_mib:g} MiB): " + ", ".join(
            f"{markdown_code(item['path'])} ({item['bytes'] / 1_048_576:.1f} MiB)" for item in displayed_large_files
        ))
        remaining = len(data["large_files"]) - len(displayed_large_files)
        if remaining:
            lines[-1] += f"; {remaining} more recorded in JSON output"
    else:
        lines.append(f"- Large files (>={threshold_mib:g} MiB): None found")
    if data["sensitive_looking_files"]:
        rendered = []
        for item in data["sensitive_looking_files"]:
            status = "tracking unknown" if item["tracked"] is None else ("tracked" if item["tracked"] else "untracked")
            rendered.append(f"{markdown_code(item['path'])} ({status})")
        lines.append("- Sensitive-looking filenames (contents not read): " + ", ".join(rendered))
    else:
        lines.append("- Sensitive-looking filenames: None found")
    if data.get("scan_mode") == "tracked":
        lines.append(
            "- Scan coverage note: all untracked files are outside this tracked-only snapshot; "
            "tracked files remain included even if an ignore rule matches them."
        )
    elif data.get("scan_mode") == "git-visible":
        lines.append(
            "- Scan coverage note: tracked and non-ignored untracked files are included; "
            "ignored untracked files are outside scope."
        )
    lines.extend(["", "> These are inventory signals, not findings. Verify context before assigning impact or priority."])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository path (default: current directory)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--max-files", type=int, default=50_000, help="Maximum files to scan")
    parser.add_argument(
        "--scan-mode", choices=tuple(sorted(SCAN_MODES)), default="filesystem",
        help="Select filesystem, Git-visible, or tracked files (default: filesystem)",
    )
    parser.add_argument(
        "--exclude-dir", action="append", default=[], metavar="NAME",
        help="Ignore directories with this name (repeatable)",
    )
    parser.add_argument(
        "--include-path", action="append", default=[], metavar="GLOB",
        help="Include matching root-relative POSIX paths (repeatable)",
    )
    parser.add_argument(
        "--exclude-path", action="append", default=[], metavar="GLOB",
        help="Exclude matching root-relative POSIX paths (repeatable)",
    )
    parser.add_argument(
        "--scope-id",
        help="Project-qualified logical scope ID used to compare equivalent roots (unset by default)",
    )
    parser.add_argument(
        "--large-file-mib", type=float, default=5.0, metavar="MIB",
        help="Large-file threshold in MiB (default: 5)",
    )
    parser.add_argument("--output", help="Write output to this file instead of stdout")
    return parser.parse_args()


def to_json(data: dict[str, Any]) -> str:
    """Render UTF-8 JSON while escaping lone surrogates from raw filesystem paths."""
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"


def main() -> int:
    args = parse_args()
    try:
        large_file_bytes, include_paths, exclude_paths, scope_id = validate_collection_options(
            args.max_files,
            args.large_file_mib,
            include_paths=args.include_path,
            exclude_paths=args.exclude_path,
            scope_id=args.scope_id,
        )
        exclude_dirs = normalize_excluded_directory_names(args.exclude_dir)
    except CollectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        root_candidate = absolute_without_symlink_resolution(Path(args.path))
    except (OSError, RuntimeError, ValueError) as error:
        print(
            f"error: could not resolve the scan root: {safe_error_value(error)}",
            file=sys.stderr,
        )
        return 2
    try:
        data = collect(
            root_candidate,
            args.max_files,
            exclude_dirs=exclude_dirs,
            large_file_bytes=large_file_bytes,
            scan_mode=args.scan_mode,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            scope_id=scope_id,
        )
    except CollectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    output = to_json(data) if args.format == "json" else to_markdown(data)
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except (OSError, UnicodeError) as error:
            print(f"error: could not write output: {safe_error_value(error)}", file=sys.stderr)
            return 2
    else:
        try:
            sys.stdout.write(output)
        except (OSError, UnicodeError) as error:
            print(f"error: could not write output: {safe_error_value(error)}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
