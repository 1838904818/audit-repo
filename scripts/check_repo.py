#!/usr/bin/env python3
"""Run a repository audit and optionally compare it with a JSON baseline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import collect_repo_signals as collector  # noqa: E402
import compare_repo_signals as comparer  # noqa: E402

COLLECTOR = SCRIPT_DIR / "collect_repo_signals.py"
COMPARER = SCRIPT_DIR / "compare_repo_signals.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository directory (default: current directory)")
    parser.add_argument("--output-dir", type=Path, default=Path("audit-repo-results"))
    parser.add_argument("--baseline", type=Path, help="Earlier collector JSON snapshot")
    parser.add_argument("--scan-mode", choices=("filesystem", "git-visible", "tracked"), default="tracked")
    parser.add_argument("--scope-id", default="repository", help="Stable logical scope identifier")
    parser.add_argument("--include-path", action="append", default=[], metavar="GLOB")
    parser.add_argument("--exclude-path", action="append", default=[], metavar="GLOB")
    parser.add_argument("--exclude-dir", action="append", default=[], metavar="NAME")
    parser.add_argument("--max-files", type=int, default=50_000)
    parser.add_argument("--large-file-mib", type=float, default=5.0)
    parser.add_argument("--fail-on-attention", action="store_true")
    parser.add_argument("--require-comparable", action="store_true")
    parser.add_argument("--github-output", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def run(command: list[str]) -> int:
    try:
        return subprocess.run(command, check=False).returncode
    except OSError as error:
        print(f"error: could not start audit tool: {error}", file=sys.stderr)
        return 2


def append_values(command: list[str], option: str, values: list[str]) -> None:
    for value in values:
        command.extend((option, value))


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


def paths_alias(first: Path, second: Path) -> bool:
    if first == second:
        return True
    if not first.exists() or not second.exists():
        return False
    return os.path.samefile(first, second)


def clear_managed_outputs(paths: tuple[Path, ...]) -> bool:
    success = True
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except (OSError, UnicodeError) as error:
            print(f"error: could not remove stale generated output {path}: {error}", file=sys.stderr)
            success = False
    return success


def main() -> int:
    args = parse_args()
    try:
        repository = Path(args.path).expanduser().resolve()
        output_dir = args.output_dir.expanduser().resolve()
        baseline = args.baseline.expanduser().resolve() if args.baseline else None
    except (OSError, RuntimeError) as error:
        print(f"error: could not resolve an input path: {error}", file=sys.stderr)
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
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"error: could not create output directory: {error}", file=sys.stderr)
        return 2
    if not clear_managed_outputs(generated_outputs):
        return 2

    common = [
        str(repository), "--scan-mode", args.scan_mode, "--scope-id", args.scope_id,
        "--max-files", str(args.max_files), "--large-file-mib", str(args.large_file_mib),
    ]
    append_values(common, "--include-path", args.include_path)
    append_values(common, "--exclude-path", args.exclude_path)
    append_values(common, "--exclude-dir", args.exclude_dir)

    collect_json = [sys.executable, str(COLLECTOR), *common, "--format", "json", "--output", str(snapshot)]
    status = run(collect_json)
    if status != 0:
        return status
    try:
        snapshot_data = json.loads(snapshot.read_text(encoding="utf-8"))
        tool_version = str(snapshot_data["tool_version"])
        scan_semantics_version = str(snapshot_data["scan_semantics_version"])
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        print(f"error: could not read generated snapshot provenance: {error}", file=sys.stderr)
        return 2

    attention_count = "0"
    comparable = ""
    if baseline is not None:
        compare_json = [
            sys.executable, str(COMPARER), str(baseline), str(snapshot),
            "--format", "json", "--output", str(comparison),
        ]
        status = run(compare_json)
        if status != 0:
            return status
        try:
            result = json.loads(comparison.read_text(encoding="utf-8"))
            attention_count = str(result["summary"]["attention_count"])
            comparable = str(bool(result["summary"]["comparable"])).lower()
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            print(f"error: could not read generated comparison: {error}", file=sys.stderr)
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

    if args.github_output:
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
        if not write_github_outputs(args.github_output, values):
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
