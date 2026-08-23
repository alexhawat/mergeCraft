"""Unit tests for Harbor MergecraftReviewAgent helpers (issue #30, Batch B)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip(
    "harbor.agents.installed.base",
    reason="harbor extra required (uv sync --extra harbor)",
)

from mergecraft.harbor.agent import MergecraftReviewAgent, _resolve_patch_path
from mergecraft.pins import action_pin_minimal

_HARBOR_AGENT_MODULE = "mergecraft.harbor.agent"


def _reload_harbor_agent_module() -> Any:
    """Drop cached ``mergecraft.harbor.agent`` so import-time behaviour is observable."""
    for name in list(sys.modules):
        if name == _HARBOR_AGENT_MODULE or name.startswith(f"{_HARBOR_AGENT_MODULE}."):
            del sys.modules[name]
    return importlib.import_module(_HARBOR_AGENT_MODULE)


def test_default_install_ref_pins_a_release_tag_not_a_moving_branch() -> None:
    resolved = action_pin_minimal()
    assert resolved.startswith("v"), (
        f"action_pin_minimal()={resolved!r} must pin a release tag "
        "(e.g. 'v0.1.0'), not a moving branch name like 'pre-0.0.1' — a "
        "Harbor install with no MERGECRAFT_INSTALL_REF override should not "
        "silently drift onto trunk."
    )


def test_import_harbor_agent_does_not_resolve_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing harbor.agent must not call ``action_pin_minimal()`` at module load."""

    def _raise_pin() -> str:
        raise RuntimeError("pin load must not run at import time")

    monkeypatch.setattr("mergecraft.pins.action_pin_minimal", _raise_pin)
    module = _reload_harbor_agent_module()
    assert module.MergecraftReviewAgent is not None


@pytest.mark.asyncio
async def test_install_resolves_default_ref_via_action_pin_minimal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``install()`` must resolve the default ref via ``action_pin_minimal()`` when unset."""
    calls: list[str] = []

    def _tracking_pin() -> str:
        calls.append("called")
        return "v0.1.0a1"

    monkeypatch.setattr("mergecraft.pins.action_pin_minimal", _tracking_pin)
    agent_mod = _reload_harbor_agent_module()
    calls.clear()

    agent = agent_mod.MergecraftReviewAgent(logs_dir=tmp_path)

    async def _noop_exec(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(agent, "exec_as_root", _noop_exec)
    monkeypatch.setattr(agent, "exec_as_agent", _noop_exec)

    class _FakeEnvironment:
        pass

    await agent.install(_FakeEnvironment())
    assert calls, "install() must call action_pin_minimal() when MERGECRAFT_INSTALL_REF is unset"


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
