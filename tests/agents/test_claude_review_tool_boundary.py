"""The Claude reviewer must not be able to write files or reach the web.

``--disallowedTools`` denies the execution tools, but ``Write``, ``Edit``,
``MultiEdit``, ``NotebookEdit``, ``WebFetch`` and ``WebSearch`` stay available
— and ``--dangerously-skip-permissions`` removes the last interactive prompt
in CI. ``SECURITY.md``'s review-only boundary says reviewers must not edit
source in the reviewed tree, and no production mode needs a write or web tool.

The contract is prevention: those tools (and their ``Agent(<tool>)`` forms)
join the deny list unconditionally, while the four execution tools stay denied
and ``--dangerously-skip-permissions`` stays for headless CI.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_EXEC_TOOLS = ("Bash", "Monitor", "REPL", "Workflow")
_REVIEW_DENIED_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch")


class _NullProcessGroup:
    def __init__(self, *_args: object, **_kwargs: object) -> None: ...

    def __enter__(self) -> None: ...

    def __exit__(self, *_args: object) -> bool:
        return False


class _Reader:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class _EmptyProcess:
    """A CLI that emits nothing and exits cleanly."""

    def __init__(self) -> None:
        self.stdout: Any = iter(())
        self.stderr: Any = _Reader("")
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def poll(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - never reached on a clean exit
        return None


def _captured_argv(monkeypatch: MonkeyPatch, tmp_path: Path) -> list[str]:
    module = importlib.import_module("mergecraft.agents.claude")
    seen: list[list[str]] = []

    def _spawn(cmd: list[str], **_kwargs: Any) -> _EmptyProcess:
        seen.append(list(cmd))
        return _EmptyProcess()

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    monkeypatch.setattr(module, "track_process_group", _NullProcessGroup)
    monkeypatch.setattr(
        module, "wait_or_kill_process_group", lambda process, timeout: process.wait()
    )

    module._run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5"),
        mcp_config=str(tmp_path / "mcp.json"),
    )
    assert seen, "the driver never spawned the CLI"
    return seen[0]


def _disallowed_value(argv: list[str]) -> str:
    assert "--disallowedTools" in argv, f"argv was {argv!r}"
    return argv[argv.index("--disallowedTools") + 1]


def _deny_rules(value: str) -> set[str]:
    return {item.strip() for item in value.split(",")}


@pytest.mark.parametrize("ci", [False, True], ids=["no-ci", "ci"])
def test_reviewer_denies_write_and_web_tools(
    ci: bool, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Prevention over detection: the reviewer must not hold a write tool."""
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)

    rules = _deny_rules(_disallowed_value(_captured_argv(monkeypatch, tmp_path)))

    for tool in _REVIEW_DENIED_TOOLS:
        assert tool in rules, f"{tool} must be denied unconditionally; rules={sorted(rules)}"
        assert f"Agent({tool})" in rules, f"Agent({tool}) must be denied too"


@pytest.mark.parametrize("ci", [False, True], ids=["no-ci", "ci"])
def test_execution_tools_stay_denied(ci: bool, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The fix adds to the deny list; it must never remove an entry."""
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)

    rules = _deny_rules(_disallowed_value(_captured_argv(monkeypatch, tmp_path)))

    for tool in _EXEC_TOOLS:
        assert tool in rules
        assert f"Agent({tool})" in rules


def test_deny_list_constant_carries_the_review_tools() -> None:
    """The constant the argv is built from must expose the new denies."""
    module = importlib.import_module("mergecraft.agents.claude")
    rules = _deny_rules(module.CLAUDE_DISALLOWED_TOOLS)

    assert set(_REVIEW_DENIED_TOOLS).issubset(rules)
    assert set(_EXEC_TOOLS).issubset(rules)


def test_ci_still_skips_permissions(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Headless CI cannot answer a prompt; the deny list is the boundary."""
    monkeypatch.setenv("CI", "true")

    argv = _captured_argv(monkeypatch, tmp_path)

    assert "--dangerously-skip-permissions" in argv
    rules = _deny_rules(_disallowed_value(argv))
    assert set(_REVIEW_DENIED_TOOLS).issubset(rules)


def test_agent_definitions_do_not_regrant_denied_tools() -> None:
    """The subagent JSON must not carry an allow-list that re-grants them."""
    import json

    from mergecraft.agents.claude import build_agents_json

    payload = json.loads(
        build_agents_json(
            verifier_denied_tools=("push_branch",),
            subagent_denied_tools=("push_branch",),
        )
    )
    denied = {*_REVIEW_DENIED_TOOLS, *_EXEC_TOOLS}
    for name, spec in payload.items():
        allowed = spec.get("tools")
        if allowed is None:
            continue
        overlap = sorted(set(allowed) & denied)
        assert not overlap, f"{name} re-grants denied tools: {overlap}"
