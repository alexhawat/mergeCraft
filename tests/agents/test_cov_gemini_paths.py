"""Error, guard, and degraded-output paths in ``mergecraft.agents.gemini``.

The existing gemini suite drives the happy path (CLI on PATH, well-formed
single-blob JSON, exit 0). This module drives the other way out of each
decision: missing/blank/malformed credentials, a CLI that is not installed,
a non-zero exit, a timeout, truncated or non-object stream output, and every
stream event shape whose tracer-disabled branch was never exercised.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import gemini as gemini_mod
from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.types import MERGECRAFT_MCP_NAME

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


class _FakeStderr:
    """Stand-in for ``Popen.stderr`` — a single blocking ``read()``."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class _FakeProcess:
    """``subprocess.Popen`` look-alike for the gemini streaming read loop."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        self.stdout: list[str] = stdout.splitlines(keepends=True)
        self.stderr = _FakeStderr(stderr)
        self.returncode = returncode
        self.pid = 999_001

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode


def _spawn(process: _FakeProcess) -> Any:
    def _fake_spawn(cmd: list[str], **kwargs: object) -> _FakeProcess:
        del cmd, kwargs
        return process

    return _fake_spawn


@pytest.fixture
def disable_tracing(monkeypatch: MonkeyPatch) -> None:
    """Force the tracer-disabled branch of ``_run_gemini_streaming``."""
    monkeypatch.setattr(
        "mergecraft.tracing.sinks.claim_sink",
        lambda _resolved: None,
    )


def _tracer() -> tuple[Any, Any]:
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    return sink, Tracer(sink=sink, session_id="gem-session", run_id="gem-run")


def _spans(sink: Any, kind: str) -> list[Any]:
    return [event for event in sink.events if getattr(event, "kind", None) == kind]


def _written_settings(config_path: str) -> dict[str, Any]:
    """Load the ``settings.json`` ``write_mcp_config`` reports it wrote."""
    from pathlib import Path as _Path

    loaded: Any = json.loads(_Path(config_path).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


# ---------------------------------------------------------------------------
# _strip_provider_prefix — the `slash > 0` guard
# ---------------------------------------------------------------------------


def test_strip_provider_prefix_only_strips_a_real_provider_segment() -> None:
    """A leading slash is not a provider prefix, so the specifier survives whole."""
    assert gemini_mod._strip_provider_prefix("google/gemini-3.1-pro") == "gemini-3.1-pro"
    assert gemini_mod._strip_provider_prefix("gemini-3.1-pro") == "gemini-3.1-pro"
    # slash at index 0 → `slash > 0` is False; stripping here would produce
    # the model id "gemini-3.1-pro" from a specifier with an empty provider.
    assert gemini_mod._strip_provider_prefix("/gemini-3.1-pro") == "/gemini-3.1-pro"


def test_strip_provider_prefix_keeps_nested_model_ids_intact() -> None:
    """Only the first segment is a provider — nested ids keep their slashes."""
    assert gemini_mod._strip_provider_prefix("vertex/publishers/google/gemini") == (
        "publishers/google/gemini"
    )


# ---------------------------------------------------------------------------
# _install / ctx_tmpdir_fallback — CLI absent from PATH
# ---------------------------------------------------------------------------


async def test_install_falls_back_to_a_locally_vendored_cli(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``gemini`` off PATH but vendored under the temp dir resolves to the vendored path."""
    monkeypatch.setattr(gemini_mod.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(tmp_path))
    local = tmp_path / "node_modules" / ".bin" / "gemini"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n", encoding="utf-8")

    assert await gemini_mod._install(None) == str(local)


