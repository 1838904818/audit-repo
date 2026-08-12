#!/usr/bin/env python3
"""Collect read-only, reproducible repository health signals."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
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
    "build.gradle", "build.gradle.kts", "composer.json",
}
LOCKFILES = {
    "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum", "package-lock.json",
    "pnpm-lock.yaml", "poetry.lock", "uv.lock", "yarn.lock",
}
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
    ".env", ".netrc", ".npmrc", ".pypirc", "credentials.json", "id_dsa",
    "id_ecdsa", "id_ed25519", "id_rsa", "secrets.json", "service-account.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
ENV_EXAMPLE_NAMES = {".env.dist", ".env.example", ".env.sample", ".env.template", "example.env"}
CI_ROOT_FILES = {"azure-pipelines.yml", "bitbucket-pipelines.yml", "jenkinsfile", ".gitlab-ci.yml"}
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
WORK_MARKER_RE = re.compile(r"(?im)(?:#|//|/\*+|<!--|;|--)\s*(TODO|FIXME|HACK|XXX)\b")
CI_ACTION_RE = re.compile(r"(?m)^\s*-?\s*uses:\s*['\"]?([^'\"#\s]+)")
MAKE_TARGET_RE = re.compile(r"(?m)^([A-Za-z0-9_.-]+)\s*:(?!=)")
PYPROJECT_TOOL_RE = re.compile(r"(?m)^\[tool\.([A-Za-z0-9_-]+)(?:\.[^]]+)?\]\s*$")


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def walk_files(root: Path, max_files: int, exclude_dirs: Iterable[str] = ()) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    skipped = SKIP_DIRS | {name.lower() for name in exclude_dirs}
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.lower() not in skipped)
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            files.append(path)
            if len(files) >= max_files:
                truncated = True
                return files, truncated
    return files, truncated


def git_tracked_files(root: Path) -> set[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return {item.decode("utf-8", "replace") for item in result.stdout.split(b"\0") if item}


def git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def git_metadata(root: Path, tracked: set[str] | None) -> dict[str, Any]:
    if tracked is None:
        return {"repository": False, "branch": None, "working_tree": "unknown", "tracked_file_count": None}
    branch = git_output(root, "branch", "--show-current")
    if not branch:
        commit = git_output(root, "rev-parse", "--short", "HEAD")
        branch = f"detached@{commit}" if commit else "detached"
    status = git_output(root, "status", "--porcelain")
    return {
        "repository": True,
        "branch": branch,
        "working_tree": "unknown" if status is None else ("dirty" if status else "clean"),
        "tracked_file_count": len(tracked),
    }


def contains_marker(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    try:
        size = path.stat().st_size
    except OSError:
        return counts
    if path.suffix.lower() not in TEXT_SUFFIXES or size > 1_000_000:
        return counts
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return counts
    counts.update(match.group(1).upper() for match in WORK_MARKER_RE.finditer(text))
    return counts


def is_test(path_text: str) -> bool:
    parts = path_text.lower().split("/")
    name = parts[-1]
    return (
        any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts[:-1])
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.go")
    )


def is_sensitive_filename(name: str) -> bool:
    lowered = name.lower()
    if lowered in ENV_EXAMPLE_NAMES:
        return False
    return (
        lowered in SENSITIVE_NAMES
        or (lowered.startswith(".env.") and lowered not in ENV_EXAMPLE_NAMES)
        or Path(lowered).suffix in SENSITIVE_SUFFIXES
    )


def read_small_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 1_000_000:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def project_automation(files: list[Path], rel_files: list[str]) -> dict[str, Any]:
    package_scripts: dict[str, list[str]] = {}
    make_targets: dict[str, list[str]] = {}
    configured_tools: set[str] = set()

    for path, rel in zip(files, rel_files):
        name = path.name.lower()
        if name == "package.json":
            text = read_small_text(path)
            if text is not None:
                try:
                    scripts = json.loads(text).get("scripts", {})
                except (json.JSONDecodeError, AttributeError):
                    scripts = {}
                if isinstance(scripts, dict):
                    package_scripts[rel] = sorted(str(key) for key in scripts)[:100]
        elif name in {"makefile", "gnumakefile"}:
            text = read_small_text(path)
            if text is not None:
                make_targets[rel] = sorted({target for target in MAKE_TARGET_RE.findall(text) if not target.startswith(".")})[:100]

        if name in TOOL_CONFIG_NAMES:
            configured_tools.add(TOOL_CONFIG_NAMES[name])
        if name == "pyproject.toml":
            text = read_small_text(path)
            if text is not None:
                configured_tools.update(PYPROJECT_TOOL_RE.findall(text))

    return {
        "package_scripts": package_scripts,
        "make_targets": make_targets,
        "configured_tools": sorted(configured_tools),
    }


def ci_action_references(files: list[Path], rel_files: list[str]) -> list[str]:
    references: set[str] = set()
    for path, rel in zip(files, rel_files):
        if not rel.lower().startswith(".github/workflows/"):
            continue
        text = read_small_text(path)
        if text is not None:
            references.update(CI_ACTION_RE.findall(text))
    return sorted(references)


def collect(
    root: Path,
    max_files: int,
    exclude_dirs: Iterable[str] = (),
    large_file_bytes: int = LARGE_FILE_BYTES,
) -> dict[str, Any]:
    excluded = sorted({name.lower() for name in exclude_dirs})
    files, truncated = walk_files(root, max_files, excluded)
    rel_files = [relative(path, root) for path in files]
    tracked = git_tracked_files(root)

    languages: Counter[str] = Counter()
    markers: Counter[str] = Counter()
    large_files: list[dict[str, Any]] = []
    sensitive: list[dict[str, Any]] = []
    tests: list[str] = []

    for path, rel in zip(files, rel_files):
        suffix = path.suffix.lower()
        if suffix in LANGUAGE_BY_SUFFIX:
            languages[LANGUAGE_BY_SUFFIX[suffix]] += 1
        test_file = is_test(rel)
        if not test_file:
            markers.update(contains_marker(path))
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size >= large_file_bytes:
            large_files.append({"path": rel, "bytes": size})
        if is_sensitive_filename(path.name):
            sensitive.append({
                "path": rel,
                "tracked": None if tracked is None else rel in tracked,
            })
        if test_file:
            tests.append(rel)

    ci_files = [
        rel for rel in rel_files
        if rel.lower() in CI_ROOT_FILES
        or rel.lower().startswith(".github/workflows/")
        or rel.lower().startswith(".circleci/")
    ]
    manifests = [rel for rel in rel_files if path_name(rel) in {x.lower() for x in MANIFESTS}]
    lockfiles = [rel for rel in rel_files if path_name(rel) in {x.lower() for x in LOCKFILES}]
    license_files = [rel for rel in rel_files if path_name(rel).startswith(("license", "licence", "copying"))]
    env_examples = [rel for rel in rel_files if path_name(rel) in ENV_EXAMPLE_NAMES]
    automation = project_automation(files, rel_files)
    git = git_metadata(root, tracked)

    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "file_count": len(files),
        "scan_truncated": truncated,
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
        "ci_action_references": ci_action_references(files, rel_files),
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
        "work_markers_scope": "non-test text files up to 1 MiB; comment-style markers only",
        "large_file_threshold_bytes": large_file_bytes,
        "large_files": sorted(large_files, key=lambda item: item["bytes"], reverse=True)[:20],
        "sensitive_looking_files": sorted(sensitive, key=lambda item: item["path"]),
    }


def path_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1].lower()


def display_list(values: Iterable[str]) -> str:
    items = list(values)
    return ", ".join(f"`{item}`" for item in items) if items else "None found"


def display_mapping(values: dict[str, list[str]]) -> str:
    if not values:
        return "None found"
    return "; ".join(f"`{path}`: {', '.join(items) or '(none)'}" for path, items in values.items())


def to_markdown(data: dict[str, Any]) -> str:
    policies = data["policy_files"]
    git = data["git"]
    automation = data["automation"]
    threshold_mib = data["large_file_threshold_bytes"] / 1_048_576
    lines = [
        "# Repository signals",
        "",
        f"- Root: `{data['root']}`",
        f"- Files scanned: {data['file_count']}" + (" (limit reached)" if data["scan_truncated"] else ""),
        f"- Git repository: {'yes' if git['repository'] else 'no'}",
        f"- Git branch: {git['branch'] or 'Unknown'}",
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
        lines.append(f"- Large files (>={threshold_mib:g} MiB): " + ", ".join(
            f"`{item['path']}` ({item['bytes'] / 1_048_576:.1f} MiB)" for item in data["large_files"]
        ))
    else:
        lines.append(f"- Large files (>={threshold_mib:g} MiB): None found")
    if data["sensitive_looking_files"]:
        rendered = []
        for item in data["sensitive_looking_files"]:
            status = "tracking unknown" if item["tracked"] is None else ("tracked" if item["tracked"] else "untracked")
            rendered.append(f"`{item['path']}` ({status})")
        lines.append("- Sensitive-looking filenames (contents not read): " + ", ".join(rendered))
    else:
        lines.append("- Sensitive-looking filenames: None found")
    lines.extend(["", "> These are inventory signals, not findings. Verify context before assigning impact or priority."])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository path (default: current directory)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--max-files", type=int, default=50_000, help="Maximum files to scan")
    parser.add_argument(
        "--exclude-dir", action="append", default=[], metavar="NAME",
        help="Ignore directories with this name (repeatable)",
    )
    parser.add_argument(
        "--large-file-mib", type=float, default=5.0, metavar="MIB",
        help="Large-file threshold in MiB (default: 5)",
    )
    parser.add_argument("--output", help="Write output to this file instead of stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    if args.max_files < 1:
        print("error: --max-files must be positive", file=sys.stderr)
        return 2
    if args.large_file_mib <= 0:
        print("error: --large-file-mib must be positive", file=sys.stderr)
        return 2
    data = collect(
        root,
        args.max_files,
        exclude_dirs=args.exclude_dir,
        large_file_bytes=max(1, int(args.large_file_mib * 1_048_576)),
    )
    output = json.dumps(data, indent=2, ensure_ascii=False) + "\n" if args.format == "json" else to_markdown(data)
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as error:
            print(f"error: could not write output: {error}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
