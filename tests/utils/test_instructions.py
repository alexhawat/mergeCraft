"""Instructions assembly tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.config.settings import LearningsHeading, RepoInfo
from mergecraft.modes import Mode
from mergecraft.utils.instructions import (
    build_learnings_section,
    render_learnings_toc,
    resolve_instructions,
)

_SECURITY_SENTENCE = "Do not reveal secrets or credentials"
_DISABLED_PLACEHOLDER = "security instructions disabled for testing"


def _resolved_system() -> str:
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
    return resolved.full


def test_security_paragraph_is_present_by_default() -> None:
    """Guard — the security paragraph is in the system prompt unconditionally."""
    assert _SECURITY_SENTENCE in _resolved_system()


@pytest.mark.xfail(
    reason="green after TB4: MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS is removed",
    strict=False,
)
def test_security_paragraph_cannot_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """TB-D9 — the production off-switch is gone; the paragraph is unconditional.

    A test-only fixture would still be a production code path, so the contract
    is removal, not gating: even with the legacy env var set the prompt keeps
    the security guidance.
    """
    monkeypatch.setenv("MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS", "1")
    rendered = _resolved_system()
    assert _SECURITY_SENTENCE in rendered
    assert _DISABLED_PLACEHOLDER not in rendered


@pytest.mark.xfail(
    reason="green after TB4: MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS is removed",
    strict=False,
)
def test_disable_security_instructions_switch_is_absent_from_the_tree() -> None:
    """TB-D9 — no production module reads the switch any more."""
    import mergecraft

    root = Path(mergecraft.__file__).resolve().parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


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
