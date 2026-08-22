"""Unit tests for Harbor MergecraftReviewAgent helpers (issue #30, Batch B)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("harbor")

from mergecraft.harbor.agent import MergecraftReviewAgent, _resolve_patch_path

_HARBOR_AGENT_MODULE = "mergecraft.harbor.agent"


def _reload_harbor_agent_module() -> Any:
    """Drop cached ``mergecraft.harbor.agent`` so import-time behaviour is observable."""
    for name in list(sys.modules):
        if name == _HARBOR_AGENT_MODULE or name.startswith(f"{_HARBOR_AGENT_MODULE}."):
            del sys.modules[name]
    return importlib.import_module(_HARBOR_AGENT_MODULE)


def _resolved_default_install_ref(agent_module: Any | None = None) -> str:
    """Resolve the default Harbor install ref across eager and lazy pin layouts (D9)."""
    module = agent_module or importlib.import_module(_HARBOR_AGENT_MODULE)
    accessor = getattr(module, "_default_install_ref", None)
    if accessor is not None:
        resolved = accessor()
        return str(resolved)
    ref = module.DEFAULT_INSTALL_REF
    if isinstance(ref, str):
        return ref
    if callable(ref):
        return str(ref())
    msg = f"unexpected DEFAULT_INSTALL_REF type: {type(ref)!r}"
    raise TypeError(msg)


def test_default_install_ref_pins_a_release_tag_not_a_moving_branch() -> None:
    resolved = _resolved_default_install_ref()
    assert resolved.startswith("v"), (
        f"DEFAULT_INSTALL_REF={resolved!r} must pin a release tag "
        "(e.g. 'v0.1.0'), not a moving branch name like 'pre-0.0.1' — a "
        "Harbor install with no MERGECRAFT_INSTALL_REF override should not "
        "silently drift onto trunk."
    )


@pytest.mark.xfail(
    reason="green after W4: defer harbor pin from import (#403, D9)",
    strict=False,
)
def test_import_harbor_agent_does_not_resolve_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing harbor.agent must not call ``action_pin_minimal()`` at module load."""

    def _raise_pin() -> str:
        raise RuntimeError("pin load must not run at import time")

    monkeypatch.setattr("mergecraft.pins.action_pin_minimal", _raise_pin)
    module = _reload_harbor_agent_module()
    assert module.MergecraftReviewAgent is not None


@pytest.mark.xfail(
    reason="green after W4: lazy default install ref accessor (#403, D9)",
    strict=False,
)
def test_default_install_ref_accessor_calls_action_pin_minimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lazy accessor mirrors ``init_cmd._workflow_template`` — resolve pin on demand."""
    calls: list[str] = []

    def _tracking_pin() -> str:
        calls.append("called")
        return "v0.1.0a1"

    monkeypatch.setattr("mergecraft.pins.action_pin_minimal", _tracking_pin)
    agent_mod = _reload_harbor_agent_module()
    accessor = getattr(agent_mod, "_default_install_ref", None)
    assert accessor is not None, (
        "mergecraft.harbor.agent must expose _default_install_ref() "
        "(mirror init_cmd._workflow_template; D9)"
    )
    calls.clear()
    ref = accessor()
    assert ref.startswith("v"), f"unexpected install ref: {ref!r}"
    assert calls == ["called"], "lazy accessor must call action_pin_minimal()"


@pytest.mark.xfail(
    reason="green after W4: install resolves pin lazily (#403, D9)",
    strict=False,
)
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