async def test_install_raises_with_an_actionable_message_when_cli_is_absent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Neither PATH nor the vendored path resolves → a named install instruction."""
    monkeypatch.setattr(gemini_mod.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(tmp_path))

    with pytest.raises(FileNotFoundError) as excinfo:
        await gemini_mod._install(None)

    assert "@google/gemini-cli" in str(excinfo.value)


def test_ctx_tmpdir_fallback_prefers_the_configured_temp_dir(monkeypatch: MonkeyPatch) -> None:
    """An empty ``MERGECRAFT_TEMP_DIR`` is treated as unset, not as an empty path."""
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", "/scratch/run-1")
    assert gemini_mod.ctx_tmpdir_fallback() == "/scratch/run-1"

    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", "")
    assert gemini_mod.ctx_tmpdir_fallback() == "/tmp"

    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    assert gemini_mod.ctx_tmpdir_fallback() == "/tmp"


# ---------------------------------------------------------------------------
# _normalize_gemini_api_key — credential resolution when the primary is
# absent, blank, or whitespace-only
# ---------------------------------------------------------------------------


def test_blank_gemini_key_is_replaced_by_the_google_alias() -> None:
    """A whitespace-only primary key must not shadow a usable alias."""
    env = {
        gemini_mod.GEMINI_API_KEY_ENV: "   ",
        gemini_mod.GOOGLE_GENERATIVE_AI_API_KEY_ENV: "alias-key",
    }
    gemini_mod._normalize_gemini_api_key(env)
    assert env[gemini_mod.GEMINI_API_KEY_ENV] == "alias-key"


def test_present_gemini_key_wins_over_the_google_alias() -> None:
    """A real primary key is never overwritten by the alias."""
    env = {
        gemini_mod.GEMINI_API_KEY_ENV: "primary-key",
        gemini_mod.GOOGLE_GENERATIVE_AI_API_KEY_ENV: "alias-key",
    }
    gemini_mod._normalize_gemini_api_key(env)
    assert env[gemini_mod.GEMINI_API_KEY_ENV] == "primary-key"


def test_no_credential_at_all_leaves_the_key_unset() -> None:
    """A blank alias must not materialise an empty ``GEMINI_API_KEY`` entry."""
    env = {gemini_mod.GOOGLE_GENERATIVE_AI_API_KEY_ENV: "  "}
    gemini_mod._normalize_gemini_api_key(env)
    assert gemini_mod.GEMINI_API_KEY_ENV not in env


def test_build_env_normalizes_the_alias_into_the_child_env(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``_build_env`` hands the child a HOME under the run dir and a resolved key."""
    monkeypatch.delenv(gemini_mod.GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.setenv(gemini_mod.GOOGLE_GENERATIVE_AI_API_KEY_ENV, "alias-key")
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    env = gemini_mod._build_env(ctx)

    assert env["HOME"] == str(tmp_path)
    assert env[gemini_mod.GEMINI_API_KEY_ENV] == "alias-key"


# ---------------------------------------------------------------------------
# _parse_gemini_payload / _parse_gemini_stdout — malformed and partial output
# ---------------------------------------------------------------------------


def test_empty_stdout_yields_no_output_and_no_usage() -> None:
    """A provider that printed nothing must not fabricate an empty-string usage record."""
    assert gemini_mod._parse_gemini_stdout("   \n  \n") == ("", None)


def test_truncated_json_is_returned_verbatim_without_usage() -> None:
    """A cut-off blob is surfaced as raw text, not silently dropped."""
    truncated = '{"result": "half a rev'
    output, usage = gemini_mod._parse_gemini_stdout(truncated)
    assert output == truncated
    assert usage is None


def test_non_object_json_stdout_is_treated_as_plain_text() -> None:
    """A top-level JSON array is not a payload — the raw text stands in."""
    output, usage = gemini_mod._parse_gemini_stdout('["a", "b"]')
    assert output == '["a", "b"]'
    assert usage is None


def test_ndjson_scan_stops_at_the_terminal_result_event() -> None:
    """The last terminal event wins; malformed and blank lines are skipped."""
    stdout = "\n".join(
        [
            "not json at all",
            "",
            json.dumps({"result": "earlier", "usage": {"input_tokens": 1}}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "result": "final answer",
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                }
            ),
        ]
    )
    output, usage = gemini_mod._parse_gemini_stdout(stdout)

    assert output == "final answer"
    assert usage is not None
    assert usage.input_tokens == 11
    assert usage.output_tokens == 7


def test_ndjson_event_without_text_leaves_the_raw_transcript_as_output() -> None:
    """A usage-only trailing event must not blank the output."""
    stdout = json.dumps({"type": "result", "usage": {"output_tokens": 3}})
    output, usage = gemini_mod._parse_gemini_stdout(stdout)

    # Single-line stdout parses as a dict on the fast path, so `result`/
    # `output`/`response` are all absent and the output is the empty string.
    assert output == ""
    assert usage is not None
    assert usage.output_tokens == 3


