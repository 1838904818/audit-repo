# Native check selection

Use declared scripts and checked-in wrappers before the examples below, but treat all of them as arbitrary code. Apply the trust boundary in `SKILL.md`, inspect the exact command and immediate call chain, and remain static-only for untrusted repositories unless execution is explicitly authorized and isolated. Run only checks supported by the repository, and separate missing tooling from actual failures.

## Guardrails

- Prefer the package manager matching the checked-in lockfile.
- Prefer wrapper scripts such as `gradlew` or `mvnw` over globally installed tools.
- Avoid commands that auto-fix, publish, deploy, migrate, or start persistent services.
- Warn before a command that may download dependencies when network access is not already expected.
- Bound slow checks and capture the exact command and exit result.

## Common ecosystems

| Signal | Candidate checks |
| --- | --- |
| `package.json` | Run declared `test`, `lint`, `typecheck`, or `build` scripts with the matching npm, pnpm, or Yarn lockfile. |
| `pyproject.toml`, `pytest.ini` | Use an existing environment; run configured tools such as `pytest`, `ruff check`, or `mypy`. |
| `Pipfile` | Use an existing Pipenv environment and declared scripts; avoid an implicit install or lock refresh. |
| `go.mod` | Consider `go test ./...` and `go vet ./...`; note that module resolution may use the network. |
| `Cargo.toml` | Prefer `cargo test --locked` and `cargo check --locked` when `Cargo.lock` exists. |
| `pom.xml`, `mvnw` | Prefer `./mvnw test` or the documented verification goal. |
| `build.gradle*`, `gradlew` | Prefer `./gradlew test` or the repository's declared check task. |
| `.sln`, `.csproj` | Consider `dotnet test --no-restore` when dependencies are already restored. |
| `Package.swift` | Use the repository-documented SwiftPM check only when the toolchain and resolved dependencies are already available without a network fetch. |
| `package.json`, `bun.lock` | Prefer declared Bun scripts only when Bun and the existing dependency tree are already available. |
| `Gemfile` | Prefer declared Bundler/Rake tasks; use `bundle exec` for repository-pinned tools. |
| `composer.json` | Run declared Composer scripts with the checked-in lockfile and existing vendor tree. |
| `Makefile`, `justfile`, `Taskfile*` | Inspect targets first; names do not guarantee that a target is read-only. |

Do not run every candidate. Select the smallest set that tests the repository's core claim and the risks identified during inspection.
