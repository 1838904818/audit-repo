# Security Policy

## Supported versions

Security fixes are applied to the latest release and the `main` branch. Users should upgrade to the newest published version before reporting an issue that may already be fixed.

## Reporting a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/1838904818/audit-repo/security/advisories/new). Do not disclose a suspected vulnerability, secret, exploit, or sensitive repository data in a public issue.

Include the affected version or commit, operating system, Python version, minimal reproduction steps, impact, and any suggested mitigation. Remove real credentials and private repository contents from examples.

If the report concerns exposed credentials, revoke or rotate them immediately; deleting them from Git history is not sufficient.

## Scope

Useful reports include unintended file writes, unsafe path handling, secret-content disclosure, archive path traversal, unbounded resource use, and incorrect security-sensitive audit output. General feature requests belong in the public issue tracker.
