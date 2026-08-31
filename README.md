# audit-repo

[![CI](https://github.com/1838904818/audit-repo/actions/workflows/ci.yml/badge.svg)](https://github.com/1838904818/audit-repo/actions/workflows/ci.yml)
[![Release](https://github.com/1838904818/audit-repo/actions/workflows/release.yml/badge.svg)](https://github.com/1838904818/audit-repo/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/1838904818/audit-repo)](https://github.com/1838904818/audit-repo/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An evidence-backed, read-only repository health audit Skill for Codex, with standalone Python tools for reproducible inventory and snapshot comparison.

中文简介：这是一个实用的 Codex Skill，用于只读审查代码仓库的测试、CI、依赖、文档、安全信号与技术债，并将结果整理为有证据和优先级的行动清单。参见[中文快速开始](#中文快速开始)。

## Features

- Collect repository signals as Markdown or JSON without installing project dependencies.
- Detect Git state, manifests, lockfiles, tests, CI, automation, ownership, containers, work markers, large files, and sensitive-looking filenames across common Python, JavaScript, .NET, Swift, JVM, Go, Rust, Ruby, and PHP repositories.
- Compare configuration-aware audit snapshots and surface meaningful changes over time.
- Flag high-confidence attention items such as newly detected sensitive filenames, lost CI or tests, and new large files.
- Keep secret values private: filename checks never read or print sensitive file contents.
- Preserve complete large-file inventories in JSON while keeping Markdown reports bounded and readable.
- Support Git-aware scan modes, monorepo path scopes, custom exclusions, recorded file limits, and large-file thresholds.

The collector produces inventory signals, not automatic findings. The Skill tells Codex to verify context and evidence before assigning impact or priority.

## Install as a Codex Skill

The easiest option in Codex is to ask the built-in installer to install this repository:

```text
Use $skill-installer to install https://github.com/1838904818/audit-repo.
```

For an offline or version-pinned installation, download the `.zip` and matching `.sha256` file from the [latest release](https://github.com/1838904818/audit-repo/releases/latest). Verify the checksum, then extract the archive's top-level `audit-repo` directory into `$HOME/.agents/skills`. Release assets are built only after the full test matrix passes on Linux, Windows, and macOS with Python 3.10 and 3.14. Before repository code runs, publishing verifies that the remote tag resolves to the workflow event commit on the default branch. It then verifies that the Release is stable and its exact two-asset set matches the current deterministic build, and rechecks tag/default-branch provenance after the online assets match. A run that finds an existing published Release leaves it unchanged and verifies it; an existing draft fails closed without being edited or deleted.

For a manual user-wide installation, clone the repository into the official local skills directory. See the [OpenAI Build skills documentation](https://learn.chatgpt.com/docs/build-skills) for current locations and invocation methods.

macOS or Linux:

```bash
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/1838904818/audit-repo.git "$HOME/.agents/skills/audit-repo"
```

Windows PowerShell:

```powershell
$skillRoot = Join-Path $HOME ".agents\skills"
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
git clone https://github.com/1838904818/audit-repo.git (Join-Path $skillRoot "audit-repo")
```

Codex detects installed skill changes automatically. If the Skill does not appear, restart Codex.

Invoke it explicitly in Codex CLI or the IDE extension with `/skills` or `$audit-repo`:

```text
Use $audit-repo to audit this repository and prioritize the most important fixes.
```

In the ChatGPT desktop app, type `@` and choose **Audit Repo** from the skill picker.

Codex can also invoke it automatically for repository health, release readiness, maintainability, security posture, technical debt, and audit comparison requests.

## Standalone usage

Requires Python 3.10 or newer. Python 3.10 through 3.14 are continuously tested, and the scripts use only the Python standard library.

Audit a repository:

```bash
python scripts/collect_repo_signals.py /path/to/repo --format markdown
```

Save a reusable JSON snapshot:

```bash
python scripts/collect_repo_signals.py /path/to/repo --format json --output before.json
```

When using `filesystem`, keep reusable snapshots outside the target repository so an earlier output does not become input to the next scan.

Choose a scan mode for the intended workflow:

```bash
# Default: reachable filesystem files, including ignored and untracked files
python scripts/collect_repo_signals.py /path/to/repo --scan-mode filesystem

# Tracked files plus non-ignored untracked files
python scripts/collect_repo_signals.py /path/to/repo --scan-mode git-visible

# Stable CI baseline containing tracked files that are present in the worktree
python scripts/collect_repo_signals.py /path/to/repo --scan-mode tracked --scope-id acme/widget:whole-repository
```

Scope a monorepo with repeatable, case-sensitive, root-relative POSIX globs:

```bash
python scripts/collect_repo_signals.py /path/to/repo \
  --scan-mode tracked \
  --include-path "packages/api/*" \
  --exclude-path "packages/api/generated/*" \
  --scope-id acme/widget:api-package \
  --format json --output api.json
```

Every mode keeps the collector's built-in directory exclusions and skips symlinks. Path globs use Python `fnmatchcase` semantics against the full relative path; `*` can match `/`, and exclusions win over inclusions. `tracked` omits every untracked file, whether ignored or not, but still includes tracked files that later match an ignore rule. Use `filesystem` when discovering accidentally created sensitive files is the priority.

`git-visible` follows the checkout's effective Git ignore configuration, including repository-local and global excludes. Use the same ignore configuration for repeat comparisons. Git metadata such as worktree state describes the Git checkout and can be broader than a path-glob scope. If Git enumerates a tracked file that is absent from the worktree—for example in a sparse checkout—the snapshot records an incomplete scan and the comparer will not treat it as directly comparable.

Scope IDs are unset by default and do not change which files are scanned. They are only an explicit assertion that snapshots from different resolved roots represent the same logical scope. Use a project-qualified value on both snapshots, never reuse it across repositories or packages, and regenerate a reviewed baseline when adopting it. The legacy implicit value `repository` no longer proves cross-root equivalence.

v1.9.0 also advances scan semantics to version 2. Snapshots created by v1.8.x therefore produce a deliberate comparison limitation even at the same root; review the new classification rules and regenerate approved baselines before restoring a comparability gate.

v1.9.1 advances scan semantics to version 3 because Windows junction and reparse-point traversal is now excluded consistently with symbolic links. A v1.9.0 baseline therefore produces a deliberate limitation; review the boundary change and regenerate the approved baseline before restoring `--require-comparable`.

Manifest and lockfile inventory uses canonical, case-sensitive filenames so a snapshot does not claim that an ecosystem tool will consume a mis-cased file on a case-sensitive platform. The inventory includes SwiftPM version-specific manifests and NuGet project-specific lockfiles. GitHub Action references are lexical workflow signals: script and description block contents are excluded, while an unambiguous single-line block value attached to `uses` is recognized.

Compare two snapshots:

```bash
python scripts/compare_repo_signals.py before.json after.json --format markdown
```

Run the complete workflow with one command. It always writes `snapshot.json` and `report.md`; when a baseline is supplied it also writes `comparison.json` and `comparison.sarif`:

```bash
python scripts/check_repo.py /path/to/repo --output-dir audit-results
python scripts/check_repo.py /path/to/repo \
  --baseline previous-snapshot.json \
  --baseline-sha256 "$EXPECTED_BASELINE_SHA256" \
  --output-dir audit-results \
  --fail-on-attention --require-comparable
```

`--baseline-sha256` accepts exactly 64 hexadecimal characters (uppercase or lowercase) and checks the baseline's raw bytes before parsing it. Prefixes, whitespace, and checksum-file lines are rejected. JSON formatting, a byte-order mark, trailing newlines, and LF/CRLF conversion all change the digest. External snapshots and baselines must resolve to regular files no larger than 64 MiB; pipes, devices, directories, and larger files are rejected. A symbolic link remains accepted when its opened target is a regular file within that limit. Snapshot JSON must also have unique object keys at every nesting level; duplicate keys are rejected because JSON consumers disagree on first-value versus last-value interpretation. Obtain the expected digest independently from maintainer-controlled configuration or a separately verified artifact; do not calculate it from the same untrusted baseline immediately before this check.

Before each run, the runner removes only those four managed output paths so reused directories cannot expose stale reports. It preflights all four paths, preserves every other entry, and fails with exit code `2` without deleting any sibling artifact when a managed path is a directory. Enabling either comparison gate without `--baseline` is also invalid. A malformed digest, digest without a baseline, digest mismatch, unreadable, oversized, non-regular, or invalid baseline fails before the output directory is created or any managed artifact or GitHub Action output is changed. When supplied, the baseline is opened once, verified as a bounded regular file, read once, optionally digest-checked, parsed as strict UTF-8 JSON, and kept in memory for the comparison. The digest remains optional; valid, unchanged baselines retain the same comparison semantics and results when it is omitted, although the runner still reads and freezes the baseline before collection. Snapshot, scan-root, and managed-output path context is ASCII-escaped and length-bounded in errors so hostile filenames cannot add CI log lines or workflow commands.

The runner also validates `--max-files`, `--large-file-mib`, include/exclude path globs, excluded directory names, `--scope-id`, scan-root availability, and Git-mode worktree eligibility before it creates or clears managed output, allocates an Action temporary directory, or appends Action outputs. An excluded directory must be a non-empty single name: path separators, `.`/`..`, whitespace-only values, and control characters are rejected, while names beginning with `-` remain valid. Matching is case-insensitive, as in earlier releases. The collector and runner share those preflight rules, so malformed settings, a missing root, or an incompatible Git scan mode returns `2` without sacrificing earlier reports. Successful collection still occurs after stale managed files are cleared, preserving established scan results when the output directory is inside the scanned root.

The runner also refuses an output directory that traverses a symbolic link or Windows reparse point (including an NTFS junction) anywhere inside the scanned repository or its containing Git worktree. This includes monorepo siblings when only a subdirectory is scanned, preventing an untrusted checkout from redirecting managed writes outside its tree. In Action mode, the GitHub output file must not equal or alias the baseline or any managed artifact.

Git-aware collection resolves Git to an absolute executable found in an absolute `PATH` directory outside the entire containing Git worktree, including when only a monorepo subdirectory is scanned. Both the lexical scan entry and its resolved target define untrusted boundaries, and containment is verified by filesystem identity as well as path spelling. Repository-contained symlinks or case variants on case-insensitive volumes therefore cannot hide a checkout-local executable. The collector never relies on current-directory executable lookup, so a checkout-local `git.exe` cannot turn a static Windows audit into code execution. Worktree cleanliness is intentionally reported as `unknown` so the inventory does not invoke broader repository-aware status machinery.

Run an audit against a quiescent checkout and do not execute untrusted repository code concurrently. Collection is a point-in-time best effort across multiple filesystem operations; a separate process that replaces files during the scan can invalidate earlier link, identity, or size observations. Use an isolated checkout when concurrent writers cannot be excluded.

Use snapshot comparison in automation, failing both on high-confidence attention items and on an incomparable baseline:

```bash
python scripts/compare_repo_signals.py before.json after.json --fail-on-attention --require-comparable
```

Produce SARIF 2.1.0 for code-scanning viewers and CI systems:

```bash
python scripts/compare_repo_signals.py before.json after.json \
  --format sarif --output audit-repo.sarif
```

SARIF `warning` results are attention signals and `note` results are comparison limitations. They require repository-context verification and are not confirmed vulnerabilities. Policy exit codes remain controlled separately by `--fail-on-attention` and `--require-comparable`.

Comparison exit codes:

- `0`: comparison completed and no enabled policy gate failed; without gate flags, attention and limitations remain report-only
- `1`: a requested policy gate failed: attention items with `--fail-on-attention`, or comparison limits with `--require-comparable`
- `2`: invalid input or execution error

New JSON snapshots record the collector version, scan-semantics version, mode, logical path scope, configured file limit, scan completeness, and every large file found within the scanned scope. Comparison JSON, Markdown, and SARIF preserve both snapshots' provenance so compatibility decisions remain visible in every report format. A collector release can change without invalidating comparisons when its scan semantics remain compatible; a changed or one-sided semantics version becomes a comparison limitation and suppresses scope-dependent alerts. Two legacy snapshots without this metadata remain mutually comparable under the older rules. Markdown output displays at most 20 items per long change list and points to JSON for the complete data. A project-qualified non-empty `--scope-id` lets equivalent checkouts at different absolute roots compare safely. When an older snapshot may contain only the legacy top-20 large-file list, the comparer reports a limitation and suppresses unreliable large-file addition/removal alerts.

Run `python scripts/collect_repo_signals.py --help` or `python scripts/compare_repo_signals.py --help` for all options.

## GitHub Actions

Use the repository directly as a composite Action. Pin a release tag or commit SHA in production workflows:

```yaml
- uses: 1838904818/audit-repo@v1.10.4
  id: audit
  with:
    scan-mode: tracked
    scope-id: ${{ github.repository }}:whole-repository
    output-dir: ${{ runner.temp }}/audit-repo
```

The Action requires Python 3.10 or newer on the runner and does not install project dependencies. It starts Python in isolated mode so checkout-local modules cannot shadow the standard library. When `output-dir` is omitted, it creates a unique directory under GitHub's `RUNNER_TEMP` instead of writing into the audited checkout. Its outputs include `snapshot`, `report`, `comparison`, `sarif`, `attention-count`, `comparable`, `tool-version`, and `scan-semantics-version`; callers can upload reports or record provenance without parsing the snapshot.

For a checked-in baseline, enable both policy gates:

```yaml
- name: Validate baseline digest configuration
  shell: bash
  env:
    EXPECTED_BASELINE_SHA256: ${{ vars.AUDIT_BASELINE_SHA256 }}
  run: |
    [[ "$EXPECTED_BASELINE_SHA256" =~ ^[0-9A-Fa-f]{64}$ ]] || {
      echo "::error::AUDIT_BASELINE_SHA256 must be configured as exactly 64 hex characters"
      exit 2
    }

- uses: 1838904818/audit-repo@v1.10.4
  with:
    baseline: .github/audit-baseline.json
    baseline-sha256: ${{ vars.AUDIT_BASELINE_SHA256 }}
    scan-mode: tracked
    scope-id: ${{ github.repository }}:whole-repository
    exclude-paths: |
      .github/audit-baseline.json
    fail-on-attention: "true"
    require-comparable: "true"
```

`include-paths`, `exclude-paths`, and `exclude-dirs` accept newline-separated values. Each non-empty `exclude-dirs` line is one directory name, not a path; the Action safely preserves a leading `-` in that name. Create the approved baseline with the same exclusions so the baseline file does not become part of its own comparison scope. Configure the non-secret digest variable through maintainer-controlled repository or environment settings, and keep the explicit format check: an unset Actions variable expands to an empty value, which otherwise means no digest pin was requested. Policy inputs accept only the exact strings `true` and `false`. Leave both gates false for a collection-only run: enabling either gate without `baseline`, or supplying another boolean spelling, is rejected as invalid configuration instead of silently disabling policy.

Digest matching proves only that the baseline has the expected exact bytes. It does not prove authorship, freshness, review status, safety, unambiguous JSON semantics, or comparison compatibility, and it does not replace strict parsing or `require-comparable`. In a `pull_request` workflow, a baseline and digest both loaded from the untrusted pull-request checkout—or a digest calculated from that baseline in the same job—do not form an independent security gate. Load the baseline from a protected base ref or separately trusted artifact, obtain its expected digest through an independent maintainer-controlled channel, and verify both before comparison.

## What the audit covers

| Area | Example signals |
| --- | --- |
| Repository state | Git repository, branch or detached commit, tracked file count; worktree cleanliness remains safely unknown |
| Build and dependencies | Manifests, lockfiles, configured tools, package scripts, Make targets |
| Verification | Tests, CI configuration, CI action references |
| Security hygiene | Sensitive-looking filenames, environment examples, dependency update configuration |
| Maintainability | TODO/FIXME-style comment markers, documentation, ownership, policies |
| Delivery | Container files, large files, license files |

See [SKILL.md](SKILL.md) for the agent workflow, [audit rubric](references/rubric.md) for priorities, and [check selection](references/check-selection.md) for safe project-native commands.

## Project resources

- [Wiki](https://github.com/1838904818/audit-repo/wiki) for task-oriented guides and CLI details
- [Releases](https://github.com/1838904818/audit-repo/releases) for versioned, checksummed Skill archives
- [Changelog](CHANGELOG.md) for version-by-version behavior and compatibility notes
- [Contributing guide](https://github.com/1838904818/audit-repo/blob/main/CONTRIBUTING.md) for local validation and change expectations
- [Code of conduct](https://github.com/1838904818/audit-repo/blob/main/CODE_OF_CONDUCT.md) for community participation expectations
- [Security policy](https://github.com/1838904818/audit-repo/security/policy) for private vulnerability reporting

## 中文快速开始

安装后，在 Codex 新任务中输入：

```text
使用 $audit-repo 审查当前仓库，给出最重要的三个改进建议。
```

也可以不安装 Skill，直接运行只读扫描器：

```bash
python scripts/collect_repo_signals.py 项目路径 --format markdown
```

对比前后两次审查结果：

```bash
python scripts/collect_repo_signals.py 项目路径 --format json --output before.json
# 修改或修复项目后，再生成 after.json
python scripts/compare_repo_signals.py before.json after.json --format markdown
```

扫描器不会读取或输出疑似密钥文件的内容。新版 JSON 快照会记录扫描文件上限并保留完整的大文件清单；Markdown 只展示有限条目，避免报告失控。它提供的是待核实信号，最终问题等级应结合实际代码和项目用途判断。

## Development

Validate the Skill and run all tests:

```bash
python /path/to/skill-creator/scripts/quick_validate.py .
python -m unittest discover -s scripts -p "test_*.py"
```

Build the same deterministic assets used by GitHub Releases:

```bash
python scripts/package_skill.py --version v1.10.4 --output-dir dist
```

The requested package version must match `TOOL_VERSION` in `scripts/collect_repo_signals.py`.

CI exercises Markdown output, JSON output, snapshot comparison, repository contracts, the composite Action, and deterministic packaging. Python 3.10 and 3.14 run on Linux, Windows, and macOS; Python 3.11 through 3.13 also run on Linux. A separate three-platform Action policy matrix verifies successful baseline gates and fail-closed attention, comparability, configuration, and collision paths. Release tags verify the minimum and latest versions on all three operating systems before publishing assets.

## License

[MIT](LICENSE)
