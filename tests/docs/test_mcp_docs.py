"""MP1.7 — public MCP install/docs contracts."""

from __future__ import annotations

import re

import yaml

from tests.ci.workflow_support import REPO_ROOT
from tests.mcp.public_mcp_support import PUBLIC_TOOL_NAMES

_MCP_PAGE = REPO_ROOT / "docs" / "mcp.md"
_MCP_TOOLS_PAGE = REPO_ROOT / "docs" / "mcp-tools.md"
_README = REPO_ROOT / "README.md"
_SKILL = REPO_ROOT / "skills" / "mergecraft" / "SKILL.md"
_MANIFEST = REPO_ROOT / "docs" / "manifest.yaml"


def _read(path: object) -> str:
    from pathlib import Path

    file_path = Path(path)
    assert file_path.is_file(), f"missing {file_path.relative_to(REPO_ROOT)} (MP7)"
    return file_path.read_text(encoding="utf-8")


def _manifest_paths() -> set[str]:
    data = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    docs = data.get("pages") or data.get("docs")
    assert isinstance(docs, list)
    paths: set[str] = set()
    for row in docs:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            paths.add(row["path"])
    return paths


def test_mcp_page_exists_and_is_manifested() -> None:
    assert _MCP_PAGE.is_file()
    assert "docs/mcp.md" in _manifest_paths()


def test_mcp_page_stdio_auth_mentions_local_scope() -> None:
    text = _read(_MCP_PAGE)
    assert "--scope local" in text or "--scope both" in text


def test_mcp_page_answers_three_questions() -> None:
    text = _read(_MCP_PAGE).lower()
    for heading in (
        "what",
        "connect",
        "never",
    ):
        assert heading in text, f"docs/mcp.md must answer '{heading}'"


def test_mcp_page_has_separate_openai_and_anthropic_sections() -> None:
    text = _read(_MCP_PAGE)
    assert re.search(r"openai|chatgpt", text, re.IGNORECASE)
    assert re.search(r"anthropic|claude", text, re.IGNORECASE)
    openai_pos = text.lower().find("openai")
    chatgpt_pos = text.lower().find("chatgpt")
    anthropic_pos = text.lower().find("anthropic")
    claude_pos = text.lower().find("claude desktop")
    assert max(openai_pos, chatgpt_pos) >= 0
    assert max(anthropic_pos, claude_pos) >= 0
    assert openai_pos != anthropic_pos or chatgpt_pos != claude_pos


def test_readme_agent_section_links_docs_mcp() -> None:
    text = _read(_README)
    agent_match = re.search(
        r"^##\s+.*(?:LLM|Agents?).*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    assert agent_match, "README needs an agent/LLM section"
    start = agent_match.start()
    rest = text[start:]
    next_heading = re.search(r"^##\s+", rest[len(agent_match.group(0)) :], re.MULTILINE)
    section = rest if next_heading is None else rest[: next_heading.start()]
    assert "docs/mcp.md" in section


def test_skill_mentions_stdio_public_and_keeps_runtime_http_bearer() -> None:
    text = _read(_SKILL)
    lowered = text.lower()
    assert "--role public" in lowered or "role public" in lowered
    assert "stdio" in lowered
    assert "bearer" in lowered
    assert "/mcp/reviewer" in lowered or "reviewer" in lowered


def test_generated_mcp_tools_page_matches_public_tool_names() -> None:
    text = _read(_MCP_TOOLS_PAGE)
    for name in PUBLIC_TOOL_NAMES:
        assert name in text


def test_readme_has_mcp_name_ownership_string() -> None:
    text = _read(_README)
    assert "mcp-name: io.github.alexhawat/mergecraft" in text
