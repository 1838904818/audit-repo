---
name: audit-repo
description: Audit a software repository and turn reproducible signals into a prioritized, evidence-backed health report. Use when Codex is asked to assess repository health, readiness, maintainability, test and CI coverage, dependency hygiene, documentation, security posture, technical debt, release risk, or the most important improvements to make before shipping or handing off a codebase.
---

# Audit Repo

Produce a useful repository audit without changing the repository. Combine deterministic inventory with project-aware checks, verify each material finding, and prioritize actions instead of dumping a generic checklist.

## Workflow

### 1. Establish scope

- Audit the current repository unless the user names another path.
- Treat generated code, vendored dependencies, fixtures, and archived experiments as out of scope unless they affect shipping risk.
- Inspect `git status -sb` first. Preserve all existing changes and never attribute them to the audit.
- Remain read-only unless the user explicitly asks for fixes or a saved report.

### 2. Collect baseline signals

Run the bundled collector from the skill directory:

```bash
python scripts/collect_repo_signals.py /path/to/repo --format markdown
```

Use `--format json` when structured output will make further analysis easier. The collector ignores common dependency/build directories, does not follow symlinks, and checks only filenames, not contents, for sensitive-looking files.

If Python is unavailable, gather equivalent signals with available read-only tools. Do not install a runtime just for the inventory.

### 3. Understand the project before judging it

- Read the root documentation, manifests, CI definitions, and the smallest relevant configuration files.
- Identify the repository's purpose, maturity, deployability, and likely consumers.
- Infer intended commands from checked-in configuration rather than guessing.
- Do not penalize a small prototype for enterprise controls unless the user asks for that standard.

### 4. Run native checks

Choose the narrowest relevant checks already supported by the repository, such as tests, linters, type checks, builds, or dependency validation.

- Prefer documented commands and scripts declared in manifests.
- Do not install dependencies, start persistent services, contact production systems, or apply automatic fixes.
- Use bounded timeouts and report checks that could not run separately from checks that failed.
- Treat a command failure as evidence to investigate, not automatically as the root cause.

### 5. Assess and verify

Read [references/rubric.md](references/rubric.md) before assigning priorities.

- Cite a file, line, command result, or reproducible absence for every material finding.
- Open the relevant source before reporting a search hit; exclude comments, examples, tests, and dead code when they make the hit harmless.
- Distinguish observed facts from inferences.
- Never print secret values. If a sensitive-looking tracked file exists, report only its path and verification method.
- Prefer a few high-confidence findings over a long speculative list.

### 6. Report answer-first

Return this structure unless the user requests another format:

1. **Verdict** - 2-4 sentences on overall health and the largest risk.
2. **Top actions** - the three highest-value next steps.
3. **Findings** - priority, evidence, impact, and a concrete recommendation.
4. **Checks run** - pass, fail, and unable-to-run results.
5. **Limits** - scope exclusions and remaining uncertainty.

Use `P0` through `P3` priorities from the rubric. Do not invent a numerical score unless the user asks for one. If no material issue is found, say so plainly and list the evidence reviewed.

## Fix mode

When the user also asks to fix findings, finish the read-only audit first, then implement only the agreed or clearly requested scope. Re-run the affected checks and separate fixed findings from remaining risks.
