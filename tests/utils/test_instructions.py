"""Instructions assembly tests (offline)."""

from __future__ import annotations

from mergecraft.config.settings import LearningsHeading, RepoInfo
from mergecraft.modes import Mode
from mergecraft.utils.instructions import (
    build_learnings_section,
    render_learnings_toc,
    resolve_instructions,
)


def test_render_learnings_toc() -> None:
    headings = [
        LearningsHeading.model_validate(
            {"depth": 2, "title": "Build", "startLine": 1, "endLine": 5}
        ),
        LearningsHeading.model_validate(
            {"depth": 3, "title": "Local", "startLine": 3, "endLine": 5}
        ),
    ]
    toc = render_learnings_toc(headings)
    assert "- Build (L1-L5)" in toc
    assert "  - Local (L3-L5)" in toc


def test_build_learnings_section_empty_path() -> None:
    assert build_learnings_section(file_path=None, headings=[]) == ""


def test_resolve_instructions_assembles_sections() -> None:
    repo = RepoInfo(owner="acme", name="widgets", data={"default_branch": "main"})
    modes = [Mode(name="Task", description="General-purpose tasks", prompt="do it")]
    payload = {
        "~mergecraft": True,
        "prompt": "say hello",
        "shell": "restricted",
        "push": "restricted",
        "event": {"trigger": "unknown", "title": "Hello", "is_pr": False},
        "model": "anthropic/claude-sonnet",
    }
    resolved = resolve_instructions(
        payload=payload,
        repo=repo,
        modes=modes,
        agent_id="opencode",
        learnings_file_path="/tmp/learnings.md",
        learnings_headings=[],
    )
    assert "YOUR TASK" in resolved.full
    assert "SYSTEM" in resolved.full
    assert "LEARNINGS" in resolved.full
    assert "RUNTIME" in resolved.full
    assert resolved.user == "say hello"
    assert "mergecraft" in resolved.system.lower() or "MCP" in resolved.system
    assert "say hello" in resolved.full
