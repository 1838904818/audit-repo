#!/usr/bin/env python3
"""Repository-level contract tests for the published Skill."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_skill_frontmatter_and_interface_metadata(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", skill, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md needs YAML frontmatter")
        frontmatter = match.group(1) if match else ""
        self.assertRegex(frontmatter, r"(?m)^name:\s*audit-repo\s*$")
        description = re.search(r"(?m)^description:\s*(.+)$", frontmatter)
        self.assertIsNotNone(description)
        self.assertGreater(len(description.group(1).strip()) if description else 0, 40)

        interface = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(interface, r'(?m)^\s*display_name:\s*"Audit Repo"\s*$')
        self.assertRegex(interface, r'(?m)^\s*short_description:\s*"[^\"]{25,100}"\s*$')
        self.assertRegex(interface, r'(?m)^\s*default_prompt:\s*"[^\"]*\$audit-repo[^\"]*"\s*$')

    def test_local_markdown_links_exist(self) -> None:
        for source_name in ("README.md", "SKILL.md"):
            source = ROOT / source_name
            text = source.read_text(encoding="utf-8")
            targets = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)
            for target in targets:
                target = target.strip().strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                local = unquote(target.split("#", 1)[0])
                self.assertTrue((ROOT / local).exists(), f"broken local link in {source_name}: {target}")

    def test_readme_uses_current_skill_install_location(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("$HOME/.agents/skills", readme)
        self.assertIn("$skill-installer", readme)
        self.assertNotIn(".codex}/skills", readme)
        self.assertNotIn(".codex/skills", readme)
        self.assertNotIn(".codex\\skills", readme)

    def test_required_public_files_exist(self) -> None:
        for relative in (
            "README.md",
            "action.yml",
            "SKILL.md",
            "CHANGELOG.md",
            "LICENSE",
            ".gitattributes",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "agents/openai.yaml",
            ".github/CODEOWNERS",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
        ):
            self.assertTrue((ROOT / relative).is_file(), f"missing required file: {relative}")

    def test_readme_contains_valid_chinese_quick_start(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("中文快速开始", readme)
        self.assertIn("使用 $audit-repo 审查当前仓库", readme)
        for mojibake_marker in ("涓枃", "锛", "€"):
            self.assertNotIn(mojibake_marker, readme)

    def test_public_examples_and_changelog_match_runtime_version(self) -> None:
        collector = (ROOT / "scripts" / "collect_repo_signals.py").read_text(encoding="utf-8")
        version_match = re.search(r'(?m)^TOOL_VERSION = "([^"]+)"\s*$', collector)
        self.assertIsNotNone(version_match)
        version = version_match.group(1) if version_match else ""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertIn(f"python scripts/package_skill.py --version v{version} --output-dir dist", readme)
        action_versions = re.findall(r"1838904818/audit-repo@v(\d+\.\d+\.\d+)", readme)
        self.assertTrue(action_versions)
        self.assertEqual(set(action_versions), {version})
        self.assertRegex(changelog, rf"(?s)\A# Changelog\n\n.*?\n## \[{re.escape(version)}\] - ")
        changelog_versions = re.findall(r"(?m)^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - ", changelog)
        self.assertGreaterEqual(len(changelog_versions), 2)
        self.assertEqual(changelog_versions[0], version)
        previous_version = changelog_versions[1]
        self.assertIn(
            f"[{version}]: https://github.com/1838904818/audit-repo/compare/v{previous_version}...v{version}",
            changelog,
        )
        self.assertIn("--baseline-sha256", readme)
        self.assertIn("--baseline-sha256", skill)
        self.assertIn("--baseline-sha256", changelog)
        self.assertRegex(action, r"(?m)^  baseline-sha256:\s*$")

    def test_actions_are_pinned_to_commit_shas(self) -> None:
        for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            action_refs = re.findall(r"(?m)^\s*- uses:\s+([^\s#]+)", workflow)
            self.assertTrue(action_refs, f"no action references found in {relative}")
            for action_ref in action_refs:
                self.assertRegex(action_ref, r"^[^@]+@[0-9a-f]{40}$")

    def test_composite_action_exposes_expected_contract(self) -> None:
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "check_repo.py").read_text(encoding="utf-8")
        self.assertIn("using: composite", action)
        self.assertIn("scripts/check_repo.py", action)
        for name in (
            "snapshot", "report", "comparison", "sarif", "attention-count", "comparable",
            "tool-version", "scan-semantics-version",
        ):
            self.assertRegex(action, rf"(?m)^  {re.escape(name)}:\s*$")
        self.assertRegex(action, r'(?ms)^  scope-id:\s*\n.*?^    default: ""\s*$')
        self.assertRegex(action, r'(?ms)^  output-dir:\s*\n.*?^    default: ""\s*$')
        self.assertRegex(action, r'(?ms)^  baseline-sha256:\s*\n.*?^    default: ""\s*$')
        self.assertIn('if [[ -n "$AUDIT_SCOPE_ID" ]]', action)
        self.assertIn('args+=("--temporary-output-parent=$RUNNER_TEMP")', action)
        self.assertNotIn("tempfile.mkdtemp", action)
        self.assertNotIn('AUDIT_OUTPUT_DIR="$(python', action)
        self.assertIn('python -I "$GITHUB_ACTION_PATH/scripts/check_repo.py"', action)
        self.assertIn('validate_boolean "fail-on-attention" "$AUDIT_FAIL_ON_ATTENTION"', action)
        self.assertIn('validate_boolean "require-comparable" "$AUDIT_REQUIRE_COMPARABLE"', action)
        self.assertIn("true|false) return 0", action)
        self.assertIn("A comparison gate requires a non-empty baseline", action)
        self.assertIn("baseline-sha256 requires a non-empty baseline", action)
        self.assertIn("baseline-sha256 must be exactly 64 hexadecimal characters", action)
        self.assertIn('args+=("--baseline-sha256=$AUDIT_BASELINE_SHA256")', action)
        self.assertIn('args+=(-- "$AUDIT_PATH")', action)
        self.assertNotRegex(action, r'(?m)^\s*args=\([^\n]*--scope-id')
        self.assertIn('baseline_bytes = comparer.read_snapshot_file_bytes(path)', runner)
        self.assertIn('hashlib.sha256(baseline_bytes).hexdigest()', runner)
        self.assertIn('comparer.load_snapshot_bytes(baseline_bytes, path)', runner)
        self.assertIn('comparer.load_snapshot_bytes(completed.stdout, Path("<collector stdout>"))', runner)
        self.assertNotIn("comparer.load_snapshot(snapshot)", runner)
        self.assertIn('result = comparer.compare(baseline_data, snapshot_data)', runner)
        self.assertNotIn('COMPARER =', runner)
        self.assertLess(runner.index("baseline_data = load_baseline"), runner.index("tempfile.mkdtemp"))

    def test_python_isolated_mode_ignores_checkout_module_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marker = root / "shadow-imported"
            root.joinpath("tempfile.py").write_text(
                "from pathlib import Path\nPath('shadow-imported').write_text('unsafe')\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", "import tempfile; assert hasattr(tempfile, 'mkdtemp')"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())

    def test_release_workflow_validates_assets_and_is_rerunnable(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("Exercise packaged Skill", workflow)
        self.assertIn("group: release-${{ github.repository }}-${{ github.ref }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        provenance_start = workflow.index("  provenance:\n")
        verify_start = workflow.index("  verify:\n")
        provenance = workflow[provenance_start:verify_start]
        self.assertLess(provenance_start, verify_start)
        self.assertIn("contents: read", provenance)
        self.assertNotIn("uses:", provenance)
        self.assertNotIn("actions/checkout", provenance)
        self.assertNotIn("scripts/", provenance)
        self.assertRegex(workflow, r"(?m)^  verify:\n(?:.*\n){0,3}    needs: provenance$")
        package_start = workflow.index("  package:\n")
        publish_start = workflow.index("  publish:\n")
        package = workflow[package_start:publish_start]
        publish = workflow[publish_start:]
        self.assertIn("needs: verify", package)
        self.assertNotIn("actions/checkout", publish)
        self.assertNotIn("git fetch", publish)
        self.assertIn("Revalidate release ref before publishing", publish)
        self.assertIn("tag-ref-object-sha: ${{ steps.provenance.outputs.tag-ref-object-sha }}", provenance)
        self.assertIn("id: provenance", provenance)
        self.assertIn('printf \'tag-ref-object-sha=%s\\n\'', provenance)
        self.assertRegex(publish, r"(?m)^    needs:\n      - package\n      - provenance$")
        self.assertIn('EXPECTED_TAG_OBJECT_SHA: ${{ needs.provenance.outputs.tag-ref-object-sha }}', publish)
        self.assertIn('repos/${GITHUB_REPOSITORY}/git/ref/tags/${TAG_PATH}', publish)
        self.assertIn('[[ "${TAG_OBJECT_SHA}" != "${EXPECTED_TAG_OBJECT_SHA}" ]]', publish)
        self.assertIn("Revalidate release provenance after asset verification", publish)
        self.assertIn('repos/${GITHUB_REPOSITORY}/git/ref/heads/${DEFAULT_BRANCH_PATH}', publish)
        self.assertIn('compare/${EXPECTED_SHA}...${DEFAULT_SHA}', publish)
        self.assertIn('git/ref/tags/${TAG_PATH}', provenance)
        self.assertIn('git/tags/${OBJECT_SHA}', provenance)
        self.assertIn('"${OBJECT_SHA}" != "${EXPECTED_SHA}"', provenance)
        self.assertIn('compare/${EXPECTED_SHA}...${DEFAULT_SHA}', provenance)
        self.assertIn('"${COMPARE_STATUS}" != "identical"', provenance)
        self.assertIn('"${COMPARE_STATUS}" != "ahead"', provenance)
        self.assertIn('--target "${GITHUB_SHA}"', workflow)
        self.assertEqual(workflow.count('gh release create "${GITHUB_REF_NAME}"'), 1)
        self.assertIn('"dist/audit-repo-${GITHUB_REF_NAME}.zip" \\', workflow)
        self.assertIn('"dist/audit-repo-${GITHUB_REF_NAME}.zip.sha256" \\', workflow)
        self.assertEqual(workflow.count('gh release download "${EXPECTED_TAG}"'), 2)
        self.assertIn('--pattern "${EXPECTED_ZIP}"', workflow)
        self.assertIn('--pattern "${EXPECTED_CHECKSUM}"', workflow)
        self.assertIn('release.get("tag_name") != expected_tag', workflow)
        self.assertIn('release.get("draft") is not False', workflow)
        self.assertIn('release.get("prerelease") is not False', workflow)
        self.assertIn('target_commitish = release.get("target_commitish")', workflow)
        self.assertIn('not isinstance(target_commitish, str) or not target_commitish', workflow)
        self.assertIn('asset.get("state") != "uploaded"', workflow)
        self.assertIn("len(names) != 2 or set(names) != expected_assets", workflow)
        self.assertIn("Existing release found; leaving it unchanged.", workflow)
        self.assertIn('gh api --paginate --slurp \\', workflow)
        self.assertIn('releases?per_page=100', workflow)
        self.assertIn('A draft Release already exists for tag', workflow)
        self.assertIn('refusing to mutate it', workflow)
        self.assertIn('if [[ "${RELEASE_STATE}" == "existing" ]]', workflow)
        self.assertIn('elif [[ "${RELEASE_STATE}" == "absent" ]]', workflow)
        self.assertEqual(workflow.count('releases/tags/${EXPECTED_TAG}'), 1)
        self.assertIn('cmp "dist/${EXPECTED_ZIP}"', workflow)
        self.assertIn('cmp "dist/${EXPECTED_CHECKSUM}"', workflow)
        for forbidden in (
            "dist/*", "--clobber", "gh release edit", "gh release upload", "gh release delete",
            'grep -Fq "HTTP 404"',
            'repos/${GITHUB_REPOSITORY}/commits/${GITHUB_REF_NAME}',
            'repos/${GITHUB_REPOSITORY}/commits/${TAG_PATH}',
            'repos/${GITHUB_REPOSITORY}/commits/${DEFAULT_BRANCH_PATH}',
        ):
            self.assertNotIn(forbidden, workflow)

    def test_ci_exercises_action_policy_fail_closed_paths(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("action-policy-e2e:", ci)
        self.assertIn("audit repo action fixture", ci)
        self.assertIn("id: leading_hyphen_inputs", ci)
        self.assertIn("scope-id: --scope:action-e2e", ci)
        self.assertIn('snapshot["include_path_patterns"] == ["*", "--include-probe/**"]', ci)
        self.assertIn('snapshot["excluded_directory_names"] == ["--cache"]', ci)
        expected_failure_steps = (
            "attention_gate", "comparable_gate", "missing_baseline_gate",
            "digest_without_baseline", "malformed_digest", "digest_mismatch",
            "digest_mismatch_default", "duplicate_root_explicit", "duplicate_root_default",
            "oversized_baseline_explicit", "oversized_baseline_default",
            "invalid_max_files_explicit",
            "invalid_large_file_explicit", "invalid_include_explicit",
            "invalid_exclude_explicit", "invalid_exclude_dirs_explicit", "invalid_scope_explicit",
            "non_git_tracked_explicit", "invalid_max_files_default",
            "invalid_exclude_dirs_default", "missing_root_default", "invalid_boolean",
            "managed_output_collision",
        )
        for step_id in expected_failure_steps:
            self.assertEqual(ci.count(f"id: {step_id}\n"), 1)
            self.assertRegex(
                ci,
                rf"(?m)^        id: {re.escape(step_id)}\n        continue-on-error: true$",
            )
        isolated_heredocs = ci.count("python -I - <<'PY'")
        self.assertGreater(isolated_heredocs, 0)
        self.assertEqual(isolated_heredocs, ci.count("<<'PY'"))
        self.assertNotIn("python - <<'PY'", ci)
        for step_id in (
            "attention_gate", "comparable_gate", "missing_baseline_gate",
            "invalid_boolean", "managed_output_collision",
        ):
            self.assertIn(f"STEP_OUTCOME: ${{{{ steps.{step_id}.outcome }}}}", ci)
        for environment_name, step_id in (
            ("MISSING_OUTCOME", "digest_without_baseline"),
            ("MALFORMED_OUTCOME", "malformed_digest"),
            ("MISMATCH_OUTCOME", "digest_mismatch"),
            ("DEFAULT_MISMATCH_OUTCOME", "digest_mismatch_default"),
            ("DUPLICATE_EXPLICIT_OUTCOME", "duplicate_root_explicit"),
            ("DUPLICATE_DEFAULT_OUTCOME", "duplicate_root_default"),
            ("OVERSIZED_EXPLICIT_OUTCOME", "oversized_baseline_explicit"),
            ("OVERSIZED_DEFAULT_OUTCOME", "oversized_baseline_default"),
        ):
            self.assertIn(f"{environment_name}: ${{{{ steps.{step_id}.outcome }}}}", ci)
            outputs_name = environment_name.replace("_OUTCOME", "_OUTPUTS")
            self.assertIn(f"{outputs_name}: ${{{{ toJSON(steps.{step_id}.outputs) }}}}", ci)
        for step_id in expected_failure_steps[11:21]:
            self.assertIn(f"steps.{step_id}.outcome", ci)
            self.assertIn(f"toJSON(steps.{step_id}.outputs)", ci)
        self.assertIn('default_parent.joinpath("invalid-collection-before.json")', ci)
        self.assertEqual(
            ci.count("baseline-sha256: ${{ steps.baseline_digest.outputs.sha256 }}"), 4,
        )
        self.assertEqual(ci.count('baseline-sha256: "' + "0" * 64 + '"'), 2)
        self.assertIn('default_parent.joinpath("digest-before.json")', ci)
        self.assertEqual(
            ci.count("baseline-sha256: ${{ steps.duplicate_root_seed.outputs.sha256 }}"), 2,
        )
        self.assertEqual(ci.count("id: duplicate_root_seed\n"), 1)
        self.assertIn('assert [name for name, _ in top_level_pairs].count("root") == 2', ci)
        self.assertIn("hashlib.sha256(ambiguous_bytes).hexdigest()", ci)
        self.assertIn('default_parent.joinpath("duplicate-key-before.json")', ci)

        def action_step(step_id: str) -> str:
            match = re.search(
                rf"(?ms)^      - name: [^\n]+\n        id: {re.escape(step_id)}\n"
                rf".*?(?=^      - name: |\Z)",
                ci,
            )
            self.assertIsNotNone(match, f"missing Action step block: {step_id}")
            return match.group(0) if match else ""

        duplicate_explicit = action_step("duplicate_root_explicit")
        duplicate_default = action_step("duplicate_root_default")
        self.assertIn("output-dir: ${{ runner.temp }}/audit repo duplicate root output", duplicate_explicit)
        self.assertNotIn("output-dir:", duplicate_default)

        oversized_explicit = action_step("oversized_baseline_explicit")
        oversized_default = action_step("oversized_baseline_default")
        self.assertIn(
            "output-dir: ${{ runner.temp }}/audit repo oversized baseline output",
            oversized_explicit,
        )
        self.assertNotIn("output-dir:", oversized_default)
        oversized_baseline = (
            "baseline: ${{ runner.temp }}/audit repo oversized external baseline.json"
        )
        self.assertIn(oversized_baseline, oversized_explicit)
        self.assertIn(oversized_baseline, oversized_default)
        self.assertNotIn("baseline-sha256:", oversized_explicit)
        self.assertNotIn("baseline-sha256:", oversized_default)

        verification = re.search(
            r"(?ms)^      - name: Verify duplicate-key rejection preserves every Action output\n"
            r".*?(?=^      - name: |\Z)",
            ci,
        )
        self.assertIsNotNone(verification, "missing duplicate-key verification step")
        verification_block = verification.group(0) if verification else ""
        for assertion in (
            'assert all(outputs.get(name) in ("", None) for name in public_outputs)',
            'assert hashlib.sha256(ambiguous_bytes).hexdigest() == os.environ["EXPECTED_SHA256"]',
            'assert tree_state(output_dir) == before["explicit"]',
            'assert after == before["default_entries"]',
        ):
            self.assertIn(assertion, verification_block)

        oversized_seed = re.search(
            r"(?ms)^      - name: Seed a sparse oversized external baseline and preserved output tree\n"
            r".*?(?=^      - name: |\Z)",
            ci,
        )
        self.assertIsNotNone(oversized_seed, "missing oversized-baseline seed step")
        oversized_seed_block = oversized_seed.group(0) if oversized_seed else ""
        self.assertIn("stream.truncate(64 * 1024 * 1024 + 1)", oversized_seed_block)
        self.assertIn(
            "assert oversized_baseline.stat().st_size == 64 * 1024 * 1024 + 1",
            oversized_seed_block,
        )
        self.assertEqual(
            oversized_seed_block.count('output_dir.joinpath("keep").mkdir()'), 1,
        )
        for seeded_name in (
            "snapshot.json", "report.md", "comparison.json",
            "comparison.sarif", "keep/sentinel.bin",
        ):
            self.assertEqual(
                oversized_seed_block.count(f'"{seeded_name}"'), 1,
                f"oversized-baseline seed must include exactly one {seeded_name}",
            )
        self.assertIn("output_dir.joinpath(name).write_bytes(", oversized_seed_block)
        self.assertNotIn("oversized_baseline.read_bytes", oversized_seed_block)
        self.assertNotIn("oversized_baseline.read_text", oversized_seed_block)
        self.assertNotIn("hashlib", oversized_seed_block)

        oversized_verification = re.search(
            r"(?ms)^      - name: Verify oversized-baseline rejection preserves every Action output\n"
            r".*?(?=^      - name: |\Z)",
            ci,
        )
        self.assertIsNotNone(oversized_verification, "missing oversized-baseline verification step")
        oversized_verification_block = oversized_verification.group(0) if oversized_verification else ""
        for assertion in (
            'assert all(outputs.get(name) in ("", None) for name in public_outputs)',
            "assert oversized_baseline.stat().st_size == 64 * 1024 * 1024 + 1",
            'assert tree_state(output_dir) == before["explicit"]',
            'assert after == before["default_entries"]',
        ):
            self.assertIn(assertion, oversized_verification_block)
        self.assertNotIn("oversized_baseline.read_bytes", oversized_verification_block)
        self.assertNotIn("oversized_baseline.read_text", oversized_verification_block)
        self.assertNotIn("hashlib", oversized_verification_block)
        self.assertIn('default_parent.joinpath("oversized-baseline-before.json")', ci)
        self.assertIn('fail-on-attention: "TRUE"', ci)
        self.assertIn('result["level"] == "warning"', ci)
        self.assertIn('result["level"] == "note"', ci)

    def test_ci_covers_supported_platforms_and_python_versions(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for operating_system in ("ubuntu-latest", "windows-latest", "macos-latest"):
            self.assertIn(operating_system, ci)
            self.assertIn(operating_system, release)
        for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
            self.assertIn(f'"{version}"', ci)
        self.assertIn('"3.10"', release)
        self.assertIn('"3.14"', release)


if __name__ == "__main__":
    unittest.main()
