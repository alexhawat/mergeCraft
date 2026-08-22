"""RD3 — LLM-agent install surface contracts.

Pins ``AGENTS.md``, the consumer skill, plugin manifests, slash commands, Copilot
instructions, ``llms.txt``, and the README agent section.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import action_uses_pattern, git_ref_exists

AGENTS_MD = REPO_ROOT / "AGENTS.md"
SKILL_MD = REPO_ROOT / "skills" / "mergecraft" / "SKILL.md"
SKILLS_LOCK = REPO_ROOT / "skills-lock.json"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SETUP_CMD = REPO_ROOT / "commands" / "mergecraft-setup.md"
REVIEW_CMD = REPO_ROOT / "commands" / "mergecraft-review.md"
COPILOT_INSTRUCTIONS = REPO_ROOT / ".github" / "copilot-instructions.md"
LLMS_TXT = REPO_ROOT / "llms.txt"
README = REPO_ROOT / "README.md"
GITIGNORE = REPO_ROOT / ".gitignore"

_UNPINNED_INSTALL = 'uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"'
_VERSIONED_GIT_REF = re.compile(
    r"git\+https://github\.com/alexhawat/mergeCraft@([^\s\"')]+)",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(REPO_ROOT)} (RD3.2)"
    return path.read_text(encoding="utf-8")


def _assert_no_unresolvable_version_pins(text: str, *, label: str) -> None:
    assert "@pre-0.0.1" not in text, f"{label} must not teach @pre-0.0.1 (D11)"
    for match in _VERSIONED_GIT_REF.finditer(text):
        ref = match.group(1)
        if ref.startswith("v") and not git_ref_exists(ref):
            pytest.fail(f"{label} pins git+…@{ref} but tag {ref!r} does not exist (D11)")
    for match in action_uses_pattern.finditer(text):
        ref = match.group(1)
        if ref.startswith("v") and not git_ref_exists(ref):
            pytest.fail(f"{label} pins uses:…@{ref} but tag {ref!r} does not exist (D11)")


def _development_section(agents_text: str) -> str:
    match = re.search(
        r"^##\s+.*(?:Working on|Development|Contributing)[^\n]*\n(.*?)(?=^## |\Z)",
        agents_text,
        re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    assert match, "AGENTS.md needs a development/contributor section for this repo (RD3.2)"
    return match.group(1)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_agents_md_exists_and_teaches_review_not_diff_review_as_primary() -> None:
    text = _read(AGENTS_MD)
    assert "mergecraft review" in text, "AGENTS.md must teach mergecraft review as primary (D10)"
    assert "mergecraft init" in text, "AGENTS.md must document mergecraft init for consumer setup"
    if "diff-review" in text:
        assert "alias" in text.lower(), (
            "AGENTS.md must describe diff-review as a deprecated alias when mentioned (D10)"
        )


def test_agents_md_stops_on_interactive_auth() -> None:
    text = _read(AGENTS_MD).lower()
    assert "mergecraft auth" in text, "AGENTS.md must document mergecraft auth"
    assert "never" in text, "AGENTS.md must tell agents never to invent credentials"
    assert any(token in text for token in ("credential", "secret", "token")), (
        "AGENTS.md must warn about credential/secret handling before interactive auth"
    )


def test_agents_md_install_ref_resolves() -> None:
    text = _read(AGENTS_MD)
    assert _UNPINNED_INSTALL in text, "AGENTS.md must teach the unpinned uv tool install form (D11)"
    _assert_no_unresolvable_version_pins(text, label="AGENTS.md")


def test_agents_md_this_repo_uses_make() -> None:
    region = _development_section(_read(AGENTS_MD)).lower()
    assert "make lint" in region, "AGENTS.md contributor section must name make lint"
    assert "make test" in region, "AGENTS.md contributor section must name make test"


def test_skill_frontmatter() -> None:
    text = _read(SKILL_MD)
    assert re.search(r"^---\s*\n.*?^name:\s*mergecraft\s*$", text, re.MULTILINE | re.DOTALL), (
        "skills/mergecraft/SKILL.md must declare YAML frontmatter name: mergecraft"
    )
    assert re.search(r"^description:\s*.+$", text, re.MULTILINE), (
        "skills/mergecraft/SKILL.md must declare a description: field"
    )


def test_skill_lock_hash_matches() -> None:
    assert SKILL_MD.is_file(), f"missing {SKILL_MD.relative_to(REPO_ROOT)} (RD3.2)"
    lock = json.loads(SKILLS_LOCK.read_text(encoding="utf-8"))
    entry = lock.get("skills", {}).get("mergecraft")
    assert isinstance(entry, dict), "skills-lock.json must carry a mergecraft entry (RD3.2)"
    expected = _sha256_file(SKILL_MD)
    assert entry.get("computedHash") == expected, (
        "skills-lock.json mergecraft.computedHash must equal SHA-256 of SKILL.md (D17)"
    )


def test_plugin_manifests() -> None:
    plugin = json.loads(_read(PLUGIN_JSON))
    assert plugin.get("name") == "mergecraft", ".claude-plugin/plugin.json must name mergecraft"
    skills_ref = plugin.get("skills") or plugin.get("skill")
    assert skills_ref == "./skills/mergecraft", (
        ".claude-plugin/plugin.json must point skills at ./skills/mergecraft (D8)"
    )
    assert MARKETPLACE_JSON.is_file(), f"missing {MARKETPLACE_JSON.relative_to(REPO_ROOT)} (RD3.2)"


def test_slash_commands_exist() -> None:
    assert SETUP_CMD.is_file(), f"missing {SETUP_CMD.relative_to(REPO_ROOT)} (RD3.2)"
    assert REVIEW_CMD.is_file(), f"missing {REVIEW_CMD.relative_to(REPO_ROOT)} (RD3.2)"


def test_copilot_instructions_point_at_agents_md() -> None:
    text = _read(COPILOT_INSTRUCTIONS)
    assert "AGENTS.md" in text, (
        ".github/copilot-instructions.md must point contributors/agents at AGENTS.md (D7)"
    )


_AGENT_SECTION_HEADING_RE = re.compile(
    r"^##\s+.*For LLM\s*/\s*Agents",
    re.MULTILINE | re.IGNORECASE,
)
_AGENT_SECTION_REGION_RE = re.compile(
    r"^##\s+.*For LLM\s*/\s*Agents[^\n]*\n(.*?)(?=^## |\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)


def _readme_agent_section_region(text: str) -> str | None:
    match = _AGENT_SECTION_REGION_RE.search(text)
    return match.group(1) if match else None


def _readme_h2_headings(text: str) -> list[str]:
    return [
        line[3:].strip()
        for line in text.splitlines()
        if line.startswith("## ") and not line.startswith("### ")
    ]


def test_readme_has_agent_section() -> None:
    text = read_text("README.md")
    assert _AGENT_SECTION_HEADING_RE.search(text), "README must ship ## For LLM / Agents (D2)"
    region = _readme_agent_section_region(text)
    assert region is not None, "README agent section must contain copy/paste prompts"
    assert "mergecraft init" in region, (
        "README agent prompts must mention mergecraft init for consumer setup"
    )


def test_agent_section_is_first_section() -> None:
    text = read_text("README.md")
    headings = _readme_h2_headings(text)
    assert headings, "README must contain at least one H2"
    first = headings[0]
    assert re.search(r"For LLM\s*/\s*Agents", first, re.IGNORECASE), (
        f"first H2 must be For LLM / Agents; got {first!r}"
    )


def test_agent_section_anchor_survives() -> None:
    text = read_text("README.md")
    assert 'id="for-agents"' in text or "id='for-agents'" in text, (
        'README must keep <span id="for-agents"> above the agent section (D2)'
    )
    llms = _read(LLMS_TXT)
    assert "README.md#for-agents" in llms, (
        "llms.txt must keep README.md#for-agents anchor link (D2)"
    )


def test_agent_prompts_are_fenced_not_quoted() -> None:
    text = read_text("README.md")
    region = _readme_agent_section_region(text)
    assert region is not None, "README agent section missing"
    prompts_region_match = re.search(
        r"###\s+One-line setup prompts[^\n]*\n(.*?)(?=\n### |\n## |\Z)",
        region,
        re.DOTALL,
    )
    assert prompts_region_match, "agent section must document one-line setup prompts"
    prompts_region = prompts_region_match.group(1)
    blockquote_prompts = re.findall(r"^>\s+", prompts_region, re.MULTILINE)
    fenced_blocks = re.findall(r"^```", prompts_region, re.MULTILINE)
    assert not blockquote_prompts, (
        "agent setup prompts must not use blockquotes — GitHub copy button needs fences"
    )
    assert fenced_blocks, "agent setup prompts must use fenced code blocks"


def test_readme_agent_badges() -> None:
    text = read_text("README.md")
    assert "skills/mergecraft/SKILL.md" in text, (
        "README must link or badge skills/mergecraft/SKILL.md (RD3.2)"
    )
    assert "llms.txt" in text, "README must link or badge llms.txt (RD3.2)"


def test_llms_txt_lists_required_urls() -> None:
    text = _read(LLMS_TXT)
    required = (
        "README.md",
        "AGENTS.md",
        "REVIEW-CHECKS.md",
        "docs/ANALYZERS.md",
        "skills/mergecraft/SKILL.md",
    )
    missing = [item for item in required if item not in text]
    assert not missing, f"llms.txt must list required paths: {missing}"


def test_claude_md_still_gitignored() -> None:
    """Pin, expected GREEN: tracked agent entry is AGENTS.md, not CLAUDE.md (D6)."""
    gitignore = GITIGNORE.read_text(encoding="utf-8")
    assert "CLAUDE.md" in gitignore, ".gitignore must ignore CLAUDE.md (D6)"
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "CLAUDE.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert tracked.returncode != 0, "CLAUDE.md must not be tracked (D6)"


def test_cursor_tree_still_gitignored() -> None:
    """Pin, expected GREEN: consumer skill replaces tracked .cursor/rules (D7)."""
    gitignore = GITIGNORE.read_text(encoding="utf-8")
    assert "/.cursor/" in gitignore, ".gitignore must ignore /.cursor/ (D7)"
    tracked = subprocess.run(
        ["git", "ls-files", ".cursor/rules/mergecraft.mdc"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.stdout.strip() == "", "no tracked .cursor/rules/mergecraft.mdc (D7)"


def test_no_tracked_dot_claude_rules() -> None:
    """Pin, expected GREEN: .claude/ stays a local operator tree (D7)."""
    tracked = subprocess.run(
        ["git", "ls-files", ".claude/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.stdout.strip() == "", "no tracked files under .claude/ (D7)"
