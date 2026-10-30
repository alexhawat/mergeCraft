"""OpenCode 2.x runs through ``opencode run``, because its server API moved.

2.x answers the 1.x ``POST /session`` with 405 (its routes live under
``/api/session``). Its ``run`` command keeps the JSON event stream and resumes
a session by id, so the driver detects the major version and, on 2.x, runs
each turn through ``opencode run --standalone``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import opencode as oc
from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.agents.shared import AgentResult, ResolvedInstructions

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _fresh_version_cache(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "_OPENCODE_MAJOR_CACHE", {})


# ── version detection ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("printed", "expected"),
    [("opencode v2.0.29\n", 2), ("1.18.30\n", 1), ("no version here", None)],
)
def test_major_version_is_read_from_the_cli(
    monkeypatch: MonkeyPatch, printed: str, expected: int | None
) -> None:
    calls: list[list[str]] = []

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=printed, stderr="")

    monkeypatch.setattr(oc.subprocess, "run", _run)

    assert oc._opencode_major_version("/bin/opencode") == expected
    assert oc._opencode_major_version("/bin/opencode") == expected
    assert calls == [["/bin/opencode", "--version"]], "the version is read once per binary"


def test_an_unrunnable_cli_reads_as_no_version(monkeypatch: MonkeyPatch) -> None:
    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("no such file")

    monkeypatch.setattr(oc.subprocess, "run", _run)

    assert oc._opencode_major_version("/missing/opencode") is None


# ── routing ───────────────────────────────────────────────────────────────────


async def test_run_takes_the_run_path_on_2x_and_never_boots_a_server(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "_opencode_major_version", lambda _cli: 2)

    def _boot(**kwargs: object) -> Any:
        raise AssertionError("2.x must not boot the 1.x server")

    monkeypatch.setattr(oc, "_boot_opencode_server", _boot)

    async def _v2(*, cli: str, ctx: Any, env: dict[str, str], model: str | None) -> AgentResult:
        return AgentResult(success=True, output="v2 output")

    monkeypatch.setattr(oc, "_run_v2", _v2)

    result = await oc._run(make_agent_run_context(tmp_path, resolved_model=None))

    assert result.success is True
    assert result.output == "v2 output"


# ── the 2.x run path ──────────────────────────────────────────────────────────


def _streaming_recorder(calls: list[list[str]], *, session_id: str = "ses_1") -> Any:
    def _fake(
        *, cmd: list[str], ctx: Any, env: dict[str, str], session: dict[str, str]
    ) -> AgentResult:
        calls.append(cmd)
        session.setdefault("id", session_id)
        return AgentResult(success=True, output="ok")

    return _fake


async def test_v2_runs_standalone_with_json_output_and_the_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(oc, "_run_opencode_cli_streaming", _streaming_recorder(calls))

    async def _no_retry(ctx: Any, *, initial: AgentResult, resume: Any) -> AgentResult:
        return initial

    monkeypatch.setattr(oc, "run_post_run_retry_loop", _no_retry)

    async def _finalize(ctx: Any, result: AgentResult) -> AgentResult:
        return result

    monkeypatch.setattr(oc, "finalize_agent_result", _finalize)
    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model="nous/tencent/hy3"),
        instructions=ResolvedInstructions(system="SYSTEM", user="USER"),
    )

    await oc._run_v2(cli="/bin/opencode", ctx=ctx, env={}, model="nous/tencent/hy3")

    (cmd,) = calls
    assert cmd[:7] == [
        "/bin/opencode",
        "run",
        "--standalone",
        "--format",
        "json",
        "--title",
        "mergecraft",
    ]
    assert cmd[cmd.index("--model") + 1] == "nous/tencent/hy3"
    assert cmd[-1] == "SYSTEM\n\nUSER"
    assert "--session" not in cmd


async def test_v2_follow_ups_resume_the_same_session(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(oc, "_run_opencode_cli_streaming", _streaming_recorder(calls))

    async def _one_retry(ctx: Any, *, initial: AgentResult, resume: Any) -> AgentResult:
        return await resume("submit your verdict")

    monkeypatch.setattr(oc, "run_post_run_retry_loop", _one_retry)

    async def _finalize(ctx: Any, result: AgentResult) -> AgentResult:
        return result

    monkeypatch.setattr(oc, "finalize_agent_result", _finalize)

    await oc._run_v2(
        cli="/bin/opencode",
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        model=None,
    )

    assert len(calls) == 2
    follow_up = calls[1]
    assert follow_up[follow_up.index("--session") + 1] == "ses_1"
    assert follow_up[-1] == "submit your verdict"


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


async def test_v2_sends_a_prompt_longer_than_one_argv_string_as_a_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(oc, "_run_opencode_cli_streaming", _streaming_recorder(calls))
    monkeypatch.setattr(oc, "_OPENCODE_ARGV_PROMPT_LIMIT", 10)

    async def _no_retry(ctx: Any, *, initial: AgentResult, resume: Any) -> AgentResult:
        return initial

    monkeypatch.setattr(oc, "run_post_run_retry_loop", _no_retry)

    async def _finalize(ctx: Any, result: AgentResult) -> AgentResult:
        return result

    monkeypatch.setattr(oc, "finalize_agent_result", _finalize)

    await oc._run_v2(
        cli="/bin/opencode",
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        model=None,
    )

    (cmd,) = calls
    attached = cmd[cmd.index("--file") + 1]
    assert _read(attached) == "review this diff"
    assert "review this diff" not in cmd


async def test_v2_initial_failure_is_returned_without_a_follow_up(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def _fail(**kwargs: Any) -> AgentResult:
        return AgentResult(success=False, error="provider down")

    monkeypatch.setattr(oc, "_run_opencode_cli_streaming", _fail)

    result = await oc._run_v2(
        cli="/bin/opencode",
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        model=None,
    )

    assert result.success is False
    assert result.error == "provider down"


# ── the 2.x event stream ─────────────────────────────────────────────────────


def test_the_handler_records_the_session_text_and_error() -> None:
    session: dict[str, str] = {}
    handle = oc._session_event_handler(session)
    accumulator = StreamSpanAccumulator(agent_name="opencode")

    handle(accumulator, {"type": "step_start", "sessionID": "ses_9", "part": {}})
    handle(accumulator, {"type": "text", "sessionID": "ses_9", "part": {"text": "pi"}})
    handle(accumulator, {"type": "text", "sessionID": "ses_9", "part": {"text": "ng"}})
    handle(
        accumulator, {"type": "error", "sessionID": "ses_9", "error": {"message": "rate limited"}}
    )

    assert session == {"id": "ses_9", "error": "rate limited"}
    assert accumulator.final_output == "ping"


class _Proc:
    def __init__(self, stdout: str, returncode: int) -> None:
        self.stdout = stdout.splitlines(keepends=True)
        self.stderr: Any = _Text("")
        self.returncode = returncode
        self.pid = 777_123

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class _Text:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text

    def __iter__(self) -> Any:
        return iter(self._text.splitlines(keepends=True))

    def readline(self) -> str:
        return ""


def test_a_2x_turn_records_token_usage_from_step_finish(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#801: the 2.x stream reports tokens per step; the run record must show them.

    Without this the review record had no ``Tokens:`` or ``Cost:`` line for an
    OpenCode Go run, because the CLI result carried no usage at all.
    """
    stdout = (
        json.dumps({"type": "text", "sessionID": "ses_9", "part": {"text": "ok"}})
        + "\n"
        + json.dumps(
            {
                "type": "step_finish",
                "sessionID": "ses_9",
                "part": {
                    "type": "step-finish",
                    "reason": "stop",
                    "cost": 0.0021,
                    "tokens": {
                        "input": 1200,
                        "output": 34,
                        "reasoning": 0,
                        "cache": {"read": 300, "write": 10},
                    },
                },
            }
        )
        + "\n"
    )
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda cmd, **kwargs: _Proc(stdout, 0))

    result = oc._run_opencode_cli_streaming(
        cmd=["opencode"],
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        session={},
    )

    assert result.success is True
    usage = result.usage
    assert usage is not None, "a stream that reports tokens must carry usage"
    assert usage.input_tokens == 1200, "the prompt total is not inflated by cached reads"
    assert usage.output_tokens == 34
    assert usage.cache_read_tokens == 300
    assert usage.cost_usd == pytest.approx(0.0021)


