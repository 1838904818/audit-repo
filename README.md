# audit-repo

[![CI](https://github.com/1838904818/audit-repo/actions/workflows/ci.yml/badge.svg)](https://github.com/1838904818/audit-repo/actions/workflows/ci.yml)
[![Release](https://github.com/1838904818/audit-repo/actions/workflows/release.yml/badge.svg)](https://github.com/1838904818/audit-repo/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/1838904818/audit-repo)](https://github.com/1838904818/audit-repo/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An evidence-backed, read-only repository health audit Skill for Codex, with standalone Python tools for reproducible inventory and snapshot comparison.

中文简介：这是一个实用的 Codex Skill，用于只读审查代码仓库的测试、CI、依赖、文档、安全信号与技术债，并将结果整理为有证据和优先级的行动清单。参见[中文快速开始](#中文快速开始)。

## Features

- Collect repository signals as Markdown or JSON without installing project dependencies.
- Detect Git state, manifests, lockfiles, tests, CI, automation, ownership, containers, work markers, large files, and sensitive-looking filenames.
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

For an offline or version-pinned installation, download the `.zip` and matching `.sha256` file from the [latest release](https://github.com/1838904818/audit-repo/releases/latest). Verify the checksum, then extract the archive's top-level `audit-repo` directory into `$HOME/.agents/skills`. Release assets are built only after the full test matrix passes on Linux, Windows, and macOS with Python 3.10 and 3.14.

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
python scripts/collect_repo_signals.py /path/to/repo --scan-mode tracked --scope-id whole-repository
```

Scope a monorepo with repeatable, case-sensitive, root-relative POSIX globs:

```bash
python scripts/collect_repo_signals.py /path/to/repo \
  --scan-mode tracked \
  --include-path "packages/api/*" \
  --exclude-path "packages/api/generated/*" \
  --scope-id api-package \
  --format json --output api.json
```

Every mode keeps the collector's built-in directory exclusions and skips symlinks. Path globs use Python `fnmatchcase` semantics against the full relative path; `*` can match `/`, and exclusions win over inclusions. `tracked` omits every untracked file, whether ignored or not, but still includes tracked files that later match an ignore rule. Use `filesystem` when discovering accidentally created sensitive files is the priority.

`git-visible` follows the checkout's effective Git ignore configuration, including repository-local and global excludes. Use the same ignore configuration for repeat comparisons. Git metadata such as worktree state describes the Git checkout and can be broader than a path-glob scope. If Git enumerates a tracked file that is absent from the worktree—for example in a sparse checkout—the snapshot records an incomplete scan and the comparer will not treat it as directly comparable.

Compare two snapshots:

```bash
python scripts/compare_repo_signals.py before.json after.json --format markdown
```

Run the complete workflow with one command. It always writes `snapshot.json` and `report.md`; when a baseline is supplied it also writes `comparison.json` and `comparison.sarif`:

```bash
python scripts/check_repo.py /path/to/repo --output-dir audit-results
python scripts/check_repo.py /path/to/repo \
  --baseline previous-snapshot.json \
  --output-dir audit-results \
  --fail-on-attention --require-comparable
```

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

New JSON snapshots record the collector version, scan-semantics version, mode, logical path scope, configured file limit, scan completeness, and every large file found within the scanned scope. Comparison JSON, Markdown, and SARIF preserve both snapshots' provenance so compatibility decisions remain visible in every report format. A collector release can change without invalidating comparisons when its scan semantics remain compatible; a changed or one-sided semantics version becomes a comparison limitation and suppresses scope-dependent alerts. Two legacy snapshots without this metadata remain mutually comparable under the older rules. Markdown output displays at most 20 items per long change list and points to JSON for the complete data. A stable non-empty `--scope-id` lets equivalent checkouts at different absolute roots compare safely. When an older snapshot may contain only the legacy top-20 large-file list, the comparer reports a limitation and suppresses unreliable large-file addition/removal alerts.

Run `python scripts/collect_repo_signals.py --help` or `python scripts/compare_repo_signals.py --help` for all options.

## GitHub Actions

Use the repository directly as a composite Action. Pin a release tag or commit SHA in production workflows:

```yaml
- uses: 1838904818/audit-repo@v1.8.0
  id: audit
  with:
    scan-mode: tracked
    scope-id: whole-repository
    output-dir: ${{ runner.temp }}/audit-repo
```

The Action requires Python 3.10 or newer on the runner and does not install project dependencies. Its outputs include `snapshot`, `report`, `comparison`, `sarif`, `attention-count`, `comparable`, `tool-version`, and `scan-semantics-version`; callers can upload reports or record provenance without parsing the snapshot.

For a checked-in baseline, enable both policy gates:

```yaml
- uses: 1838904818/audit-repo@v1.8.0
  with:
    baseline: .github/audit-baseline.json
    scan-mode: tracked
    scope-id: whole-repository
    fail-on-attention: "true"
    require-comparable: "true"
```

`include-paths`, `exclude-paths`, and `exclude-dirs` accept newline-separated values. A run without `baseline` is collection-only, so comparison gates do not apply.

## What the audit covers

| Area | Example signals |
| --- | --- |
| Repository state | Branch, clean or dirty worktree, tracked file count |
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
python scripts/package_skill.py --version v1.2.3 --output-dir dist
```

CI exercises Markdown output, JSON output, snapshot comparison, repository contracts, the composite Action, and deterministic packaging across Linux, Windows, and macOS. It covers every supported Python minor version from 3.10 through 3.14; release tags verify the minimum and latest versions on all three operating systems before publishing assets.

## License

[MIT](LICENSE)
