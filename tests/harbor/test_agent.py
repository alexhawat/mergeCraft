"""Unit tests for Harbor MergecraftReviewAgent helpers (issue #30, Batch B)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("harbor")

from mergecraft.harbor.agent import DEFAULT_INSTALL_REF, MergecraftReviewAgent, _resolve_patch_path


def test_default_install_ref_pins_a_release_tag_not_a_moving_branch() -> None:
    assert DEFAULT_INSTALL_REF.startswith("v"), (
        f"DEFAULT_INSTALL_REF={DEFAULT_INSTALL_REF!r} must pin a release tag "
        "(e.g. 'v0.1.0'), not a moving branch name like 'pre-0.0.1' — a "
        "Harbor install with no MERGECRAFT_INSTALL_REF override should not "
        "silently drift onto trunk."
    )


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
