#!/usr/bin/env python3
"""Compare two audit-repo JSON snapshots without inspecting repository contents."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_SCHEMA_VERSIONS = {1}
LARGE_GROWTH_MIN_BYTES = 5 * 1024 * 1024
SET_FIELDS = {
    "manifests": "Manifests",
    "lockfiles": "Lockfiles",
    "documentation": "Primary documentation",
    "license_files": "License files",
    "ci_files": "CI configuration",
    "ci_action_references": "CI action references",
    "dependency_update_config": "Dependency update configuration",
    "codeowners": "CODEOWNERS",
    "container_files": "Container files",
    "environment_examples": "Environment examples",
}


class SnapshotError(ValueError):
    """Raised when a snapshot cannot be compared safely."""


def reject_json_constant(value: str) -> None:
    raise SnapshotError(f"non-finite JSON number is not supported: {value}")


def validate_snapshot(raw: dict[str, Any], path: Path) -> None:
    version = raw.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SnapshotError(f"unsupported schema_version {version!r} in {path}")

    list_fields = set(SET_FIELDS) | {
        "excluded_directory_names", "large_files", "sensitive_looking_files",
    }
    for field in list_fields:
        if field in raw and not isinstance(raw[field], list):
            raise SnapshotError(f"field {field!r} must be a list in {path}")
    for field in set(SET_FIELDS) | {"excluded_directory_names"}:
        if any(not isinstance(item, str) for item in raw.get(field, [])):
            raise SnapshotError(f"field {field!r} must contain only strings in {path}")
    for field in ("file_count", "test_file_count", "large_file_threshold_bytes"):
        value = raw.get(field)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise SnapshotError(f"field {field!r} must be a non-negative integer in {path}")
    if "scan_truncated" in raw and not isinstance(raw["scan_truncated"], bool):
        raise SnapshotError(f"field 'scan_truncated' must be a boolean in {path}")
    if "root" in raw and raw["root"] is not None and not isinstance(raw["root"], str):
        raise SnapshotError(f"field 'root' must be a string or null in {path}")

    markers = raw.get("work_markers", {})
    if not isinstance(markers, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for key, value in markers.items()
    ):
        raise SnapshotError(f"field 'work_markers' must map strings to non-negative integers in {path}")

    automation = raw.get("automation", {})
    if not isinstance(automation, dict):
        raise SnapshotError(f"field 'automation' must be an object in {path}")
    if "configured_tools" in automation and (
        not isinstance(automation["configured_tools"], list)
        or any(not isinstance(item, str) for item in automation["configured_tools"])
    ):
        raise SnapshotError(f"field 'automation.configured_tools' must be a list of strings in {path}")

    for item in raw.get("large_files", []):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("bytes"), int)
            or isinstance(item.get("bytes"), bool)
            or item["bytes"] < 0
        ):
            raise SnapshotError(f"each 'large_files' item needs a string path and non-negative integer bytes in {path}")
    for item in raw.get("sensitive_looking_files", []):
        tracked = item.get("tracked") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or (tracked is not None and not isinstance(tracked, bool))
        ):
            raise SnapshotError(f"each 'sensitive_looking_files' item needs a string path and boolean/null tracked value in {path}")


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_json_constant)
    except OSError as error:
        raise SnapshotError(f"could not read {path}: {error}") from error
    except SnapshotError:
        raise
    except ValueError as error:
        raise SnapshotError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise SnapshotError(f"snapshot must be a JSON object: {path}")
    validate_snapshot(raw, path)
    return raw


def string_set(data: dict[str, Any], field: str) -> set[str]:
    value = data.get(field, [])
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def int_value(data: dict[str, Any], field: str) -> int:
    value = data.get(field, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def total_markers(data: dict[str, Any]) -> int:
    value = data.get("work_markers", {})
    if not isinstance(value, dict):
        return 0
    return sum(item for item in value.values() if isinstance(item, int) and not isinstance(item, bool))


def sensitive_map(data: dict[str, Any]) -> dict[str, bool | None]:
    result: dict[str, bool | None] = {}
    value = data.get("sensitive_looking_files", [])
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        tracked = item.get("tracked")
        result[item["path"]] = tracked if isinstance(tracked, bool) else None
    return result


def large_file_map(data: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    value = data.get("large_files", [])
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        size = item.get("bytes")
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            result[item["path"]] = size
    return result


def append_set_change(
    changes: list[dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
    field: str,
    label: str,
) -> None:
    old = string_set(before, field)
    new = string_set(after, field)
    added = sorted(new - old)
    removed = sorted(old - new)
    if added or removed:
        changes.append({"field": field, "label": label, "added": added, "removed": removed})


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    attention: list[dict[str, str]] = []
    limitations: list[str] = []

    for field, label in SET_FIELDS.items():
        append_set_change(changes, before, after, field, label)

    before_automation = before.get("automation", {})
    after_automation = after.get("automation", {})
    before_tools = before_automation.get("configured_tools", []) if isinstance(before_automation, dict) else []
    after_tools = after_automation.get("configured_tools", []) if isinstance(after_automation, dict) else []
    append_set_change(
        changes,
        {"configured_tools": before_tools},
        {"configured_tools": after_tools},
        "configured_tools",
        "Configured tools",
    )

    for field, label in (("file_count", "Files scanned"), ("test_file_count", "Test files")):
        old = int_value(before, field)
        new = int_value(after, field)
        if old != new:
            changes.append({"field": field, "label": label, "before": old, "after": new, "delta": new - old})

    old_markers = total_markers(before)
    new_markers = total_markers(after)
    if old_markers != new_markers:
        changes.append({
            "field": "work_markers_total",
            "label": "Work markers",
            "before": old_markers,
            "after": new_markers,
            "delta": new_markers - old_markers,
        })
        if new_markers > old_markers:
            attention.append({
                "code": "work-markers-increased",
                "message": f"Comment-style work markers increased from {old_markers} to {new_markers}; review the new markers in context.",
            })

    old_sensitive = sensitive_map(before)
    new_sensitive = sensitive_map(after)
    sensitive_added = sorted(set(new_sensitive) - set(old_sensitive))
    sensitive_removed = sorted(set(old_sensitive) - set(new_sensitive))
    tracking_changed = sorted(
        path for path in set(old_sensitive) & set(new_sensitive)
        if old_sensitive[path] != new_sensitive[path]
    )
    if sensitive_added or sensitive_removed or tracking_changed:
        changes.append({
            "field": "sensitive_looking_files",
            "label": "Sensitive-looking filenames",
            "added": sensitive_added,
            "removed": sensitive_removed,
            "tracking_changed": tracking_changed,
        })
    for path in sensitive_added:
        status = new_sensitive[path]
        tracking = "tracked" if status is True else ("untracked" if status is False else "tracking unknown")
        attention.append({
            "code": "sensitive-filename-added",
            "message": f"Sensitive-looking filename added: {markdown_code(path)} ({tracking}); verify that no secret is committed.",
        })
    for path in tracking_changed:
        if new_sensitive[path] is True:
            attention.append({
                "code": "sensitive-file-now-tracked",
                "message": f"Sensitive-looking file is now tracked: {markdown_code(path)}; verify its contents without exposing values.",
            })

    old_large = large_file_map(before)
    new_large = large_file_map(after)
    large_added = sorted(set(new_large) - set(old_large))
    large_removed = sorted(set(old_large) - set(new_large))
    large_resized = [
        {
            "path": path,
            "before_bytes": old_large[path],
            "after_bytes": new_large[path],
            "delta_bytes": new_large[path] - old_large[path],
        }
        for path in sorted(set(old_large) & set(new_large))
        if old_large[path] != new_large[path]
    ]
    if large_added or large_removed or large_resized:
        changes.append({
            "field": "large_files",
            "label": "Large files",
            "added": large_added,
            "removed": large_removed,
            "resized": large_resized,
        })
    for path in large_added:
        attention.append({"code": "large-file-added", "message": f"New large file detected: {markdown_code(path)}; verify that it belongs in Git."})
    for item in large_resized:
        before_size = item["before_bytes"]
        after_size = item["after_bytes"]
        if item["delta_bytes"] >= LARGE_GROWTH_MIN_BYTES and after_size >= max(1, before_size) * 1.5:
            attention.append({
                "code": "large-file-grew-significantly",
                "message": (
                    f"Large file grew significantly: {markdown_code(item['path'])} "
                    f"from {human_bytes(before_size)} to {human_bytes(after_size)}; verify that the growth is intentional."
                ),
            })

    loss_rules = (
        ("ci_files", "CI configuration disappeared"),
        ("documentation", "Primary documentation disappeared"),
        ("license_files", "License file disappeared"),
    )
    for field, message in loss_rules:
        if string_set(before, field) and not string_set(after, field):
            attention.append({"code": f"{field}-removed", "message": f"{message}; confirm that this was intentional."})
    if int_value(before, "test_file_count") > 0 and int_value(after, "test_file_count") == 0:
        attention.append({"code": "tests-disappeared", "message": "Test files changed from a nonzero count to zero; confirm that tests were not lost."})

    for label, field in (
        ("excluded directory names", "excluded_directory_names"),
        ("large-file threshold", "large_file_threshold_bytes"),
    ):
        if before.get(field) != after.get(field):
            limitations.append(f"The {label} differ between snapshots, so related deltas may not be comparable.")
    if before.get("scan_truncated") or after.get("scan_truncated"):
        limitations.append("At least one scan reached its file limit, so the comparison may be incomplete.")
        attention.append({"code": "scan-truncated", "message": "At least one snapshot is truncated; rerun with a higher --max-files value."})

    return {
        "schema_version": 1,
        "before_root": before.get("root"),
        "after_root": after.get("root"),
        "changes": changes,
        "attention": attention,
        "limitations": limitations,
        "summary": {
            "change_count": len(changes),
            "attention_count": len(attention),
            "comparable": not limitations,
        },
    }


def markdown_code(value: object) -> str:
    """Render untrusted data as a single safe Markdown code span."""
    text = "".join(
        " " if char.isspace() else char if ord(char) >= 32 and not 127 <= ord(char) <= 159 else "?"
        for char in str(value)
    )
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if longest or text.startswith(" ") or text.endswith(" ") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def display_items(values: Iterable[str]) -> str:
    items = list(values)
    return ", ".join(markdown_code(item) for item in items) if items else "none"


def render_change(change: dict[str, Any]) -> str:
    if "delta" in change:
        delta = change["delta"]
        sign = "+" if delta > 0 else ""
        return f"- **{change['label']}:** {change['before']} -> {change['after']} ({sign}{delta})"
    parts = []
    if change.get("added"):
        parts.append(f"added {display_items(change['added'])}")
    if change.get("removed"):
        parts.append(f"removed {display_items(change['removed'])}")
    if change.get("tracking_changed"):
        parts.append(f"tracking changed for {display_items(change['tracking_changed'])}")
    if change.get("resized"):
        parts.append("resized " + ", ".join(
            f"{markdown_code(item['path'])} ({human_bytes(item['before_bytes'])} -> {human_bytes(item['after_bytes'])})"
            for item in change["resized"]
        ))
    return f"- **{change['label']}:** " + "; ".join(parts)


def to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Repository signal comparison",
        "",
        f"- Before: {markdown_code(result['before_root'] or 'Unknown')}",
        f"- After: {markdown_code(result['after_root'] or 'Unknown')}",
        f"- Changed dimensions: {summary['change_count']}",
        f"- Attention items: {summary['attention_count']}",
        f"- Directly comparable: {'yes' if summary['comparable'] else 'no'}",
        "",
        "## Changes",
        "",
    ]
    lines.extend(render_change(change) for change in result["changes"])
    if not result["changes"]:
        lines.append("No tracked signal changes found.")
    lines.extend(["", "## Attention", ""])
    lines.extend(f"- {item['message']}" for item in result["attention"])
    if not result["attention"]:
        lines.append("No high-confidence attention items found.")
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    if not result["limitations"]:
        lines.append("No comparison limits detected.")
    lines.extend(["", "> Signal changes are not findings. Verify repository context before assigning impact or priority."])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="Earlier JSON snapshot")
    parser.add_argument("after", type=Path, help="Later JSON snapshot")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write output to this file instead of stdout")
    parser.add_argument("--fail-on-attention", action="store_true", help="Exit 1 when attention items exist")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = compare(load_snapshot(args.before), load_snapshot(args.after))
    except SnapshotError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n" if args.format == "json" else to_markdown(result)
    if args.output:
        try:
            args.output.write_text(output, encoding="utf-8")
        except OSError as error:
            print(f"error: could not write output: {error}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(output)
    return 1 if args.fail_on_attention and result["attention"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
