#!/usr/bin/env python3
"""Run a repository audit and optionally compare it with a JSON baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import collect_repo_signals as collector  # noqa: E402
import compare_repo_signals as comparer  # noqa: E402

COLLECTOR = SCRIPT_DIR / "collect_repo_signals.py"
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class BaselineError(ValueError):
    """Raised when a comparison baseline cannot be loaded safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository directory (default: current directory)")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output-dir", type=Path, help="Output directory (default: audit-repo-results)",
    )
    output_group.add_argument("--temporary-output-parent", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--baseline", type=Path, help="Earlier collector JSON snapshot")
    parser.add_argument(
        "--baseline-sha256",
        help="Expected 64-hex SHA-256 of the baseline's exact bytes; requires --baseline",
    )
    parser.add_argument("--scan-mode", choices=("filesystem", "git-visible", "tracked"), default="tracked")
    parser.add_argument(
        "--scope-id", help="Project-qualified logical scope ID for equivalent roots (unset by default)",
    )
    parser.add_argument("--include-path", action="append", default=[], metavar="GLOB")
    parser.add_argument("--exclude-path", action="append", default=[], metavar="GLOB")
    parser.add_argument("--exclude-dir", action="append", default=[], metavar="NAME")
    parser.add_argument("--max-files", type=int, default=50_000)
    parser.add_argument("--large-file-mib", type=float, default=5.0)
    parser.add_argument("--fail-on-attention", action="store_true", help="Fail on attention items; requires --baseline")
    parser.add_argument("--require-comparable", action="store_true", help="Fail when incomparable; requires --baseline")
    parser.add_argument("--github-output", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def collect_snapshot(command: list[str]) -> tuple[int, bytes | None, dict[str, object] | None]:
    try:
        completed = subprocess.run(command, check=False, stdout=subprocess.PIPE)
    except OSError as error:
        print(f"error: could not start audit tool: {error}", file=sys.stderr)
        return 2, None, None
    if completed.returncode != 0:
        print(f"error: audit collector failed with exit status {completed.returncode}", file=sys.stderr)
        return 2, None, None
    try:
        snapshot = comparer.load_snapshot_bytes(completed.stdout, Path("<collector stdout>"))
    except comparer.SnapshotError as error:
        print(f"error: could not parse collector JSON: {error}", file=sys.stderr)
        return 2, None, None
    return 0, completed.stdout, snapshot


def append_values(command: list[str], option: str, values: list[str]) -> None:
    for value in values:
        command.append(f"{option}={value}")


def write_github_outputs(path: Path, values: dict[str, str]) -> bool:
    try:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                if "\n" not in value and "\r" not in value:
                    stream.write(f"{key}={value}\n")
                    continue
                value_lines = set(value.splitlines())
                delimiter = f"audit_repo_{uuid.uuid4().hex}"
                while delimiter in value_lines:
                    delimiter = f"audit_repo_{uuid.uuid4().hex}"
                stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
    except (OSError, UnicodeError) as error:
        print(f"error: could not write GitHub Action outputs: {error}", file=sys.stderr)
        return False
    return True


def write_text(path: Path, content: str, label: str) -> bool:
    try:
        path.write_text(content, encoding="utf-8")
    except (OSError, UnicodeError) as error:
        print(f"error: could not write {label}: {error}", file=sys.stderr)
        return False
    return True


def write_bytes(path: Path, content: bytes, label: str) -> bool:
    try:
        path.write_bytes(content)
    except OSError as error:
        print(f"error: could not write {label}: {error}", file=sys.stderr)
        return False
    return True


def paths_alias(first: Path, second: Path) -> bool:
    if first == second:
        return True
    if not first.exists() or not second.exists():
        return False
    return os.path.samefile(first, second)


def load_baseline(path: Path, expected_sha256: str | None) -> dict[str, object]:
    try:
        baseline_bytes = path.read_bytes()
    except OSError as error:
        raise BaselineError(f"could not read baseline {path}: {error}") from error
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(baseline_bytes).hexdigest()
        normalized_expected = expected_sha256.lower()
        if actual_sha256 != normalized_expected:
            raise BaselineError(
                "baseline SHA-256 mismatch "
                f"(expected {normalized_expected}, got {actual_sha256})"
            )
    try:
        return comparer.load_snapshot_bytes(baseline_bytes, path)
    except comparer.SnapshotError as error:
        raise BaselineError(str(error)) from error


def clear_managed_outputs(paths: tuple[Path, ...]) -> bool:
    for path in paths:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as error:
            print(f"error: could not inspect stale generated output {path}: {error}", file=sys.stderr)
            return False
        if stat.S_ISDIR(metadata.st_mode):
            print(
                f"error: could not remove stale generated output {path}: managed output path is a directory",
                file=sys.stderr,
            )
            return False

    success = True
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except (OSError, UnicodeError) as error:
            print(f"error: could not remove stale generated output {path}: {error}", file=sys.stderr)
            success = False
    return success


def absolute_without_symlink_resolution(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.drive and not expanded.is_absolute():
        raise ValueError("drive-relative paths are not supported")
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


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


def repository_output_redirect(untrusted_boundaries: tuple[Path, ...], output_candidate: Path) -> Path | None:
    resolved_parent = Path(output_candidate.anchor).resolve()
    for part in output_candidate.parts[1:]:
        if part == "..":
            resolved_parent = resolved_parent.parent
            continue
        parent_is_untrusted = any(
            path_is_within(resolved_parent, boundary)
            for boundary in untrusted_boundaries
        )
        next_path = resolved_parent / part
        if parent_is_untrusted and collector.path_is_link_or_reparse_point(next_path):
            return next_path
        resolved_parent = next_path.resolve(strict=False)
    return None


def main() -> int:
    args = parse_args()
    enabled_gates = [
        option
        for enabled, option in (
            (args.fail_on_attention, "--fail-on-attention"),
            (args.require_comparable, "--require-comparable"),
        )
        if enabled
    ]
    if enabled_gates and args.baseline is None:
        print(f"error: enabling {', '.join(enabled_gates)} requires --baseline", file=sys.stderr)
        return 2
    if args.baseline_sha256 is not None and args.baseline is None:
        print("error: --baseline-sha256 requires --baseline", file=sys.stderr)
        return 2
    if args.baseline_sha256 is not None and SHA256_RE.fullmatch(args.baseline_sha256) is None:
        print("error: --baseline-sha256 must be exactly 64 hexadecimal characters", file=sys.stderr)
        return 2
    try:
        _, include_paths, exclude_paths, scope_id = collector.validate_collection_options(
            args.max_files,
            args.large_file_mib,
            include_paths=args.include_path,
            exclude_paths=args.exclude_path,
            scope_id=args.scope_id,
        )
        exclude_dirs = collector.normalize_excluded_directory_names(args.exclude_dir)
    except collector.CollectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    temporary_output_parent = None
    output_dir = None
    try:
        repository_candidate = absolute_without_symlink_resolution(Path(args.path))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: could not resolve an input path: {error}", file=sys.stderr)
        return 2
    try:
        repository = collector.validate_collection_target(repository_candidate, args.scan_mode)
    except collector.CollectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        untrusted_output_boundaries = tuple({
            repository,
            collector.git_worktree_boundary(repository_candidate),
            collector.git_worktree_boundary(repository),
        })
        requested_output = args.output_dir if args.output_dir is not None else Path("audit-repo-results")
        if args.temporary_output_parent is not None:
            output_candidate = absolute_without_symlink_resolution(args.temporary_output_parent)
        else:
            output_candidate = absolute_without_symlink_resolution(requested_output)
        unsafe_output_component = repository_output_redirect(untrusted_output_boundaries, output_candidate)
        if unsafe_output_component is not None:
            print(
                "error: output directory must not traverse a symbolic link or reparse point inside the repository or containing Git worktree",
                file=sys.stderr,
            )
            return 2
        resolved_output_candidate = output_candidate.resolve()
        if args.temporary_output_parent is not None:
            temporary_output_parent = resolved_output_candidate
            if any(
                path_is_within(temporary_output_parent, boundary)
                for boundary in untrusted_output_boundaries
            ):
                print(
                    "error: temporary output parent must be outside the repository and containing Git worktree",
                    file=sys.stderr,
                )
                return 2
        else:
            output_dir = resolved_output_candidate
        baseline = args.baseline.expanduser().resolve() if args.baseline else None
        github_output = args.github_output.expanduser().resolve() if args.github_output else None
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: could not resolve an input path: {error}", file=sys.stderr)
        return 2

    if baseline is not None and github_output is not None:
        try:
            baseline_aliases_github_output = paths_alias(baseline, github_output)
        except OSError as error:
            print(f"error: could not verify baseline and GitHub output isolation: {error}", file=sys.stderr)
            return 2
        if baseline_aliases_github_output:
            print("error: GitHub output must not alias the baseline", file=sys.stderr)
            return 2

    baseline_data = None
    if baseline is not None:
        try:
            baseline_data = load_baseline(baseline, args.baseline_sha256)
        except BaselineError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    if temporary_output_parent is not None:
        try:
            output_dir = Path(tempfile.mkdtemp(prefix="audit-repo-", dir=temporary_output_parent))
        except OSError as error:
            print(f"error: could not create temporary output directory: {error}", file=sys.stderr)
            return 2
    if output_dir is None:
        print("error: output directory was not selected", file=sys.stderr)
        return 2

    snapshot = output_dir / "snapshot.json"
    report = output_dir / "report.md"
    comparison = output_dir / "comparison.json"
    sarif = output_dir / "comparison.sarif"
    generated_outputs = (snapshot, report, comparison, sarif)
    if baseline is not None:
        try:
            baseline_aliases_output = any(
                paths_alias(baseline, generated)
                for generated in generated_outputs
            )
        except OSError as error:
            print(f"error: could not verify baseline isolation: {error}", file=sys.stderr)
            return 2
        if baseline_aliases_output:
            print("error: baseline must not alias any generated output", file=sys.stderr)
            return 2
    if github_output is not None:
        try:
            github_output_aliases_generated = any(
                paths_alias(github_output, generated)
                for generated in generated_outputs
            )
        except OSError as error:
            print(f"error: could not verify GitHub output isolation: {error}", file=sys.stderr)
            return 2
        if github_output_aliases_generated:
            print("error: GitHub output must not alias any generated output", file=sys.stderr)
            return 2
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"error: could not create output directory: {error}", file=sys.stderr)
        return 2
    if not clear_managed_outputs(generated_outputs):
        return 2

    common = [
        f"--scan-mode={args.scan_mode}",
        f"--max-files={args.max_files}",
        f"--large-file-mib={args.large_file_mib}",
    ]
    if scope_id is not None:
        common.append(f"--scope-id={scope_id}")
    append_values(common, "--include-path", include_paths)
    append_values(common, "--exclude-path", exclude_paths)
    append_values(common, "--exclude-dir", exclude_dirs)

    collect_json = [
        sys.executable, "-I", str(COLLECTOR), *common,
        "--format=json", "--", str(repository_candidate),
    ]
    status, snapshot_bytes, snapshot_data = collect_snapshot(collect_json)
    if status != 0 or snapshot_bytes is None or snapshot_data is None:
        return status
    try:
        tool_version = str(snapshot_data["tool_version"])
        scan_semantics_version = str(snapshot_data["scan_semantics_version"])
    except (KeyError, TypeError) as error:
        print(f"error: could not read generated snapshot provenance: {error}", file=sys.stderr)
        return 2
    if not write_bytes(snapshot, snapshot_bytes, "snapshot JSON"):
        return 2

    attention_count = "0"
    comparable = ""
    if baseline is not None:
        try:
            if baseline_data is None:
                raise comparer.SnapshotError("baseline was not loaded")
            result = comparer.compare(baseline_data, snapshot_data)
            comparison_text = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
            if not write_text(comparison, comparison_text, "comparison JSON"):
                return 2
            attention_count = str(result["summary"]["attention_count"])
            comparable = str(bool(result["summary"]["comparable"])).lower()
        except (comparer.SnapshotError, KeyError, TypeError) as error:
            print(f"error: could not compare snapshots: {error}", file=sys.stderr)
            return 2
        if not write_text(report, comparer.to_markdown(result), "Markdown report"):
            return 2
        if not write_text(sarif, json.dumps(comparer.to_sarif(result), indent=2, ensure_ascii=True) + "\n", "SARIF report"):
            return 2
        attention_failed = args.fail_on_attention and bool(result["attention"])
        comparability_failed = args.require_comparable and not result["summary"]["comparable"]
        status = 1 if attention_failed or comparability_failed else 0
    else:
        if not write_text(report, collector.to_markdown(snapshot_data), "Markdown report"):
            return 2
        status = 0

    if github_output is not None:
        values = {
            "snapshot": str(snapshot),
            "report": str(report),
            "comparison": str(comparison) if baseline is not None else "",
            "sarif": str(sarif) if baseline is not None else "",
            "attention-count": attention_count,
            "comparable": comparable,
            "tool-version": tool_version,
            "scan-semantics-version": scan_semantics_version,
        }
        if not write_github_outputs(github_output, values):
            return 2
    print(f"snapshot={snapshot}")
    print(f"report={report}")
    print(f"tool_version={tool_version}")
    print(f"scan_semantics_version={scan_semantics_version}")
    if baseline is not None:
        print(f"comparison={comparison}")
        print(f"sarif={sarif}")
        print(f"attention_count={attention_count}")
        print(f"comparable={comparable}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
