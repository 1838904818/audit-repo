# Contributing to audit-repo

Thanks for helping improve the Skill. Changes should preserve its core promise: useful, evidence-backed repository audits that are read-only by default and safe around secrets.

## Before you start

- Search existing issues before opening a new one.
- Use the feature request template for behavior changes.
- Report suspected vulnerabilities privately through [GitHub Security Advisories](https://github.com/1838904818/audit-repo/security/advisories/new), not in a public issue.

## Local development

The project supports Python 3.10 or newer and uses only the standard library. Clone the repository, make a focused change, then run:

```bash
python -m unittest discover -s scripts -p "test_*.py"
python scripts/collect_repo_signals.py . --format markdown
python scripts/collect_repo_signals.py . --format json --output repo-signals.json
python scripts/compare_repo_signals.py repo-signals.json repo-signals.json --format markdown
```

If you have the Codex `skill-creator` package locally, also validate the Skill metadata:

```bash
python /path/to/skill-creator/scripts/quick_validate.py .
```

## Change expectations

- Add or update tests for observable behavior changes.
- Keep scans read-only, bounded, and free of dependency installation or network access.
- Never read or print the contents of sensitive-looking files.
- Preserve JSON compatibility when possible; call out intentional schema changes.
- Update README, Skill instructions, or Wiki documentation when user-facing behavior changes.
- Keep commits focused and explain the user impact in the commit message.

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
