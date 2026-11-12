"""A 200 KiB prompt reaches every CLI driver without one oversized argv string (#1329).

Linux caps one ``execve`` argument at 128 KiB (``MAX_ARG_STRLEN``), so a prompt
passed as a single argv string fails to spawn with ``E2BIG``. Each driver now
sends the prompt on stdin or in a file. The fake CLI here is a real child
process spawned through the real ``spawn_agent_cli``; it records how much
prompt text it received and from where.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import shared
from mergecraft.agents.shared import AgentResult, ResolvedInstructions

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_MAX_ARG_STRLEN = 128 * 1024
_USER = "u" * (200 * 1024)
_SYSTEM = "s" * (8 * 1024)

# argv[1] is the report path; the rest is the driver's own argv (minus the CLI).
_FAKE_CLI = r"""
import json, sys
report, argv = sys.argv[1], sys.argv[2:]
received = ""
if "--system-prompt-file" in argv:
    received += open(argv[argv.index("--system-prompt-file") + 1]).read()
if "--file" in argv:
    received += open(argv[argv.index("--file") + 1]).read()
if "-" in argv or "-p" in argv or "--print" in argv:
    received += sys.stdin.read()
received += "".join(a for a in argv if len(a) > 4096)
json.dump({"received": len(received), "longest_arg": max(map(len, argv))}, open(report, "w"))
sys.stdout.write('{"type": "result", "result": "ok"}\n')
"""


class _Driver(NamedTuple):
    name: str
    module_name: str
    invoke: Callable[[Any, Any, Path], AgentResult]
    carries_system: bool


def _claude(module: Any, ctx: Any, tmp_path: Path) -> AgentResult:
    return module._run_claude_once(
        cli="claude", prompt="", ctx=ctx, mcp_config=str(tmp_path / "mcp.json")
    )


def _codex(module: Any, ctx: Any, _tmp_path: Path) -> AgentResult:
    return module._run_codex_once(cli="codex", prompt="", ctx=ctx, mcp_config="unused")


def _gemini(module: Any, ctx: Any, _tmp_path: Path) -> AgentResult:
    return module._run_gemini_once(cli="gemini", prompt="", ctx=ctx, mcp_config="")


async def _opencode_async(module: Any, ctx: Any) -> AgentResult:
    return await module._run_cli_fallback(cli="opencode", ctx=ctx, env={})


def _opencode(module: Any, ctx: Any, _tmp_path: Path) -> AgentResult:
    import asyncio

    return asyncio.run(_opencode_async(module, ctx))


_DRIVERS = (
    _Driver("claude", "mergecraft.agents.claude", _claude, True),
    _Driver("codex", "mergecraft.agents.codex", _codex, False),
    _Driver("gemini", "mergecraft.agents.gemini", _gemini, False),
    _Driver("opencode-1x", "mergecraft.agents.opencode", _opencode, True),
)


@pytest.mark.parametrize("driver", _DRIVERS, ids=[d.name for d in _DRIVERS])
def test_a_200_kib_prompt_reaches_the_cli(
    driver: _Driver, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = importlib.import_module(driver.module_name)
    report = tmp_path / "report.json"
    argvs: list[list[str]] = []
    real_spawn = shared.spawn_agent_cli

    def _spawn(cmd: list[str], **kwargs: Any) -> Any:
        argvs.append(list(cmd))
        fake = [sys.executable, "-c", _FAKE_CLI, str(report), *cmd[1:]]
        kwargs["env"] = {"PATH": "/usr/bin:/bin"}
        return real_spawn(fake, **kwargs)

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    if hasattr(module, "_build_env"):
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})
    if driver.name == "opencode-1x":
        # Keep the attached prompt file out of the real evidence directory.
        monkeypatch.setattr(module, "_evidence_dir", lambda _ctx: tmp_path / "evidence")
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    ctx.instructions = ResolvedInstructions(system=_SYSTEM, user=_USER)

    driver.invoke(module, ctx, tmp_path)

    assert argvs, f"{driver.name} never spawned its CLI"
    longest = max(len(arg) for argv in argvs for arg in argv)
    assert longest < _MAX_ARG_STRLEN, f"{driver.name} put a {longest}-byte string in argv"
    received = json.loads(report.read_text(encoding="utf-8"))["received"]
    assert received >= len(_USER), f"{driver.name} CLI received only {received} bytes"
    if driver.carries_system:
        assert received >= len(_USER) + len(_SYSTEM)


def test_the_opencode_1x_fallback_keeps_the_answer(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """AGT-F15 — the ``run`` fallback reads ``text`` events, so the answer survives."""
    module = importlib.import_module("mergecraft.agents.opencode")
    event = '{"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "the answer"}}'
    script = f"import sys; sys.stdout.write({event!r} + chr(10))"
    real_spawn = shared.spawn_agent_cli

    def _spawn(cmd: list[str], **kwargs: Any) -> Any:
        kwargs["env"] = {"PATH": "/usr/bin:/bin"}
        return real_spawn([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = _opencode(module, ctx, tmp_path)

    assert result.success is True
    assert result.output == "the answer"
