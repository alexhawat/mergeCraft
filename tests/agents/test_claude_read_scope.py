"""The Claude reviewer must be denied the credential material the image cannot move.

Plan 42 denied Claude's write, web and execution tools but not ``Read`` /
``Glob`` / ``Grep``, which can read anything the agent user can. The OS identity
is the real boundary (``tests/security/test_agent_readable_secrets.py``), but a
few paths cannot be moved out of the agent user's reach:

* ``/github/file_commands/*`` — the runner's command files;
* ``/github/home/**`` — the runner's home;
* ``/proc/*/environ`` of other processes — kernel state;
* ``<codex home>/auth.json`` — written by ``agents/codex._setup_codex_auth``.

The wiring point is :func:`mergecraft.agents.gates.build_claude_native_fs_denies`.
An **absolute** path is spelled ``//<path>`` — a single leading ``/`` anchors at
the primary working directory, not the filesystem root, so ``Read(/github/home)``
denies ``<cwd>/github/home``, a path that does not exist. Each path also needs
its ``/**`` subtree form so a file argument and a directory argument are both
covered. This suite pins that the Claude driver passes those paths to the
builder, that the builder anchors them, and that the resulting rules reach the
CLI invocation (argv, or a settings file written beside the MCP config).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.claude import _run_claude_once
from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

# The paths HW0's static table says the image cannot move; each needs a Claude
# deny rule. ``auth.json`` is matched by basename because the Codex home is
# run-specific.
_STATIC_DENY_PATHS = (
    "/github/file_commands",
    "/github/home",
    "/proc/*/environ",
)


class _Reader:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class _EmptyProcess:
    def __init__(self) -> None:
        self.stdout = iter(())
        self.stderr = _Reader("")
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - not reached
        return None


def _noop_ctx(*_a: Any, **_k: Any) -> Any:
    from contextlib import nullcontext

    return nullcontext()


def _run_ctx(tmp_path: Path) -> AgentRunContext:
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        resolved_model="anthropic/claude-sonnet-5",
    )


def _captured_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    module = importlib.import_module("mergecraft.agents.claude")
    seen: list[list[str]] = []

    def _spawn(cmd: list[str], **_k: Any) -> _EmptyProcess:
        seen.append(list(cmd))
        return _EmptyProcess()

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    monkeypatch.setattr(module, "track_process_group", _noop_ctx)
    monkeypatch.setattr(module, "wait_or_kill_process_group", lambda proc, timeout: proc.wait())

    _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=_run_ctx(tmp_path),
        mcp_config=str(tmp_path / "mcp.json"),
    )
    assert seen, "driver never spawned the CLI"
    return seen[0]


def _tmpdir_blob(root: Path) -> str:
    """Return the argv's settings sources: every readable file the driver wrote."""
    parts: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def test_driver_passes_the_image_secret_paths_to_the_native_fs_deny_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The driver must wire ``build_claude_native_fs_denies`` with the run's paths."""
    import mergecraft.agents.claude as claude_mod
    import mergecraft.agents.gates as gates_mod

    captured: list[str] = []

    def _record(extra_secret_paths: list[str] | None = None) -> list[str]:
        captured.extend(extra_secret_paths or [])
        return [*gates_mod.GIT_NATIVE_WRITE_DENY_CLAUDE, *gates_mod.GIT_NATIVE_READ_DENY_CLAUDE]

    monkeypatch.setattr(gates_mod, "build_claude_native_fs_denies", _record)
    if hasattr(claude_mod, "build_claude_native_fs_denies"):
        monkeypatch.setattr(claude_mod, "build_claude_native_fs_denies", _record)

    _captured_argv(tmp_path, monkeypatch)

    for path in _STATIC_DENY_PATHS:
        assert any(path in candidate for candidate in captured), (
            f"the driver never passed {path!r} to build_claude_native_fs_denies; "
            f"captured {captured!r}"
        )
    assert any("auth.json" in candidate for candidate in captured), (
        f"the Codex auth file needs a deny rule; captured {captured!r}"
    )


def test_native_read_denies_reach_the_claude_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every path the image cannot move gets a ``Read(...)`` deny rule in the invocation."""
    argv = _captured_argv(tmp_path, monkeypatch)
    blob = " ".join(argv) + "\n" + _tmpdir_blob(tmp_path)

    for path in ("/github/file_commands", "/github/home", "/proc/*/environ"):
        assert re.search(rf"Read\([^)]*{re.escape(path)}", blob), (
            f"no Read deny rule names {path!r}; invocation was {blob!r}"
        )
    assert re.search(r"Read\([^)]*auth\.json", blob), (
        f"no Read deny rule names the Codex auth file; invocation was {blob!r}"
    )


@pytest.mark.parametrize("verb", ["Read", "Edit"])
def test_the_builder_emits_read_and_edit_rules_for_each_secret_path(verb: str) -> None:
    """The helper itself: an absolute path is anchored ``//`` with an exact + subtree rule.

    Claude Code resolves a single leading ``/`` against the primary working
    directory, so ``Read(/github/home)`` denies ``<cwd>/github/home`` — a path
    that does not exist — and the control is dead. The fail-closed spelling is
    the gitignore-style ``//`` for the filesystem root, and both the exact rule
    (a file argument) and its ``/**`` subtree (a directory argument) are needed.
    """
    from mergecraft.agents.gates import build_claude_native_fs_denies

    rules = build_claude_native_fs_denies(["/secret/auth.json"])

    assert f"{verb}(//secret/auth.json)" in rules, (
        f"{verb}(/secret/auth.json) anchors at the working directory, not the "
        f"filesystem root, and denies nothing; got {rules!r}"
    )
    assert f"{verb}(//secret/auth.json/**)" in rules, (
        f"the anchored subtree rule must cover a directory argument; got {rules!r}"
    )
    assert f"{verb}(/secret/auth.json)" not in rules, (
        f"the single-slash absolute form is anchored at the working directory and "
        f"denies nothing; got {rules!r}"
    )
