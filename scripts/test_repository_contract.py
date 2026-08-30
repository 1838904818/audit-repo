#!/usr/bin/env python3
"""Repository-level contract tests for the published Skill."""

from __future__ import annotations

import re
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

    def test_release_workflow_validates_assets_and_is_rerunnable(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("Exercise packaged Skill", workflow)
        self.assertIn("gh release download", workflow)
        self.assertIn("cmp ", workflow)
        self.assertNotIn("--clobber", workflow)

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
