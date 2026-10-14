"""``reviewer_p0_slug_from_config`` had no caller anywhere; the plain reader stays."""

from __future__ import annotations

from mergecraft.config.roster_unwired import reviewer_p0_slug

_RAW = {"agents": {"reviewer": {"modelChain": ["anthropic/claude-sonnet"]}}}


def test_reviewer_p0_slug_from_config_is_gone() -> None:
    """The zero-caller wrapper is deleted; the plain first-slug reader still works."""
    import mergecraft.config.roster_unwired as module

    assert "reviewer_p0_slug_from_config" not in module.__all__
    assert not hasattr(module, "reviewer_p0_slug_from_config")
    # Surviving surface: the direct reader still returns the first reviewer slug.
    assert reviewer_p0_slug(_RAW) == "anthropic/claude-sonnet"