def test_payload_camel_case_usage_aliases_are_summed_into_input_tokens() -> None:
    """camelCase aliases feed the same totals as the snake_case fields."""
    output, usage = gemini_mod._parse_gemini_payload(
        {
            "response": "camel review",
            "usage": {
                "inputTokens": 10,
                "outputTokens": 4,
                "cacheReadTokens": 5,
                "cacheWriteTokens": 2,
            },
        }
    )

    assert output == "camel review"
    assert usage is not None
    assert usage.input_tokens == 17  # 10 + 5 + 2
    assert usage.output_tokens == 4
    assert usage.cache_read_tokens == 5
    assert usage.cache_write_tokens == 2
    assert usage.cost_usd is None


def test_payload_with_cost_only_still_reports_usage() -> None:
    """A cost-bearing payload with no token counts is a usage record, not ``None``."""
    _output, usage = gemini_mod._parse_gemini_payload({"total_cost_usd": 0.25})

    assert usage is not None
    assert usage.cost_usd == pytest.approx(0.25)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cache_read_tokens is None


def test_payload_without_usage_or_cost_reports_no_usage() -> None:
    """No usage and no cost → ``None``, never a zeroed record."""
    output, usage = gemini_mod._parse_gemini_payload({"output": "text only"})
    assert output == "text only"
    assert usage is None


# ---------------------------------------------------------------------------
# write_mcp_config — the empty-deny-list and no-auth-token branches
# ---------------------------------------------------------------------------


def test_settings_omit_exclude_tools_when_nothing_is_denied(tmp_path: Path) -> None:
    """An empty deny list must not emit an empty ``excludeTools`` array.

    An empty array is a different instruction to the CLI than an absent key.
    """
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    settings = _written_settings(gemini_mod.write_mcp_config(ctx))
    server = settings["mcpServers"][MERGECRAFT_MCP_NAME]

    assert "excludeTools" not in server
    assert server["trust"] is True
    assert server["httpUrl"] == ctx.mcp_server_url
    assert settings["context"]["fileName"] == "GEMINI.md"


