# Changelog

All notable changes to `audit-repo` are documented here. The project follows semantic versioning.

## [1.10.7] - 2026-08-31

### Security

- Reject YAML explicit mapping-key syntax inside flow collections when enforcing the repository's workflow `uses` pin contract. Forms such as `{ ? uses: owner/project@main }` can parse as a real dependency key and now fail closed.
- Require newly published GitHub Releases to report `immutable: true` before the release workflow succeeds, complementing exact asset-set, byte-identity, and tag-provenance verification.

Snapshot schema 1 and scan semantics 3 are unchanged. Existing snapshots remain comparable when their scan settings and logical scopes match.

## [1.10.6] - 2026-08-31

### Security

- Close workflow pin-contract bypasses where YAML anchors, aliases, or tags make a mapping key parse as `uses` without exposing a canonical textual `uses:` key. Dependency keys using YAML node properties or aliases now fail closed at collection-node boundaries.
- Recognize anchors and tags on block-scalar values so script or description text inside those scalars remains outside the dependency-key policy surface.

Snapshot schema 1 and scan semantics 3 are unchanged. Existing snapshots remain comparable when their scan settings and logical scopes match.

## [1.10.5] - 2026-08-31

### Changed

- Accept both LF and CRLF separators in the Action's multiline `include-paths`, `exclude-paths`, and `exclude-dirs` inputs. Only the trailing CR from a CRLF line ending is removed; embedded control characters remain invalid.
- Strengthen the repository contract so every workflow `uses:` entry is checked, including named steps and reusable workflows, and every external reference must use a full 40-character commit SHA.

Snapshot schema 1 and scan semantics 3 are unchanged. Existing snapshots remain comparable when their scan settings and logical scopes match.

## [1.10.4] - 2026-08-31

### Security

- Limit external comparison snapshots and runner baselines to regular files of at most 64 MiB, preventing unbounded reads and rejecting devices, pipes, and other special files.
- Bind each accepted input with one file descriptor, check its opened target, and read at most one byte beyond the limit so file growth cannot bypass the bound. Symlinks whose opened targets are regular files remain supported.
- Keep runner baseline digest verification and strict parsing on the same captured bytes, before managed output creation, cleanup, temporary-result allocation, or GitHub Action output.
- Escape and bound untrusted snapshot, scan-root, and managed-output path context in errors so control characters cannot forge extra CI log lines or workflow commands.

Snapshot schema 1 and scan semantics 3 are unchanged. Previously accepted regular, unambiguous snapshots no larger than 64 MiB remain compatible; larger or non-regular stored inputs must be replaced before comparison.

## [1.10.3] - 2026-08-31

### Security

- Reject duplicate JSON object keys at every nesting level instead of silently accepting parser-dependent first-value or last-value semantics.
- Apply the same strict parser to standalone comparisons, digest-pinned runner baselines, and collector stdout snapshots.
- Preserve managed reports, GitHub Action output, and unallocated temporary-result state when a digest-matching but duplicate-key baseline fails preflight.

Snapshot schema 1 and scan semantics 3 are unchanged. Unambiguous snapshots remain compatible; any stored snapshot containing duplicate object keys must be regenerated from a reviewed source.

## [1.10.2] - 2026-08-31

### Changed

- Validate and normalize excluded directory names in both collector entry points and the one-command runner before any managed output or Action state can change.
- Keep the established case-insensitive directory-name matching and support for names beginning with `-`, while deduplicating equivalent configured names.

### Security

- Reject empty or whitespace-only exclusions, path separators, `.`/`..` dot segments, and control characters instead of accepting ambiguous or non-portable directory paths as names.
- Exercise invalid excluded-directory preflight in local integration tests and the Linux, Windows, and macOS composite-Action matrix while preserving all existing managed reports, GitHub outputs, and unallocated temporary-result state.

Snapshot schema 1 and scan semantics 3 are unchanged. Snapshots made with identical settings that v1.10.2 still accepts remain comparable; review and replace any newly rejected legacy exclusion value before collecting a new comparison snapshot.

