"""Unit tests for Harbor MergecraftReviewAgent helpers (issue #30, Batch B)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("harbor")

from mergecraft.harbor.agent import MergecraftReviewAgent, _resolve_patch_path


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Apply task.patch to the repo", "task.patch"),
        ("Review changes.patch for security issues", "changes.patch"),
        ("Use diff.patch in the working tree", "diff.patch"),
        ("Check review.patch before scoring", "review.patch"),
        ("Patch at src/foo/bar.patch please", "src/foo/bar.patch"),
        ("No patch mentioned here", None),
    ],
)
def test_resolve_patch_path(instruction: str, expected: str | None) -> None:
    assert _resolve_patch_path(instruction) == expected


def test_build_run_env_forwards_explicit_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MERGECRAFT_MODEL", "from-env")
    monkeypatch.setenv("MERGECRAFT_CUSTOM", "passthrough")

    agent = MergecraftReviewAgent(logs_dir=Path("/tmp/logs"))
    env = agent._build_run_env()

    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert env["MERGECRAFT_MODEL"] == "from-env"
    assert env["MERGECRAFT_CUSTOM"] == "passthrough"


def test_build_run_env_model_name_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_MODEL", "from-env")

    agent = MergecraftReviewAgent(logs_dir=Path("/tmp/logs"), model_name="claude-sonnet-4")
    env = agent._build_run_env()

    assert env["MERGECRAFT_MODEL"] == "claude-sonnet-4"
