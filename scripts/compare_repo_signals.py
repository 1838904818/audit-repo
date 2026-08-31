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
SCAN_MODES = {"filesystem", "git-visible", "tracked"}
LEGACY_IMPLICIT_SCOPE_IDS = {"repository"}
REQUIRED_SNAPSHOT_FIELDS = {
    "root", "file_count", "scan_truncated", "excluded_directory_names",
    "work_markers", "large_file_threshold_bytes", "large_files",
    "sensitive_looking_files",
}
LARGE_GROWTH_MIN_BYTES = 5 * 1024 * 1024
MAX_COUNT = 2**63 - 1
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


def unique_json_object(pairs: list[tuple[str, Any]], source: Path) -> dict[str, Any]:
    """Build one JSON object while rejecting parser-dependent duplicate keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            display = ascii(key)
            if len(display) > 120:
                display = display[:117] + "..."
            raise SnapshotError(f"duplicate JSON object key {display} in {source}")
        result[key] = value
    return result


def validate_unique_paths(items: list[Any], field: str, source: Path) -> None:
    seen: set[str] = set()
    for item in items:
        item_path = item["path"]
        if item_path in seen:
            raise SnapshotError(f"field {field!r} must not contain duplicate paths in {source}")
        seen.add(item_path)


def validate_snapshot(raw: dict[str, Any], path: Path) -> None:
    version = raw.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SnapshotError(f"unsupported schema_version {version!r} in {path}")

    list_fields = set(SET_FIELDS) | {
        "excluded_directory_names", "exclude_path_patterns", "include_path_patterns",
        "large_files", "scan_incomplete_reasons", "sensitive_looking_files",
    }
    for field in list_fields:
        if field in raw and not isinstance(raw[field], list):
            raise SnapshotError(f"field {field!r} must be a list in {path}")
    for field in set(SET_FIELDS) | {
        "excluded_directory_names", "exclude_path_patterns", "include_path_patterns",
        "scan_incomplete_reasons",
    }:
        if any(not isinstance(item, str) for item in raw.get(field, [])):
            raise SnapshotError(f"field {field!r} must contain only strings in {path}")
    for field in ("file_count", "test_file_count", "large_file_threshold_bytes"):
        value = raw.get(field)
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or (field in {"file_count", "test_file_count"} and value > MAX_COUNT)
        ):
            raise SnapshotError(f"field {field!r} must be a non-negative integer in {path}")
    if "scan_file_limit" in raw:
        scan_file_limit = raw["scan_file_limit"]
        if not isinstance(scan_file_limit, int) or isinstance(scan_file_limit, bool) or scan_file_limit < 1:
            raise SnapshotError(f"field 'scan_file_limit' must be a positive integer in {path}")
    if "tool_version" in raw:
        tool_version = raw["tool_version"]
        if (
            not isinstance(tool_version, str)
            or not tool_version.strip()
            or len(tool_version) > 100
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in tool_version)
        ):
            raise SnapshotError(
                f"field 'tool_version' must be 1-100 characters with non-whitespace content "
                f"and no control characters in {path}"
            )
    if "scan_semantics_version" in raw:
        semantics_version = raw["scan_semantics_version"]
        if not isinstance(semantics_version, int) or isinstance(semantics_version, bool) or semantics_version < 1:
            raise SnapshotError(f"field 'scan_semantics_version' must be a positive integer in {path}")
    if "scan_truncated" in raw and not isinstance(raw["scan_truncated"], bool):
        raise SnapshotError(f"field 'scan_truncated' must be a boolean in {path}")
    if "large_files_complete" in raw and not isinstance(raw["large_files_complete"], bool):
        raise SnapshotError(f"field 'large_files_complete' must be a boolean in {path}")
    if "root" in raw and (
        not isinstance(raw["root"], str) or not raw["root"].strip()
    ):
        raise SnapshotError(f"field 'root' must be a non-empty string in {path}")
    if "scan_mode" in raw and (
        not isinstance(raw["scan_mode"], str) or raw["scan_mode"] not in SCAN_MODES
    ):
        raise SnapshotError(f"field 'scan_mode' must be one of {sorted(SCAN_MODES)} in {path}")
    if "scope_id" in raw and raw["scope_id"] is not None:
        scope_id = raw["scope_id"]
        if (
            not isinstance(scope_id, str)
            or not scope_id.strip()
            or len(scope_id) > 200
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in scope_id)
        ):
            raise SnapshotError(
                f"field 'scope_id' must be null or 1-200 characters with non-whitespace content "
                f"and no control characters in {path}"
            )

    markers = raw.get("work_markers", {})
    if not isinstance(markers, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_COUNT
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

    validate_unique_paths(raw.get("large_files", []), "large_files", path)
    validate_unique_paths(raw.get("sensitive_looking_files", []), "sensitive_looking_files", path)

    missing_fields = sorted(REQUIRED_SNAPSHOT_FIELDS - raw.keys())
    if missing_fields:
        raise SnapshotError(f"snapshot is missing required collector fields in {path}: {', '.join(missing_fields)}")


def load_snapshot_bytes(content: bytes, path: Path) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        raw = json.loads(
            text,
            parse_constant=reject_json_constant,
            object_pairs_hook=lambda pairs: unique_json_object(pairs, path),
        )
    except SnapshotError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise SnapshotError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise SnapshotError(f"snapshot must be a JSON object: {path}")
    validate_snapshot(raw, path)
    return raw


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise SnapshotError(f"could not read {path}: {error}") from error
    return load_snapshot_bytes(content, path)


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


def large_file_list_is_complete(data: dict[str, Any]) -> bool:
    explicit = data.get("large_files_complete")
    if isinstance(explicit, bool):
        return explicit
    value = data.get("large_files", [])
    return isinstance(value, list) and len(value) < 20


def scan_scope(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "scan_mode": data.get("scan_mode", "filesystem"),
        "include_path_patterns": sorted(set(data.get("include_path_patterns", []))),
        "exclude_path_patterns": sorted(set(data.get("exclude_path_patterns", []))),
        "scope_id": data.get("scope_id"),
    }


def effective_scope_id(value: object) -> object:
    if value is None or (isinstance(value, str) and value in LEGACY_IMPLICIT_SCOPE_IDS):
        return None
    return value


def logical_scope_limitations(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    before_has_semantics = "scan_semantics_version" in before
    after_has_semantics = "scan_semantics_version" in after
    if before_has_semantics != after_has_semantics:
        limitations.append(
            "The scan semantics version is unavailable in one snapshot, so equivalent logical scope cannot be confirmed."
        )
    elif before_has_semantics and before["scan_semantics_version"] != after["scan_semantics_version"]:
        limitations.append(
            "The scan semantics versions differ between snapshots, so the logical scan scopes are not equivalent."
        )
    if sorted(set(before.get("excluded_directory_names", []))) != sorted(
        set(after.get("excluded_directory_names", []))
    ):
        limitations.append("The excluded directory names differ between snapshots, so related deltas may not be comparable.")

    before_scope = scan_scope(before)
    after_scope = scan_scope(after)
    labels = {
        "scan_mode": "scan modes",
        "include_path_patterns": "included path globs",
        "exclude_path_patterns": "excluded path globs",
    }
    for field, label in labels.items():
        if before_scope[field] != after_scope[field]:
            limitations.append(f"The {label} differ between snapshots, so the logical scan scopes are not equivalent.")
    before_scope_id = effective_scope_id(before_scope["scope_id"])
    after_scope_id = effective_scope_id(after_scope["scope_id"])
    if before_scope_id != after_scope_id:
        limitations.append("The scope IDs differ between snapshots, so the logical scan scopes are not equivalent.")
    roots_differ = before.get("root") != after.get("root")
    shared_scope_id = bool(before_scope_id) and before_scope_id == after_scope_id
    if roots_differ and not shared_scope_id:
        limitations.append(
            "The snapshot roots differ without a shared non-empty scope ID, so equivalent logical scope cannot be confirmed."
        )
    return limitations


def scan_is_complete(data: dict[str, Any]) -> bool:
    return not data.get("scan_truncated") and not data.get("scan_incomplete_reasons", [])


def scan_scope_limitations(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    limitations = logical_scope_limitations(before, after)

    before_has_limit = "scan_file_limit" in before
    after_has_limit = "scan_file_limit" in after
    if before_has_limit != after_has_limit:
        limitations.append(
            "The scan file limit is unavailable in one snapshot, so equivalent scan scope cannot be confirmed."
        )
    elif before_has_limit and before["scan_file_limit"] != after["scan_file_limit"]:
        limitations.append("The scan file limits differ between snapshots, so file-count deltas may not be comparable.")

    if before.get("scan_truncated") or after.get("scan_truncated"):
        limitations.append("At least one scan reached its file limit, so the comparison may be incomplete.")
    if before.get("scan_incomplete_reasons") or after.get("scan_incomplete_reasons"):
        limitations.append(
            "At least one snapshot reports an incomplete scan, so scope-dependent deltas may not be comparable."
        )
    return limitations


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
    limitations = scan_scope_limitations(before, after)
    logical_scope_comparable = not logical_scope_limitations(before, after)
    scans_complete = scan_is_complete(before) and scan_is_complete(after)
    scope_alerts_comparable = logical_scope_comparable and scans_complete
    large_threshold_comparable = before.get("large_file_threshold_bytes") == after.get("large_file_threshold_bytes")

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
        if new_markers > old_markers and scope_alerts_comparable:
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
    for path in (sensitive_added if scope_alerts_comparable else []):
        status = new_sensitive[path]
        tracking = "tracked" if status is True else ("untracked" if status is False else "tracking unknown")
        attention.append({
            "code": "sensitive-filename-added",
            "message": f"Sensitive-looking filename added: {markdown_code(path)} ({tracking}); verify that no secret is committed.",
        })
    for path in tracking_changed:
        if scope_alerts_comparable and old_sensitive[path] is False and new_sensitive[path] is True:
            attention.append({
                "code": "sensitive-file-now-tracked",
                "message": f"Sensitive-looking file is now tracked: {markdown_code(path)}; verify its contents without exposing values.",
            })

    old_large = large_file_map(before)
    new_large = large_file_map(after)
    large_lists_complete = large_file_list_is_complete(before) and large_file_list_is_complete(after)
    large_inventory_comparable = (
        large_lists_complete and scans_complete and logical_scope_comparable and large_threshold_comparable
    )
    large_added = sorted(set(new_large) - set(old_large)) if large_inventory_comparable else []
    large_removed = sorted(set(old_large) - set(new_large)) if large_inventory_comparable else []
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
        if (
            scope_alerts_comparable
            and item["delta_bytes"] >= LARGE_GROWTH_MIN_BYTES
            and after_size * 2 >= max(1, before_size) * 3
        ):
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
        if scope_alerts_comparable and string_set(before, field) and not string_set(after, field):
            attention.append({"code": f"{field}-removed", "message": f"{message}; confirm that this was intentional."})
    if scope_alerts_comparable and int_value(before, "test_file_count") > 0 and int_value(after, "test_file_count") == 0:
        attention.append({"code": "tests-disappeared", "message": "Test files changed from a nonzero count to zero; confirm that tests were not lost."})

    if not large_threshold_comparable:
        limitations.append(
            "The large-file thresholds differ between snapshots, so large-file additions and removals are not comparable."
        )
    if not large_lists_complete:
        limitations.append(
            "At least one snapshot may contain only the legacy top-20 large-file list, so large-file additions and removals were not compared."
        )
    if before.get("scan_truncated") or after.get("scan_truncated"):
        attention.append({"code": "scan-truncated", "message": "At least one snapshot is truncated; rerun with a higher --max-files value."})

    return {
        "schema_version": 1,
        "before_root": before.get("root"),
        "after_root": after.get("root"),
        "before_provenance": {
            "tool_version": before.get("tool_version"),
            "scan_semantics_version": before.get("scan_semantics_version"),
        },
        "after_provenance": {
            "tool_version": after.get("tool_version"),
            "scan_semantics_version": after.get("scan_semantics_version"),
        },
        "before_scan_scope": scan_scope(before),
        "after_scan_scope": scan_scope(after),
        "changes": changes,
        "attention": attention,
        "limitations": limitations,
        "summary": {
            "change_count": len(changes),
            "attention_count": len(attention),
            "comparable": not limitations,
            "logical_scope_comparable": logical_scope_comparable,
            "scans_complete": scans_complete,
        },
    }


def markdown_code(value: object) -> str:
    """Render untrusted data as a single safe Markdown code span."""
    text = "".join(
        " " if char.isspace() else char
        if ord(char) >= 32 and not 127 <= ord(char) <= 159 and not 0xD800 <= ord(char) <= 0xDFFF
        else "?"
        for char in str(value)
    )
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if longest or text.startswith(" ") or text.endswith(" ") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    if value < 0:
        return f"-{human_bytes(-value)}"
    if value < 1024:
        return f"{value} B"
    unit_index = 0
    divisor = 1
    while unit_index < len(units) - 1 and value >= divisor * 1024:
        divisor *= 1024
        unit_index += 1
    tenths = (value * 10 + divisor // 2) // divisor
    # Avoid Python's configurable huge-integer decimal conversion limit while
    # still giving a useful order of magnitude for adversarially large values.
    if tenths.bit_length() > 1500:
        binary_exponent = max(0, value.bit_length() - 1 - 10 * unit_index)
        return f"~2^{binary_exponent} {units[unit_index]}"
    return f"{tenths // 10}.{tenths % 10} {units[unit_index]}"


def display_items(values: Iterable[str], limit: int = 20) -> str:
    items = list(values)
    if not items:
        return "none"
    rendered = ", ".join(markdown_code(item) for item in items[:limit])
    remaining = len(items) - limit
    return rendered + (f", and {remaining} more in JSON output" if remaining > 0 else "")


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
        resized = change["resized"]
        parts.append("resized " + ", ".join(
            f"{markdown_code(item['path'])} ({human_bytes(item['before_bytes'])} -> {human_bytes(item['after_bytes'])})"
            for item in resized[:20]
        ) + (f", and {len(resized) - 20} more in JSON output" if len(resized) > 20 else ""))
    return f"- **{change['label']}:** " + "; ".join(parts)


def to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    before_scope = result.get("before_scan_scope", {})
    after_scope = result.get("after_scan_scope", {})
    before_provenance = result.get("before_provenance", {})
    after_provenance = result.get("after_provenance", {})
    lines = [
        "# Repository signal comparison",
        "",
        f"- Before: {markdown_code(result['before_root'] or 'Unknown')}",
        f"- After: {markdown_code(result['after_root'] or 'Unknown')}",
        f"- Before collector version: {markdown_code(before_provenance.get('tool_version') or 'Unknown')}",
        f"- After collector version: {markdown_code(after_provenance.get('tool_version') or 'Unknown')}",
        f"- Before scan semantics version: {markdown_code(before_provenance.get('scan_semantics_version') or 'Unknown')}",
        f"- After scan semantics version: {markdown_code(after_provenance.get('scan_semantics_version') or 'Unknown')}",
        f"- Before scan mode: {markdown_code(before_scope.get('scan_mode', 'filesystem'))}",
        f"- After scan mode: {markdown_code(after_scope.get('scan_mode', 'filesystem'))}",
        f"- Before scope ID: {markdown_code(before_scope.get('scope_id')) if before_scope.get('scope_id') is not None else 'None'}",
        f"- After scope ID: {markdown_code(after_scope.get('scope_id')) if after_scope.get('scope_id') is not None else 'None'}",
        f"- Before included path globs: {display_items(before_scope.get('include_path_patterns', []))}",
        f"- After included path globs: {display_items(after_scope.get('include_path_patterns', []))}",
        f"- Before excluded path globs: {display_items(before_scope.get('exclude_path_patterns', []))}",
        f"- After excluded path globs: {display_items(after_scope.get('exclude_path_patterns', []))}",
        f"- Changed dimensions: {summary['change_count']}",
        f"- Attention items: {summary['attention_count']}",
        f"- Directly comparable: {'yes' if summary['comparable'] else 'no'}",
        f"- Logical scan scope equivalent: {'yes' if summary.get('logical_scope_comparable', summary['comparable']) else 'no'}",
        f"- Scans complete: {'yes' if summary.get('scans_complete', True) else 'no'}",
        "",
        "## Changes",
        "",
    ]
    lines.extend(render_change(change) for change in result["changes"])
    if not result["changes"]:
        lines.append("No tracked signal changes found.")
    lines.extend(["", "## Attention", ""])
    displayed_attention = result["attention"][:50]
    lines.extend(f"- {item['message']}" for item in displayed_attention)
    if len(result["attention"]) > len(displayed_attention):
        lines.append(f"- {len(result['attention']) - len(displayed_attention)} more attention items are available in JSON output.")
    if not result["attention"]:
        lines.append("No high-confidence attention items found.")
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    if not result["limitations"]:
        lines.append("No comparison limits detected.")
    lines.extend(["", "> Signal changes are not findings. Verify repository context before assigning impact or priority."])
    return "\n".join(lines) + "\n"


def to_sarif(result: dict[str, Any]) -> dict[str, Any]:
    """Render attention items and limitations as portable SARIF 2.1.0 signals."""
    rule_ids = sorted({item["code"] for item in result["attention"]})
    rules = [
        {
            "id": rule_id,
            "shortDescription": {"text": rule_id.replace("-", " ").capitalize()},
            "helpUri": "https://github.com/1838904818/audit-repo/wiki/Snapshot-Comparison",
            "properties": {"tags": ["repository-health", "audit-repo"]},
        }
        for rule_id in rule_ids
    ]
    if result["limitations"]:
        rules.append({
            "id": "comparison-limitation",
            "shortDescription": {"text": "Snapshot comparison limitation"},
            "helpUri": "https://github.com/1838904818/audit-repo/wiki/Snapshot-Comparison",
            "properties": {"tags": ["repository-health", "audit-repo", "comparability"]},
        })
    results = [
        {
            "ruleId": item["code"],
            "level": "warning",
            "message": {"text": item["message"]},
            "properties": {"kind": "attention", "findingStatus": "signal-needs-verification"},
        }
        for item in result["attention"]
    ]
    results.extend(
        {
            "ruleId": "comparison-limitation",
            "level": "note",
            "message": {"text": limitation},
            "properties": {"kind": "limitation", "findingStatus": "not-a-finding"},
        }
        for limitation in result["limitations"]
    )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "audit-repo",
                "informationUri": "https://github.com/1838904818/audit-repo",
                "rules": rules,
            }},
            "results": results,
            "properties": {
                "beforeRoot": result.get("before_root"),
                "afterRoot": result.get("after_root"),
                "beforeProvenance": result.get("before_provenance", {}),
                "afterProvenance": result.get("after_provenance", {}),
                "summary": result["summary"],
                "notice": "Repository signals require verification and are not confirmed vulnerabilities.",
            },
        }],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="Earlier JSON snapshot")
    parser.add_argument("after", type=Path, help="Later JSON snapshot")
    parser.add_argument("--format", choices=("markdown", "json", "sarif"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write output to this file instead of stdout")
    parser.add_argument("--fail-on-attention", action="store_true", help="Exit 1 when attention items exist")
    parser.add_argument("--require-comparable", action="store_true", help="Exit 1 when comparison limitations exist")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = compare(load_snapshot(args.before), load_snapshot(args.after))
    except SnapshotError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.format == "markdown":
        output = to_markdown(result)
    else:
        rendered = result if args.format == "json" else to_sarif(result)
        output = json.dumps(rendered, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        try:
            args.output.write_text(output, encoding="utf-8")
        except (OSError, UnicodeError) as error:
            print(f"error: could not write output: {error}", file=sys.stderr)
            return 2
    else:
        try:
            sys.stdout.write(output)
        except (OSError, UnicodeError) as error:
            print(f"error: could not write output: {error}", file=sys.stderr)
            return 2
    attention_failed = args.fail_on_attention and bool(result["attention"])
    comparability_failed = args.require_comparable and not result["summary"]["comparable"]
    return 1 if attention_failed or comparability_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
