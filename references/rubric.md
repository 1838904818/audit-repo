# Repository audit rubric

Use this rubric to make priorities consistent while adapting expectations to the repository's purpose and maturity.

## Priority

- **P0 - Critical:** credible risk of active compromise, irreversible data loss, or a production outage. Recommend immediate containment or rollback.
- **P1 - High:** likely release blocker, exploitable security weakness, broken core path, or failure that can materially affect users or operators.
- **P2 - Medium:** meaningful reliability, maintainability, testing, dependency, or documentation gap with a realistic future cost.
- **P3 - Low:** localized improvement, cleanup, or polish with limited near-term impact.

Raise priority only when both likelihood and impact justify it. Downgrade findings that depend on unverified assumptions.

## Dimensions

### Correctness and verification

Look for executable tests around core behavior, meaningful failure cases, deterministic test setup, and checks that actually run. Test count alone is not coverage evidence.

### Build and delivery

Look for reproducible dependency resolution, documented build/run commands, CI aligned with local checks, release automation where appropriate, and a clear artifact or deployment path.

### Security and dependency hygiene

Look for accidentally tracked sensitive files, unsafe defaults, unsupported runtimes, missing lockfiles where reproducibility matters, unreviewed executable downloads, and security reporting guidance for public projects. Never claim a vulnerability from a package version without verifying it against a current authoritative source.

### Reliability and operations

Look for error handling at boundaries, timeouts and retries for network calls, safe migrations, rollback options, observability, configuration validation, and cleanup of resources. Apply these expectations only to relevant systems.

### Maintainability

Look for understandable structure, bounded complexity, duplicated critical logic, stale TODO/FIXME markers, clear ownership boundaries, and configuration that matches actual behavior.

### Documentation and onboarding

Look for purpose, prerequisites, setup, common commands, configuration, architecture context, contribution guidance, and licensing appropriate to the intended audience. A Codex `SKILL.md` can serve as the primary usage document for a skill repository.

## Evidence standard

A reportable finding needs:

1. a reproducible observation;
2. a plausible impact in this repository's context; and
3. a specific action that would reduce the risk.

Record unavailable checks as uncertainty, not failure. Record missing files only when the project actually needs them.