## [1.10.1] - 2026-08-31

### Changed

- Centralize validation and normalization of file limits, large-file thresholds, path globs, and logical scope IDs so the one-command runner and collector use the same rules.
- Share scan-root and Git-worktree eligibility preflight between the runner and collector, and perform all shared preflight checks before the runner allocates an Action temporary directory, creates or clears managed output, or appends GitHub Action outputs.
- Forward paths, scope IDs, globs, and exclusion names as single option tokens so valid values beginning with `-` are not reinterpreted as command-line options.

### Security

- Preserve existing reports and Action state for preflight-invalid collection requests, including malformed settings, an unavailable root, and a Git scan requested for a non-Git directory.
- Normalize every nonzero collector subprocess status to runner exit code `2`, keeping collector execution failures distinct from exit code `1` policy-gate results.
- Exercise representative numeric, path-pattern, and scope rejections in the Linux, Windows, and macOS composite-Action policy matrix.
- Document that concurrent repository writers can invalidate multi-step filesystem observations, and require a quiescent or isolated checkout for an evidence-grade audit.

Snapshot schema 1 and scan semantics 3 are unchanged. This patch changes invalid-input failure timing and the recorded collector version, not scan-signal semantics or comparability for valid settings.

## [1.10.0] - 2026-08-31

### Added

- Add optional `--baseline-sha256` runner verification and a matching `baseline-sha256` composite-Action input for pinning a baseline's exact bytes to an independently obtained expected digest.
- Exercise matching, missing-baseline, strict-format, mismatch, and default-temporary-output digest paths in the three-platform Action policy matrix.

### Changed

- Read a comparison baseline once, verify its digest when requested, parse the same bytes as strict UTF-8 JSON, and retain the validated object in memory instead of reopening the baseline after collection.
- Allocate the Action's unique default output directory only after baseline path, digest, and snapshot validation succeeds.

### Security

- Reject a digest without a baseline, malformed digest text, digest mismatch, unreadable baseline, and invalid baseline before creating or clearing outputs or appending GitHub Action outputs.
- Document that a matching SHA-256 is an exact-byte content pin, not proof of authorship, freshness, review, safety, or comparability. A digest from the same untrusted checkout is not an independent trust signal.

The digest is optional. Snapshot schema 1 and scan semantics 3 are unchanged, so v1.9.1 and v1.10.0 snapshots remain comparable when their scan settings and logical scopes match.

## [1.9.1] - 2026-08-31

### Added

- Exercise successful and rejected composite-Action policy paths on Linux, Windows, and macOS, including SARIF, comparison limitations, sensitive-file attention, invalid configuration, and output collisions.

### Changed

- Advance scan semantics to version 3 because Windows junction/reparse-point traversal could previously include files outside the intended repository root.
- Accept only exact `true` or `false` policy input values in the composite Action and reject enabled comparison gates when no baseline is supplied.
- Require a release tag to resolve to the workflow event commit on the default branch before repository code runs, then verify the published Release is stable, still names that tag, and contains exactly the two expected assets.
- Re-download and compare both online assets after either creating or reusing a Release, then recheck tag/default-branch provenance; a run that finds an existing published Release is verification-only, while an existing draft fails closed without mutation.

### Fixed

- Reject a GitHub output file that aliases the baseline or any managed audit artifact before stale outputs are removed.
- Preflight all four managed output paths so a directory collision fails without partially deleting other stale artifacts.
- Treat symbolic links and Windows reparse points, including NTFS junctions on Python 3.10 and 3.11, as output-path redirects across the scanned root and its entire containing Git worktree, including monorepo siblings.
- Replace broad release asset globs with explicit archive and checksum paths, preventing ambiguous extra assets from passing release verification.

Because traversal coverage changed, v1.9.0 baselines are intentionally not directly comparable with v1.9.1 snapshots. Review the reparse-point boundary and regenerate approved baselines before restoring a comparability gate.

## [1.9.0] - 2026-08-31

### Added

