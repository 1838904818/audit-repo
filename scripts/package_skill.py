#!/usr/bin/env python3
"""Build a deterministic, installable audit-repo Skill archive."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "audit-repo"
VERSION_RE = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
RUNTIME_FILES = (
    Path("SKILL.md"),
    Path("README.md"),
    Path("LICENSE"),
    Path("agents/openai.yaml"),
    Path("references/check-selection.md"),
    Path("references/rubric.md"),
    Path("scripts/collect_repo_signals.py"),
    Path("scripts/compare_repo_signals.py"),
)


class PackageError(ValueError):
    """Raised when a release archive cannot be built safely."""


def normalize_version(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise PackageError("version must look like v1.2.3 or 1.2.3")
    return version if version.startswith("v") else f"v{version}"


def archive_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise PackageError(f"could not read required file {path}: {error}") from error


def build_archive(version: str, output_dir: Path) -> tuple[Path, Path, str]:
    normalized = normalize_version(version)
    missing = [str(path) for path in RUNTIME_FILES if not (ROOT / path).is_file()]
    if missing:
        raise PackageError("missing required runtime files: " + ", ".join(missing))
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PackageError(f"could not create output directory {output_dir}: {error}") from error

    archive = output_dir / f"audit-repo-{normalized}.zip"
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for relative in RUNTIME_FILES:
                info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative.as_posix()}", FIXED_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o644 & 0xFFFF) << 16
                bundle.writestr(info, archive_bytes(ROOT / relative))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    except OSError as error:
        raise PackageError(f"could not write release assets: {error}") from error
    return archive, checksum, digest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version, such as v1.2.3")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"), help="Asset output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        archive, checksum, digest = build_archive(args.version, args.output_dir)
    except PackageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"archive={archive}")
    print(f"checksum={checksum}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
