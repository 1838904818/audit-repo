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
- Compare two audit snapshots and surface meaningful changes over time.
- Flag high-confidence attention items such as newly detected sensitive filenames, lost CI or tests, and new large files.
- Keep secret values private: filename checks never read or print sensitive file contents.
- Support custom directory exclusions, file limits, and large-file thresholds.

The collector produces inventory signals, not automatic findings. The Skill tells Codex to verify context and evidence before assigning impact or priority.

## Install as a Codex Skill

The easiest option in Codex is to ask the built-in installer to install this repository:

```text
Use $skill-installer to install https://github.com/1838904818/audit-repo.
```

For an offline or version-pinned installation, download the `.zip` and matching `.sha256` file from the [latest release](https://github.com/1838904818/audit-repo/releases/latest). Verify the checksum, then extract the archive's top-level `audit-repo` directory into `$HOME/.agents/skills`. Release assets are built only after the full test matrix passes on Windows and Linux with Python 3.10 and 3.13.

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

Requires Python 3.10 or newer. The scripts use only the Python standard library.

Audit a repository:

```bash
python scripts/collect_repo_signals.py /path/to/repo --format markdown
```

Save a reusable JSON snapshot:

```bash
python scripts/collect_repo_signals.py /path/to/repo --format json --output before.json
```

Compare two snapshots:

```bash
python scripts/compare_repo_signals.py before.json after.json --format markdown
```

Use snapshot comparison in automation:

```bash
python scripts/compare_repo_signals.py before.json after.json --fail-on-attention
```

Comparison exit codes:

- `0`: comparison completed without attention items
- `1`: attention items found when `--fail-on-attention` is enabled
- `2`: invalid input or execution error

Run `python scripts/collect_repo_signals.py --help` or `python scripts/compare_repo_signals.py --help` for all options.

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
- [Contributing guide](https://github.com/1838904818/audit-repo/blob/main/CONTRIBUTING.md) for local validation and change expectations
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

扫描器不会读取或输出疑似密钥文件的内容。它提供的是待核实信号，最终问题等级应结合实际代码和项目用途判断。

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

CI exercises Markdown output, JSON output, snapshot comparison, repository contracts, and deterministic packaging on every push. Release tags additionally run the full cross-platform matrix before publishing assets.

## License

[MIT](LICENSE)