def test_a_2x_turn_sums_the_tokens_of_every_step(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    def _step(tokens_in: int, tokens_out: int) -> str:
        return json.dumps(
            {
                "type": "step_finish",
                "sessionID": "ses_9",
                "part": {"tokens": {"input": tokens_in, "output": tokens_out}},
            }
        )

    stdout = "\n".join([_step(100, 5), _step(250, 8)]) + "\n"
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda cmd, **kwargs: _Proc(stdout, 0))

    result = oc._run_opencode_cli_streaming(
        cmd=["opencode"],
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        session={},
    )

    assert result.usage is not None
    assert result.usage.input_tokens == 350
    assert result.usage.output_tokens == 13


def test_a_2x_turn_without_reported_tokens_carries_no_usage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    stdout = json.dumps({"type": "text", "sessionID": "ses_9", "part": {"text": "ok"}}) + "\n"
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda cmd, **kwargs: _Proc(stdout, 0))

    result = oc._run_opencode_cli_streaming(
        cmd=["opencode"],
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        session={},
    )

    assert result.success is True
    assert result.usage is None, "no reported tokens must not invent a usage row"


def test_a_failed_2x_turn_names_its_stream_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """2.x reports the failure on stdout; with empty stderr it is the error."""
    stdout = json.dumps(
        {"type": "error", "sessionID": "ses_9", "error": {"message": "model overloaded"}}
    )
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda cmd, **kwargs: _Proc(stdout, 1))
    session: dict[str, str] = {}

    result = oc._run_opencode_cli_streaming(
        cmd=["opencode"],
        ctx=make_agent_run_context(tmp_path, resolved_model=None),
        env={},
        session=session,
    )

    assert result.success is False
    assert result.error == "model overloaded"