- Recognize Django `tests.py`, conventional case-sensitive .NET `*Tests.cs` files, canonically cased Pipenv, SwiftPM, .NET project/solution manifests, NuGet lockfiles including project-specific names, and Bun lockfiles.
- Recognize SwiftPM version-specific manifests such as `Package@swift-5.10.swift`.
- Restrict CI inventory and GitHub Action-reference extraction to canonical CI entry points and actual top-level GitHub workflow YAML files; ignore `uses:` text inside YAML block scalars.

### Changed

- Advance scan semantics to version 2 for the expanded, lower-noise file classification rules.
- Leave scope IDs unset by default in the runner and composite Action.
- Treat the legacy implicit scope ID `repository` as unset, so it cannot authorize comparison across different repository roots.
- Create the Action's default output directory under `RUNNER_TEMP` instead of inside the audited checkout.

### Fixed

- Reject empty snapshot roots so unknown origins cannot pass the comparability gate.
- Reject output paths that traverse repository-contained symbolic links instead of letting an untrusted checkout redirect managed writes.
- Make the Skill's prompt-injection and repository-code execution trust boundary explicit.
- Resolve Git only from absolute `PATH` directories outside both the lexical scan-entry worktree and the resolved target boundary, using filesystem identity to resist current-directory, monorepo-sibling, symlink-entry, and case-variant executable hijacking.
- Leave worktree cleanliness unknown instead of invoking broader repository-aware status machinery.
- Disable repository-configured Git hooks and filesystem monitors, suppress optional locks and prompts, and discard inherited `GIT_*` targeting/configuration overrides.
- Run the composite Action's Python processes in isolated mode so checkout-local modules cannot shadow the standard library or runner code imports.

Because file classification changed, snapshots created before v1.9.0 have a different scan-semantics version and are intentionally not directly comparable. Review the classification changes and regenerate approved baselines. For future cross-root comparisons, set the same repository-qualified scope ID on both snapshots.

## [1.8.2] - 2026-08-31

### Fixed

- Reject snapshots with duplicate large-file or sensitive-file paths instead of using order-dependent last-write-wins comparison data.
- Remove only the runner's four managed outputs before each run so a reused output directory cannot expose stale comparison reports or SARIF.
- Fail closed on managed-output directory collisions without recursively deleting user files.
- Clarify Action output behavior when no baseline is supplied.

## [1.8.1] - 2026-08-31

### Fixed

- Encode Action output values containing CR or LF with GitHub's multiline file-command format.
- Prevent a user-controlled output path from injecting additional `$GITHUB_OUTPUT` keys on platforms that allow newline characters in filenames.
- Reject a baseline that aliases any generated output before collection can overwrite trusted comparison evidence.
- Refuse release packaging when the requested tag version differs from the collector's runtime `TOOL_VERSION`.

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

[1.10.7]: https://github.com/1838904818/audit-repo/compare/v1.10.6...v1.10.7
[1.10.6]: https://github.com/1838904818/audit-repo/compare/v1.10.5...v1.10.6
[1.10.5]: https://github.com/1838904818/audit-repo/compare/v1.10.4...v1.10.5
[1.10.4]: https://github.com/1838904818/audit-repo/compare/v1.10.3...v1.10.4
[1.10.3]: https://github.com/1838904818/audit-repo/compare/v1.10.2...v1.10.3
[1.10.2]: https://github.com/1838904818/audit-repo/compare/v1.10.1...v1.10.2
[1.10.1]: https://github.com/1838904818/audit-repo/compare/v1.10.0...v1.10.1
[1.10.0]: https://github.com/1838904818/audit-repo/compare/v1.9.1...v1.10.0
[1.9.1]: https://github.com/1838904818/audit-repo/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/1838904818/audit-repo/compare/v1.8.2...v1.9.0
[1.8.2]: https://github.com/1838904818/audit-repo/compare/v1.8.1...v1.8.2
[1.8.1]: https://github.com/1838904818/audit-repo/compare/v1.8.0...v1.8.1
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