def test_settings_omit_headers_when_no_mcp_token_was_issued(tmp_path: Path) -> None:
    """A dev run without a per-run MCP token emits no ``headers`` block at all."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    assert not ctx.mcp_auth_token

    settings = _written_settings(gemini_mod.write_mcp_config(ctx))

    assert "headers" not in settings["mcpServers"][MERGECRAFT_MCP_NAME]


def test_settings_carry_the_bearer_header_when_a_token_is_issued(tmp_path: Path) -> None:
    """A per-run token becomes the MCP ``Authorization`` header."""
    from dataclasses import replace

    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        mcp_auth_token="run-token",
    )
    settings = _written_settings(gemini_mod.write_mcp_config(ctx))

    assert settings["mcpServers"][MERGECRAFT_MCP_NAME]["headers"] == {
        "Authorization": "Bearer run-token"
    }


def test_rendered_subagent_block_replaces_the_built_in_roster(tmp_path: Path) -> None:
    """A rendered roster is written verbatim — the default prompts are not appended."""
    from dataclasses import replace

    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        instructions=_instructions("SYSTEM RULES"),
    )
    gemini_mod.write_mcp_config(ctx, subagent_block="ROSTER BLOCK")
    written = (tmp_path / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")

    assert written == "SYSTEM RULES\n\nROSTER BLOCK"
    assert "mergecraft-reviewer" not in written


def _instructions(system: str) -> Any:
    from mergecraft.agents.shared import ResolvedInstructions

    return ResolvedInstructions(system=system, user="review this diff")


def test_default_instruction_text_lists_both_read_only_subagents(tmp_path: Path) -> None:
    """With no rendered roster, the built-in reviewer + verifier prompts are written."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    gemini_mod.write_mcp_config(ctx)
    written = (tmp_path / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")

    assert gemini_mod.REVIEWER_AGENT_NAME in written
    assert gemini_mod.VERIFIER_AGENT_NAME in written
    assert written.startswith("Registered read-only subagents")


# ---------------------------------------------------------------------------
# _run_gemini_once — argv assembly under flag combinations
# ---------------------------------------------------------------------------


def test_argv_omits_model_and_yes_flag_and_adds_resume_for_a_session_continuation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No resolved model + not CI + resume → no ``-m``, no ``-y``, ``--resume latest``."""
    monkeypatch.delenv("CI", raising=False)
    captured: dict[str, Any] = {}

    def _fake_streaming(*, cmd: list[str], ctx: Any, model: str | None) -> Any:
        captured["cmd"] = cmd
        captured["model"] = model
        return gemini_mod.AgentResult(success=True, output="ok")

    monkeypatch.setattr(gemini_mod, "_run_gemini_streaming", _fake_streaming)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_once(
        cli="/usr/bin/gemini",
        prompt="follow up please",
        ctx=ctx,
        mcp_config="",
        continue_session=True,
    )

    cmd = captured["cmd"]
    assert captured["model"] is None
    assert "-m" not in cmd
    assert "-y" not in cmd
    assert cmd[cmd.index("--resume") + 1] == "latest"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "follow up please" in cmd[cmd.index("-p") + 1]
    assert result.success is True


def test_argv_strips_the_provider_prefix_from_the_model_flag(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The CLI receives the bare model id, not the ``provider/model`` specifier."""
    monkeypatch.setenv("CI", "true")
    captured: dict[str, Any] = {}

    def _fake_streaming(*, cmd: list[str], ctx: Any, model: str | None) -> Any:
        captured["cmd"] = cmd
        return gemini_mod.AgentResult(success=True)

    monkeypatch.setattr(gemini_mod, "_run_gemini_streaming", _fake_streaming)
    ctx = make_agent_run_context(tmp_path, resolved_model="google/gemini-3.1-pro")

    gemini_mod._run_gemini_once(cli="gemini", prompt="", ctx=ctx, mcp_config="")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-m") + 1] == "gemini-3.1-pro"
    assert "-y" in cmd


def test_empty_prompt_falls_back_to_the_context_user_instruction(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An empty ``prompt`` argument reuses ``ctx.instructions.user``."""
    monkeypatch.delenv("CI", raising=False)
    captured: dict[str, Any] = {}

    def _fake_streaming(*, cmd: list[str], ctx: Any, model: str | None) -> Any:
        captured["cmd"] = cmd
        return gemini_mod.AgentResult(success=True)

    monkeypatch.setattr(gemini_mod, "_run_gemini_streaming", _fake_streaming)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    gemini_mod._run_gemini_once(cli="gemini", prompt="", ctx=ctx, mcp_config="")

    assert "review this diff" in captured["cmd"][captured["cmd"].index("-p") + 1]


# ---------------------------------------------------------------------------
# _run_gemini_streaming — spawn failure, timeout, non-zero exit
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("disable_tracing")
def test_streaming_returns_a_failed_result_when_the_cli_cannot_be_spawned(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A missing binary is a failed ``AgentResult``, never a raised ``FileNotFoundError``."""

    def _boom(cmd: list[str], **kwargs: object) -> Any:
        del cmd, kwargs
        msg = "no such file: gemini"
        raise FileNotFoundError(msg)

    monkeypatch.setattr(gemini_mod, "spawn_agent_cli", _boom)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_streaming(cmd=["gemini"], ctx=ctx, model=None)

    assert result.success is False
    assert result.error == "no such file: gemini"
    assert result.output is None


@pytest.mark.usefixtures("disable_tracing")
def test_streaming_reports_a_timeout_as_a_clean_failed_result(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``TimeoutExpired`` from the group wait becomes a named failure, not a traceback."""
    monkeypatch.setattr(gemini_mod, "spawn_agent_cli", _spawn(_FakeProcess(stdout="")))

    def _timeout(process: Any, *, timeout: float | None) -> int:
        del process, timeout
        raise subprocess.TimeoutExpired(cmd="gemini", timeout=1)

    monkeypatch.setattr(gemini_mod, "wait_or_kill_process_group", _timeout)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_streaming(cmd=["gemini"], ctx=ctx, model=None)

    assert result.success is False
    assert result.error == "gemini CLI timed out"


@pytest.mark.usefixtures("disable_tracing")
def test_nonzero_exit_with_rate_limit_stderr_is_marked_retryable(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A 429-shaped stderr must set ``metadata['retryable']`` so the chain retries."""
    process = _FakeProcess(
        stdout=json.dumps({"type": "message", "role": "assistant", "content": "partial"}) + "\n",
        stderr="Error: 429 Too Many Requests\n",
        returncode=1,
    )
    monkeypatch.setattr(gemini_mod, "spawn_agent_cli", _spawn(process))
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_streaming(cmd=["gemini"], ctx=ctx, model=None)

    assert result.success is False
    assert result.metadata == {"retryable": True}
    assert result.error == "Error: 429 Too Many Requests"
    # Partial output produced before the failure is preserved for the caller.
    assert result.output == "partial"


@pytest.mark.usefixtures("disable_tracing")
def test_nonzero_exit_without_stderr_names_the_exit_code(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A silent non-zero exit still produces a diagnosable error string."""
    monkeypatch.setattr(
        gemini_mod,
        "spawn_agent_cli",
        _spawn(_FakeProcess(stdout="", stderr="   \n", returncode=7)),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_streaming(cmd=["gemini"], ctx=ctx, model=None)

    assert result.success is False
    assert result.error == "gemini exited 7"
    assert result.metadata == {}
    assert result.output is None


@pytest.mark.usefixtures("disable_tracing")
def test_successful_run_with_no_stream_output_reports_none_not_empty_string(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An empty stream on a clean exit is ``output=None``, not ``""``."""
    monkeypatch.setattr(
        gemini_mod,
        "spawn_agent_cli",
        _spawn(_FakeProcess(stdout="\n\n", stderr="", returncode=0)),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_streaming(cmd=["gemini"], ctx=ctx, model=None)

    assert result.success is True
    assert result.output is None
    assert result.usage is None


@pytest.mark.usefixtures("disable_tracing")
def test_span_cleanup_failure_does_not_fail_an_otherwise_successful_run(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Tracing must never fail a review — a raising ``close_all`` is swallowed."""

    def _handler_factory(**kwargs: object) -> Any:
        del kwargs

        def _handler(accumulator: StreamSpanAccumulator, event: dict[str, Any]) -> None:
            accumulator.set_output(str(event.get("content") or ""))

        def _close_all() -> None:
            msg = "sink already closed"
            raise RuntimeError(msg)

        return _handler, _close_all

    monkeypatch.setattr(gemini_mod, "_gemini_stream_event_handler", _handler_factory)
    monkeypatch.setattr(
        gemini_mod,
        "spawn_agent_cli",
        _spawn(_FakeProcess(stdout=json.dumps({"content": "done"}) + "\n", returncode=0)),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = gemini_mod._run_gemini_streaming(cmd=["gemini"], ctx=ctx, model=None)

    assert result.success is True
    assert result.output == "done"


# ---------------------------------------------------------------------------
# _gemini_stream_event_handler — tracer-disabled branches and guard clauses
# ---------------------------------------------------------------------------


def test_handler_without_a_tracer_still_accumulates_output_and_usage() -> None:
    """Tracing off must not cost the caller its output or token totals."""
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=None, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    for event in (
        {"type": "init"},
        {"type": "message", "role": "assistant", "content": "reviewed"},
        {"type": "tool_use", "id": "t1", "name": "browser", "input": {"q": "x"}},
        {"type": "tool_result", "tool_use_id": "t1", "output": "page"},
        {"type": "result", "usage": {"input_tokens": 9, "output_tokens": 2}},
    ):
        handler(acc, event)
    close_all()

    assert acc.final_output == "reviewed"
    usage = acc.to_usage()
    assert usage is not None
    assert usage.input_tokens == 9
    assert usage.output_tokens == 2


def test_untyped_legacy_blob_event_replaces_accumulated_usage() -> None:
    """An older single-blob event still populates output and authoritative usage."""
    handler, _close = gemini_mod._gemini_stream_event_handler(tracer=None, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")
    acc.absorb_usage({"input_tokens": 500, "output_tokens": 500})

    handler(
        acc,
        {
            "result": "legacy blob answer",
            "usage": {"input_tokens": 12, "output_tokens": 3},
            "total_cost_usd": 0.5,
        },
    )

    assert acc.final_output == "legacy blob answer"
    usage = acc.to_usage()
    assert usage is not None
    assert usage.input_tokens == 12  # replaced, not added to the earlier 500
    assert usage.output_tokens == 3
    assert usage.cost_usd == pytest.approx(0.5)


def test_untyped_event_without_payload_leaves_the_accumulator_untouched() -> None:
    """A typeless heartbeat with no result/usage must not blank prior output."""
    handler, _close = gemini_mod._gemini_stream_event_handler(tracer=None, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")
    acc.set_output("earlier")

    handler(acc, {"noise": True})

    assert acc.final_output == "earlier"
    assert acc.to_usage() is None


def test_non_assistant_message_is_not_taken_as_the_run_output() -> None:
    """A user/system echo must never become the review output."""
    handler, _close = gemini_mod._gemini_stream_event_handler(tracer=None, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "message", "role": "user", "content": "the diff"})
    handler(acc, {"type": "message", "role": "assistant", "content": ""})

    assert acc.final_output is None


def test_tool_use_without_an_id_opens_no_span() -> None:
    """An id-less ``tool_use`` cannot be correlated to a result — it is dropped."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "tool_use", "name": "browser", "input": {"q": "x"}})
    close_all()

    assert _spans(sink, "tool.call") == []


def test_duplicate_tool_use_id_does_not_open_a_second_span() -> None:
    """A replayed ``tool_use`` must not leak a second, never-closed span."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "tool_use", "id": "t1", "name": "browser"})
    handler(acc, {"type": "tool_use", "id": "t1", "name": "shell"})
    handler(acc, {"type": "tool_result", "tool_use_id": "t1", "output": "ok"})
    close_all()

    tool_calls = _spans(sink, "tool.call")
    assert len(tool_calls) == 1
    assert tool_calls[0].attrs["tool.name"] == "browser"
    # No ``input`` on the event → no request payload attrs are invented.
    assert "tool.input" not in tool_calls[0].attrs


def test_tool_result_for_an_unknown_id_is_ignored() -> None:
    """An orphan ``tool_result`` closes nothing and emits nothing."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "tool_result", "tool_use_id": "never-opened", "output": "ok"})
    close_all()

    assert _spans(sink, "tool.call") == []


def test_error_event_closes_open_tool_spans_and_surfaces_the_message() -> None:
    """A provider error closes the in-flight tool span and becomes the output."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(acc, {"type": "tool_use", "id": "t1", "name": "browser"})
    handler(acc, {"type": "error", "message": "provider refused the request"})
    close_all()

    assert acc.final_output == "provider refused the request"
    assert len(_spans(sink, "tool.call")) == 1
    # The init-opened provider/llm pair is closed by the error path too, so
    # close_all() has nothing left to emit and cannot double-close.
    assert len(_spans(sink, "provider.call")) == 1
    assert len(_spans(sink, "llm.call")) == 1


def test_error_event_with_a_non_string_message_leaves_output_untouched() -> None:
    """A structured error body is not coerced into the review output."""
    handler, _close = gemini_mod._gemini_stream_event_handler(tracer=None, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")
    acc.set_output("earlier answer")

    handler(acc, {"type": "error", "message": {"code": 500}})

    assert acc.final_output == "earlier answer"


def test_result_event_ignores_a_non_mapping_usage_and_non_string_response() -> None:
    """Malformed terminal fields degrade to "no usage recorded", not a crash."""
    handler, _close = gemini_mod._gemini_stream_event_handler(tracer=None, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")
    acc.set_output("earlier answer")

    handler(acc, {"type": "result", "usage": "n/a", "response": {"text": "nope"}})

    assert acc.final_output == "earlier answer"
    assert acc.to_usage() is None


def test_result_event_closes_the_pair_and_records_the_terminal_response() -> None:
    """The terminal event closes exactly one provider/llm pair and sets the output."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(acc, {"type": "result", "usage": {"input_tokens": 40}, "response": "done"})
    close_all()

    llm_spans = _spans(sink, "llm.call")
    assert len(llm_spans) == 1
    assert llm_spans[0].attrs["gen_ai.request.model"] == "gemini-3"
    assert llm_spans[0].attrs["gen_ai.system"] == "google"
    assert acc.final_output == "done"
    accumulated = acc.to_usage()
    assert accumulated is not None
    assert accumulated.input_tokens == 40


def test_close_all_closes_spans_left_open_by_a_truncated_stream() -> None:
    """A stream that dies mid-tool still emits its open spans exactly once."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(acc, {"type": "tool_use", "id": "t1", "name": "browser"})
    close_all()

    assert len(_spans(sink, "tool.call")) == 1
    assert len(_spans(sink, "provider.call")) == 1
    assert len(_spans(sink, "llm.call")) == 1


def test_assistant_message_is_not_captured_without_a_capture_policy() -> None:
    """``capture_policy=None`` keeps message bodies off the span (pre-OB3 surface)."""
    sink, tracer = _tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(
        tracer=tracer, model_id="gemini-3", capture_policy=None
    )
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(acc, {"type": "message", "role": "assistant", "content": "secret body"})
    handler(acc, {"type": "result"})
    close_all()

    attrs = _spans(sink, "llm.call")[0].attrs
    assert not any(key.startswith("gen_ai.output.messages") for key in attrs)
    assert acc.final_output == "secret body"
