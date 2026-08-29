# Changelog

All notable changes to `audit-repo` are documented here. The project follows semantic versioning.

## [1.8.0] - 2026-08-30

### Added

- Expose `tool-version` and `scan-semantics-version` from the one-command runner and composite GitHub Action.
- Let CI workflows record snapshot provenance without separately parsing `snapshot.json`.

## [1.7.2] - 2026-08-30

### Fixed

- Reject empty, overlong, non-string, and control-character collector-version metadata before it can enter comparison JSON, Markdown, or SARIF.
- Add malformed provenance regression coverage while retaining valid legacy snapshot compatibility.

## [1.7.1] - 2026-08-30

### Changed

- Preserve before/after collector and scan-semantics provenance in comparison JSON, Markdown, and SARIF output.
- Display provenance directly in human-readable comparison reports so comparability decisions are auditable without reopening source snapshots.

## [1.7.0] - 2026-08-30

### Added

- Record the collector version and an explicit scan-semantics version in new JSON snapshots and Markdown inventories.
- Validate scan-provenance metadata and cover compatible, mismatched, mixed legacy, and legacy-only comparisons.

### Changed

- Mark changed or one-sided scan-semantics versions as comparison limitations and suppress scope-dependent alerts that could otherwise be misleading.
- Keep two legacy snapshots without scan-semantics metadata mutually comparable under the existing legacy rules.

## [1.6.0] - 2026-08-21

### Added

- Add SARIF 2.1.0 output for snapshot attention signals and comparison limitations.
- Add `comparison.sarif` to one-command baseline runs and expose its path from the composite GitHub Action.
- Exercise SARIF generation in the full cross-platform CI and packaged-Skill release checks.

### Changed

- Keep SARIF severity separate from policy exit codes and label every exported result as a signal requiring verification rather than a confirmed vulnerability.

## [1.5.0] - 2026-08-18

### Added

- Add macOS to continuous integration and release verification.
- Test every supported Python minor version from 3.10 through 3.14 in CI.

### Changed

- Require the release test matrix to pass on Linux, Windows, and macOS at both the minimum and latest supported Python versions.
- Build release assets with Python 3.14 while preserving deterministic archive output.
- Skip the Linux-specific raw-byte filename round-trip test on POSIX filesystems that reject non-UTF-8 byte paths.

## [1.4.0] - 2026-08-17

### Added

- Add `scripts/check_repo.py` as a one-command audit runner that writes a JSON snapshot and Markdown report.
- Add a reusable composite GitHub Action with optional baseline comparison, attention, and comparability gates.
- Expose snapshot, report, comparison, attention-count, and comparability paths or values as Action outputs.

### Changed

- Exercise the one-command runner and local composite Action in the cross-platform CI matrix.
- Include the one-command runner in versioned Skill archives.

## [1.3.0] - 2026-08-13

### Added

- Add `filesystem`, `git-visible`, and `tracked` scan modes for discovery, large repositories, and stable CI baselines.
- Add repeatable case-sensitive include/exclude path globs and a stable logical scope ID for monorepos.
- Record scan mode and path scope in JSON snapshots and comparison reports.
- Add `--require-comparable` for automation that must reject comparison limitations.
- Add a project code of conduct.

### Changed

- Mark scope configuration changes as comparison limitations and suppress high-confidence alerts that could be caused by a changed scope.
- Detect incomplete Git worktrees, including missing sparse-checkout paths, instead of silently treating them as complete scans.
- Keep older snapshots compatible by treating missing mode and path fields as the historical filesystem defaults.

### Fixed

- Preserve non-UTF-8 Git paths, safely render untrusted Git metadata, and handle very large supported JSON integers without tracebacks.
- Reject JSON objects that do not contain the minimum collector snapshot structure.
- Record filesystem and Git worktree enumeration failures as incomplete scans.
- Avoid suppressing valid alerts solely because two complete scans used different file limits.
- Report a sensitive file as newly tracked only when its prior state was explicitly untracked.

## [1.2.0] - 2026-08-13

### Added

- Record each snapshot's scan file limit so mismatched collection scopes can be detected.
- Preserve the complete large-file inventory in JSON snapshots while bounding human-readable reports.
- Recognize additional high-signal credential paths, key stores, environment templates, and Terraform state files without reading their contents.
- Validate and exercise extracted Skill archives before publishing a GitHub Release.
- Publish a task-oriented GitHub Wiki with installation, CLI, comparison, automation, FAQ, and Chinese guides.

### Changed

- Make release archives byte-reproducible across line-ending conventions without relying on zlib output.
- Suppress unreliable large-file additions and removals when comparing against a legacy top-20 snapshot.
- Make release publishing safe to rerun by verifying existing assets byte-for-byte without mutating an established release.

## [1.1.0] - 2026-08-13

### Added

- Cross-platform CI on Windows and Linux with Python 3.10 and 3.13.
- Deterministic release packaging with a matching SHA-256 asset.
- Contribution, security, ownership, issue, and pull request guidance.

### Fixed

- Skip sensitive-looking file contents during work-marker collection.
- Escape untrusted paths in Markdown reports.
- Validate malformed and non-finite snapshot input without tracebacks.
- Detect significant growth of existing large files and avoid false scan-truncation reports.

## [1.0.1] - 2026-08-12

- Added a bilingual README and quick-start guidance.

## [1.0.0] - 2026-08-12

- First stable release of the Codex Skill, repository signal collector, snapshot comparer, tests, and CI.

[1.8.0]: https://github.com/1838904818/audit-repo/compare/v1.7.2...v1.8.0
[1.7.2]: https://github.com/1838904818/audit-repo/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/1838904818/audit-repo/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/1838904818/audit-repo/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/1838904818/audit-repo/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/1838904818/audit-repo/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/1838904818/audit-repo/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/1838904818/audit-repo/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/1838904818/audit-repo/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/1838904818/audit-repo/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/1838904818/audit-repo/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/1838904818/audit-repo/releases/tag/v1.0.0
