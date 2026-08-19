"""#287 / D11: untrusted + sandbox ``none`` must not register ``shell``.

``detect_sandbox_method`` early-returns ``"none"`` when ``CI != "true"``
(``mcp/shell.py``). ``build_common_tools`` still registers ``shell`` /
``kill_background`` whenever ``payload.shell == "restricted"``
(``mcp/server.py``), so an untrusted local/Action tree with no unshare
sandbox still gets a shell tool.

W6 must skip that registration when ``detect_sandbox_method() == "none"``
**and** ``trust_tier == "untrusted"``. Trusted + ``none`` + ``restricted``
keeps the tool (cwd confinement + ``resolve_env("restricted")``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.shell import detect_sandbox_method, get_sandbox_method
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

TrustTier = Literal["trusted", "untrusted"]

_XFAIL_SANDBOX = pytest.mark.xfail(
    reason="green after W6: untrusted + sandbox none does not register shell",
    strict=False,
)


@pytest.fixture(autouse=True)
def _reset_sandbox_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """W4.2 — module global at ``shell.py`` must not leak across cases."""
    monkeypatch.setattr(shell_mod, "_detected_sandbox", None)


def _tool_ctx(
    tmp_path: Path,
    *,
    trust_tier: TrustTier = "trusted",
    shell: Literal["disabled", "restricted", "enabled"] = "restricted",
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


@pytest.mark.parametrize("ci_value", [None, "false", "0", ""], ids=["unset", "false", "0", "empty"])
def test_detect_sandbox_method_none_outside_ci(
    monkeypatch: pytest.MonkeyPatch,
    ci_value: str | None,
) -> None:
    """Non-CI hosts return ``none`` and do not claim isolation."""
    if ci_value is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci_value)
    method = detect_sandbox_method()
    assert method == "none"
    assert get_sandbox_method() == "none"


def test_detect_sandbox_method_cache_resets_between_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4.2: a prior ``none`` cache must not survive a reset + CI=true probe skip."""
    monkeypatch.delenv("CI", raising=False)
    assert detect_sandbox_method() == "none"
    monkeypatch.setattr(shell_mod, "_detected_sandbox", None)
    monkeypatch.setenv("CI", "false")
    assert detect_sandbox_method() == "none"


@_XFAIL_SANDBOX
def test_untrusted_restricted_sandbox_none_omits_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D11: untrusted + restricted + sandbox none must not register shell tools."""
    monkeypatch.delenv("CI", raising=False)
    ctx = _tool_ctx(tmp_path, trust_tier="untrusted", shell="restricted")
    names = {spec.name for spec in build_common_tools(ctx)}
    assert detect_sandbox_method() == "none"
    assert "shell" not in names
    assert "kill_background" not in names


def test_trusted_restricted_sandbox_none_keeps_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: trusted local CLI review still gets ``shell`` when sandbox is none."""
    monkeypatch.delenv("CI", raising=False)
    ctx = _tool_ctx(tmp_path, trust_tier="trusted", shell="restricted")
    names = {spec.name for spec in build_common_tools(ctx)}
    assert detect_sandbox_method() == "none"
    assert "shell" in names
    assert "kill_background" in names
