"""#284 / D10: ``ignore_scripts`` follows trust, not only ``shell == disabled``.

``start_installation`` today sets ``PrepOptions.ignore_scripts`` from
``ctx.payload.shell == "disabled"`` only (``mcp/dependencies.py``). An
untrusted (PR-authored) tree with the default ``shell: restricted`` still
runs npm lifecycle scripts in the privileged Action process.

W3 must set ``ignore_scripts=True`` when ``trust_tier == "untrusted"`` **or**
``shell == "disabled"``. Trusted + ``restricted`` may still run scripts.
Node/Python prep adapters already honor the flag — do not change them.

``tests/mcp/test_dependencies_python_skip.py`` pins the ``shell: disabled``
Python-skip path and is left untouched (W1.2).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.prep import run_prep_phase
from mergecraft.prep.types import PrepOptions, PrepResult
from mergecraft.utils.github import GitHubClient

_SENTINEL_NAME = "SENTINEL"
_XFAIL_TRUST = pytest.mark.xfail(
    reason="green after W3: ignore_scripts follows trust",
    strict=False,
)

Shell = Literal["disabled", "restricted", "enabled"]
TrustTier = Literal["trusted", "untrusted"]


def _write_postinstall_fixture(repo: Path) -> Path:
    """Write a ``package.json`` whose ``postinstall`` creates ``SENTINEL``."""
    sentinel = repo / _SENTINEL_NAME
    package_json = {
        "name": "ignore-scripts-trust-fixture",
        "version": "0.0.0",
        "private": True,
        "scripts": {
            "postinstall": "node -e \"require('fs').writeFileSync('SENTINEL','postinstall')\"",
        },
    }
    (repo / "package.json").write_text(json.dumps(package_json, indent=2) + "\n", encoding="utf-8")
    return sentinel


def _tool_ctx(
    tmp_path: Path,
    *,
    shell: Shell = "restricted",
    trust_tier: TrustTier = "trusted",
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell=shell,
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier=trust_tier,
    )


def _stub_npm_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    sentinel: Path,
) -> None:
    """Pretend npm is on PATH; write the sentinel unless ``--ignore-scripts``."""

    def _write_sentinel() -> None:
        sentinel.write_text("postinstall", encoding="utf-8")

    async def _fake_run_cmd(cmd: str, args: list[str]) -> tuple[int, str]:
        if cmd == "npm" and ("install" in args or "ci" in args):
            if "--ignore-scripts" not in args:
                _write_sentinel()
            return 0, "ok"
        return 0, "ok"

    def _which(name: str) -> str | None:
        if name == "npm":
            return "/usr/bin/npm"
        return None

    monkeypatch.setattr("mergecraft.prep.node._run_cmd", _fake_run_cmd)
    monkeypatch.setattr("mergecraft.prep.node.shutil.which", _which)


async def _await_installation(ctx: ToolContext) -> None:
    state = ctx.tool_state.dependency_installation
    assert state is not None
    assert state.promise is not None
    await state.promise
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trust_tier", "shell", "expect_ignore"),
    [
        pytest.param(
            "untrusted",
            "restricted",
            True,
            id="untrusted-restricted",
            marks=_XFAIL_TRUST,
        ),
        pytest.param(
            "untrusted",
            "enabled",
            True,
            id="untrusted-enabled",
            marks=_XFAIL_TRUST,
        ),
        pytest.param("untrusted", "disabled", True, id="untrusted-disabled"),
        pytest.param("trusted", "disabled", True, id="trusted-disabled"),
        pytest.param("trusted", "restricted", False, id="trusted-restricted"),
        pytest.param("trusted", "enabled", False, id="trusted-enabled"),
    ],
)
async def test_start_installation_ignore_scripts_follows_d10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trust_tier: TrustTier,
    shell: Shell,
    expect_ignore: bool,
) -> None:
    """D10: ignore scripts when untrusted **or** ``shell == disabled``."""
    captured: list[PrepOptions] = []

    async def _fake_prep(options: PrepOptions) -> list[PrepResult]:
        captured.append(options)
        return []

    monkeypatch.setattr("mergecraft.mcp.dependencies.run_prep_phase", _fake_prep)

    ctx = _tool_ctx(tmp_path, shell=shell, trust_tier=trust_tier)
    start_installation(ctx)
    await _await_installation(ctx)

    assert captured, "start_installation must call run_prep_phase"
    assert captured[0].ignore_scripts is expect_ignore


@pytest.mark.asyncio
@_XFAIL_TRUST
async def test_start_installation_untrusted_restricted_does_not_run_postinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Untrusted + default ``restricted`` must not create the postinstall sentinel."""
    sentinel = _write_postinstall_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_npm_lifecycle(monkeypatch, sentinel)

    ctx = _tool_ctx(tmp_path, shell="restricted", trust_tier="untrusted")
    start_installation(ctx)
    await _await_installation(ctx)

    assert not sentinel.exists(), (
        "untrusted + shell=restricted must pass ignore_scripts so postinstall "
        "does not write SENTINEL in the privileged process"
    )


@pytest.mark.asyncio
async def test_start_installation_trusted_restricted_may_run_postinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: maintainer tree + ``restricted`` may still run lifecycle scripts."""
    sentinel = _write_postinstall_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_npm_lifecycle(monkeypatch, sentinel)

    ctx = _tool_ctx(tmp_path, shell="restricted", trust_tier="trusted")
    start_installation(ctx)
    await _await_installation(ctx)

    assert sentinel.is_file()
    assert sentinel.read_text(encoding="utf-8") == "postinstall"


@pytest.mark.asyncio
@pytest.mark.parametrize("trust_tier", ["trusted", "untrusted"])
async def test_start_installation_shell_disabled_skips_postinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trust_tier: TrustTier,
) -> None:
    """Any ``shell == disabled`` still skips scripts, regardless of trust (D10)."""
    sentinel = _write_postinstall_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_npm_lifecycle(monkeypatch, sentinel)

    ctx = _tool_ctx(tmp_path, shell="disabled", trust_tier=trust_tier)
    start_installation(ctx)
    await _await_installation(ctx)

    assert not sentinel.exists()


@pytest.mark.asyncio
async def test_run_prep_phase_ignore_scripts_skips_postinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adapter control: ``run_prep_phase`` already honors ``ignore_scripts=True``."""
    sentinel = _write_postinstall_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_npm_lifecycle(monkeypatch, sentinel)

    results = await run_prep_phase(PrepOptions(ignore_scripts=True))

    assert not sentinel.exists()
    assert results
    assert results[0].language == "node"


@pytest.mark.asyncio
async def test_run_prep_phase_without_ignore_scripts_runs_postinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adapter control: ``ignore_scripts=False`` still executes the lifecycle script."""
    sentinel = _write_postinstall_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_npm_lifecycle(monkeypatch, sentinel)

    results = await run_prep_phase(PrepOptions(ignore_scripts=False))

    assert sentinel.is_file()
    assert results
    assert results[0].language == "node"
    assert results[0].dependencies_installed is True
