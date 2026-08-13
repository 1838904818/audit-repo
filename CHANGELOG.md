# Changelog

All notable changes to `audit-repo` are documented here. The project follows semantic versioning.

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

[1.2.0]: https://github.com/1838904818/audit-repo/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/1838904818/audit-repo/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/1838904818/audit-repo/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/1838904818/audit-repo/releases/tag/v1.0.0
