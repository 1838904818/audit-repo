#!/usr/bin/env python3
"""Collect read-only, reproducible repository health signals."""

from __future__ import annotations

import argparse
import json
import os
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
    ".env", "credentials.json", "id_dsa", "id_ecdsa", "id_ed25519",
    "id_rsa", "secrets.json", "service-account.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
CI_ROOT_FILES = {"azure-pipelines.yml", "bitbucket-pipelines.yml", "jenkinsfile", ".gitlab-ci.yml"}
LARGE_FILE_BYTES = 5 * 1024 * 1024


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def walk_files(root: Path, max_files: int) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_DIRS)
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


def contains_marker(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    try:
        size = path.stat().st_size
    except OSError:
        return counts
    if path.suffix.lower() not in TEXT_SUFFIXES or size > 1_000_000:
        return counts
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").upper()
    except OSError:
        return counts
    for marker in ("TODO", "FIXME", "HACK", "XXX"):
        counts[marker] = text.count(marker)
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


def collect(root: Path, max_files: int) -> dict[str, Any]:
    files, truncated = walk_files(root, max_files)
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
        markers.update(contains_marker(path))
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size >= LARGE_FILE_BYTES:
            large_files.append({"path": rel, "bytes": size})
        name_lower = path.name.lower()
        if name_lower in SENSITIVE_NAMES or suffix in SENSITIVE_SUFFIXES:
            sensitive.append({
                "path": rel,
                "tracked": None if tracked is None else rel in tracked,
            })
        if is_test(rel):
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
    env_examples = [rel for rel in rel_files if path_name(rel) in {".env.example", ".env.sample", "example.env"}]

    return {
        "root": str(root),
        "file_count": len(files),
        "scan_truncated": truncated,
        "git_repository": (root / ".git").exists() or tracked is not None,
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
        "test_file_count": len(tests),
        "test_file_examples": sorted(tests)[:10],
        "ignore_files": sorted(rel for rel in rel_files if path_name(rel) in {".gitignore", ".dockerignore"}),
        "environment_examples": sorted(env_examples),
        "work_markers": dict(markers),
        "large_files": sorted(large_files, key=lambda item: item["bytes"], reverse=True)[:20],
        "sensitive_looking_files": sorted(sensitive, key=lambda item: item["path"]),
    }


def path_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1].lower()


def display_list(values: Iterable[str]) -> str:
    items = list(values)
    return ", ".join(f"`{item}`" for item in items) if items else "None found"


def to_markdown(data: dict[str, Any]) -> str:
    policies = data["policy_files"]
    lines = [
        "# Repository signals",
        "",
        f"- Root: `{data['root']}`",
        f"- Files scanned: {data['file_count']}" + (" (limit reached)" if data["scan_truncated"] else ""),
        f"- Git repository: {'yes' if data['git_repository'] else 'no'}",
        f"- Languages (file count): {', '.join(f'{k} {v}' for k, v in data['languages_by_file_count'].items()) or 'None detected'}",
        "",
        "## Project structure",
        "",
        f"- Manifests: {display_list(data['manifests'])}",
        f"- Lockfiles: {display_list(data['lockfiles'])}",
        f"- Primary documentation: {display_list(data['documentation'])}",
        f"- Licenses: {display_list(data['license_files'])}",
        f"- CI configuration: {display_list(data['ci_files'])}",
        f"- Test files: {data['test_file_count']}",
        f"- Test examples: {display_list(data['test_file_examples'])}",
        f"- Ignore files: {display_list(data['ignore_files'])}",
        f"- Environment examples: {display_list(data['environment_examples'])}",
        "",
        "## Repository policies",
        "",
        f"- Contributing: {display_list(policies['contributing'])}",
        f"- Security: {display_list(policies['security'])}",
        f"- Code of conduct: {display_list(policies['code_of_conduct'])}",
        "",
        "## Review signals",
        "",
        "- Work markers: " + (", ".join(f"{k} {v}" for k, v in data["work_markers"].items()) or "None found"),
    ]
    if data["large_files"]:
        lines.append("- Large files (>=5 MiB): " + ", ".join(
            f"`{item['path']}` ({item['bytes'] / 1_048_576:.1f} MiB)" for item in data["large_files"]
        ))
    else:
        lines.append("- Large files (>=5 MiB): None found")
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
    data = collect(root, args.max_files)
    output = json.dumps(data, indent=2, ensure_ascii=False) + "\n" if args.format == "json" else to_markdown(data)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
