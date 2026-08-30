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

    def test_readme_package_example_matches_runtime_version(self) -> None:
        collector = (ROOT / "scripts" / "collect_repo_signals.py").read_text(encoding="utf-8")
        version_match = re.search(r'(?m)^TOOL_VERSION = "([^"]+)"\s*$', collector)
        self.assertIsNotNone(version_match)
        version = version_match.group(1) if version_match else ""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"python scripts/package_skill.py --version v{version} --output-dir dist", readme)

    def test_actions_are_pinned_to_commit_shas(self) -> None:
        for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            action_refs = re.findall(r"(?m)^\s*- uses:\s+([^\s#]+)", workflow)
            self.assertTrue(action_refs, f"no action references found in {relative}")
            for action_ref in action_refs:
                self.assertRegex(action_ref, r"^[^@]+@[0-9a-f]{40}$")

    def test_composite_action_exposes_expected_contract(self) -> None:
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertIn("using: composite", action)
        self.assertIn("scripts/check_repo.py", action)
        for name in (
            "snapshot", "report", "comparison", "sarif", "attention-count", "comparable",
            "tool-version", "scan-semantics-version",
        ):
            self.assertRegex(action, rf"(?m)^  {re.escape(name)}:\s*$")
        self.assertRegex(action, r'(?ms)^  scope-id:\s*\n.*?^    default: ""\s*$')
        self.assertRegex(action, r'(?ms)^  output-dir:\s*\n.*?^    default: ""\s*$')
        self.assertIn('if [[ -n "$AUDIT_SCOPE_ID" ]]', action)
        self.assertIn('tempfile.mkdtemp(prefix="audit-repo-", dir=os.environ["RUNNER_TEMP"])', action)
        self.assertIn('AUDIT_OUTPUT_DIR="$(python -I -c', action)
        self.assertIn('python -I "$GITHUB_ACTION_PATH/scripts/check_repo.py"', action)
        self.assertIn('validate_boolean "fail-on-attention" "$AUDIT_FAIL_ON_ATTENTION"', action)
        self.assertIn('validate_boolean "require-comparable" "$AUDIT_REQUIRE_COMPARABLE"', action)
        self.assertIn("true|false) return 0", action)
        self.assertIn("A comparison gate requires a non-empty baseline", action)
        self.assertNotRegex(action, r'(?m)^\s*args=\([^\n]*--scope-id')

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
        self.assertEqual(ci.count("continue-on-error: true"), 5)
        self.assertEqual(ci.count("python -I - <<'PY'"), 11)
        self.assertNotIn("python - <<'PY'", ci)
        for step_id in (
            "attention_gate", "comparable_gate", "missing_baseline_gate",
            "invalid_boolean", "managed_output_collision",
        ):
            self.assertIn(f"STEP_OUTCOME: ${{{{ steps.{step_id}.outcome }}}}", ci)
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
