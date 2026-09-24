"""The Gemini reviewer must not hold its built-in write, shell or web tools.

The driver appends ``-y`` (auto-approve) in CI and excludes only the MCP
server's tools. Gemini's *built-in* tools — the file writers, the shell, and
the web fetchers — stay available and unprompted, so the reviewer can edit the
reviewed tree and reach the network.

The contract is the same prevention boundary as the Claude reviewer: a
top-level ``excludeTools`` in the written ``settings.json`` names the built-in
write, shell and web tools in every mode, while ``-y`` stays and the per-MCP
server exclusions are unchanged.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

import mergecraft.agents.gemini as gemini_mod
from mergecraft.types import MERGECRAFT_MCP_NAME

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

# AR0 recorded these against the pinned Gemini CLI (0.53.0 local / 0.59.0 Docker).
_BUILTIN_WRITE_SHELL_WEB = (
    "write_file",
    "replace",
    "run_shell_command",
    "web_fetch",
    "google_web_search",
)


def _written_settings(ctx: Any) -> dict[str, Any]:
    config_path = Path(gemini_mod.write_mcp_config(ctx))
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("ci", [False, True], ids=["no-ci", "ci"])
def test_settings_exclude_builtin_write_shell_and_web_tools(
    ci: bool, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The exclusion is unconditional — ``-y`` cannot be the only boundary."""
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)

    settings = _written_settings(make_agent_run_context(tmp_path, resolved_model=None))

    excluded = settings.get("excludeTools")
    assert isinstance(excluded, list), (
        "the written settings must carry a top-level `excludeTools` list "
        "(the per-MCP-server list only filters that server's tools)"
    )
    names = {str(item) for item in excluded}
    missing = sorted(set(_BUILTIN_WRITE_SHELL_WEB) - names)
    assert not missing, f"built-in write/shell/web tools not excluded: {missing}"


def test_per_server_mcp_exclusions_are_unchanged(tmp_path: Path) -> None:
    """The MCP exclusion list keeps its existing meaning and contents."""
    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        subagent_denied_tools=("push_branch",),
    )

    settings = _written_settings(ctx)

    server = settings["mcpServers"][MERGECRAFT_MCP_NAME]
    assert "push_branch" in server["excludeTools"]


@pytest.mark.parametrize(
    ("ci", "expected"),
    [(True, True), (False, False)],
    ids=["ci-adds-y", "no-ci-omits-y"],
)
def test_auto_approve_flag_follows_ci(
    ci: bool, expected: bool, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``-y`` stays exactly as it was — the exclusion list is the boundary."""
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)

    captured: dict[str, list[str]] = {}

    def _fake_streaming(
        *, cmd: list[str], ctx: Any, model: str | None, prompt: str | None = None
    ) -> Any:
        del ctx, model, prompt
        captured["cmd"] = cmd
        return gemini_mod.AgentResult(success=True)

    monkeypatch.setattr(gemini_mod, "_run_gemini_streaming", _fake_streaming)

    gemini_mod._run_gemini_once(
        cli="/usr/bin/gemini",
        prompt="review this diff",
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        mcp_config="",
    )

    assert ("-y" in captured["cmd"]) is expected
