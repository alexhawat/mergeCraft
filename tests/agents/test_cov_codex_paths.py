"""Error, fallback and guard-clause paths of the Codex harness (issue #431).

Every test here drives the *second* way out of a decision in
``mergecraft.agents.codex``: a failing subprocess, an unusable credential, a
skipped fallback candidate, or a malformed provider stream.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from loguru import logger
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import codex as codex_module
from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.agents.codex_stream import codex_stream_event_handler, parse_codex_payload
from mergecraft.tracing.content import ContentCapture
from mergecraft.tracing.sinks import MemorySink
from mergecraft.tracing.tracer import Tracer
from mergecraft.types import MERGECRAFT_MCP_NAME, MERGECRAFT_VERIFIER_MCP_NAME

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from mergecraft.agents.shared import AgentRunContext

_HOME_PARENT_ENV = ("MERGECRAFT_CODEX_HOME_PARENT", "RUNNER_TEMP", "GITHUB_WORKSPACE")


class _FakeProcess:
    """``subprocess.Popen`` stand-in delivering a recorded stdout/stderr pair."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        timeout: bool = False,
    ) -> None:
        self.stdout: list[str] = stdout.splitlines(keepends=True)
        self.stderr: Any = self
        self._stderr_text = stderr
        self._returncode = returncode
        self._timeout = timeout
        self.pid = None

    def read(self) -> str:
        return self._stderr_text

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self._timeout:
            raise subprocess.TimeoutExpired(cmd="codex", timeout=1)
        return self._returncode


def _capture_logs() -> tuple[list[tuple[str, str]], int]:
    records: list[tuple[str, str]] = []

    def _sink(record: Any) -> None:
        entry = record.record
        records.append((entry["level"].name, entry["message"]))

    return records, logger.add(_sink, level="DEBUG")


def _clear_home_parent_env(monkeypatch: MonkeyPatch) -> None:
    for key in (*_HOME_PARENT_ENV, "XDG_CACHE_HOME"):
        monkeypatch.delenv(key, raising=False)


def _pin_forbidden_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Treat only ``tmp_path/forbidden-tmp`` as world-writable.

    Pytest's ``tmp_path`` lives under ``/tmp`` on GitHub Actions, so the
    production forbidden-root list would also reject a *safe* candidate
    placed next to it. A synthetic root keeps both sides of the ladder
    inside ``tmp_path``.
    """
    root = tmp_path / "forbidden-tmp"
    root.mkdir()
    monkeypatch.setattr(codex_module, "_FORBIDDEN_TEMP_ROOTS", (str(root),))
    return root


def _temp_rooted_ctx(tmp_path: Path, *, tmpdir: Path | None = None) -> AgentRunContext:
    """Context whose tmpdir sits under a forbidden temp root."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    ctx.tmpdir = str(tmpdir) if tmpdir is not None else "/tmp/mergecraft-cov431-run"
    return ctx


# ---------------------------------------------------------------------------
# $CODEX_HOME relocation — the fallback ladder when tmpdir is world-writable
# ---------------------------------------------------------------------------


def test_codex_home_keeps_run_tmpdir_when_it_is_not_world_writable(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A tmpdir outside a forbidden root needs no relocation: home is ``<tmpdir>/.codex``."""
    monkeypatch.setattr(codex_module, "_FORBIDDEN_TEMP_ROOTS", ())
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    assert codex_module._codex_home(ctx) == tmp_path / ".codex"


def test_codex_home_parent_skips_env_candidate_that_is_also_world_writable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A forbidden-root override is rejected, not used: Codex would refuse it too."""
    _clear_home_parent_env(monkeypatch)
    forbidden = _pin_forbidden_root(tmp_path, monkeypatch)
    run_dir = forbidden / "mergecraft-cov431-run"
    run_dir.mkdir()
    override = forbidden / "still-world-writable"
    override.mkdir()
    safe = tmp_path / "runner-temp"
    monkeypatch.setenv("MERGECRAFT_CODEX_HOME_PARENT", str(override))
    monkeypatch.setenv("RUNNER_TEMP", str(safe))

    resolved = codex_module._safe_codex_home_parent(_temp_rooted_ctx(tmp_path, tmpdir=run_dir))

    assert resolved == safe / "mergecraft-cov431-run"


def test_codex_home_parent_skips_candidate_whose_mkdir_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """An unusable override (its parent is a regular file) falls through to the next key."""
    _clear_home_parent_env(monkeypatch)
    forbidden = _pin_forbidden_root(tmp_path, monkeypatch)
    run_dir = forbidden / "mergecraft-cov431-run"
    run_dir.mkdir()
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("regular file", encoding="utf-8")
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("MERGECRAFT_CODEX_HOME_PARENT", str(blocker / "child"))
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))

    resolved = codex_module._safe_codex_home_parent(_temp_rooted_ctx(tmp_path, tmpdir=run_dir))

    assert resolved == workspace / "mergecraft-cov431-run"
    assert workspace.is_dir()


def test_codex_home_parent_falls_back_to_xdg_cache_when_no_override_is_set(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """With every override empty, home lands under ``$XDG_CACHE_HOME/mergecraft``."""
    _clear_home_parent_env(monkeypatch)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("RUNNER_TEMP", "   ")

    resolved = codex_module._safe_codex_home_parent(_temp_rooted_ctx(tmp_path))

    assert resolved == tmp_path / "cache" / "mergecraft" / "mergecraft-cov431-run"
    assert (tmp_path / "cache" / "mergecraft").is_dir()


# ---------------------------------------------------------------------------
# Credential resolution — malformed, partial and absent CODEX_AUTH_JSON
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("not json at all", None),
        ('["refresh_token"]', None),
        ('{"tokens": {"refresh_token": "rt-nested"}}', "rt-nested"),
        ('{"tokens": {"refresh": "rt-alias"}}', "rt-alias"),
        ('{"tokens": {"refresh_token": ""}, "refresh": "rt-top"}', "rt-top"),
        ('{"refresh_token": "rt-flat"}', "rt-flat"),
        ('{"tokens": {"access_token": "at"}}', None),
        ('{"refresh_token": 12345}', None),
    ],
)
def test_extract_refresh_token_shapes(raw: str, expected: str | None) -> None:
    """Refresh extraction reads nested tokens, top-level aliases, and rejects non-strings."""
    assert codex_module._extract_refresh_token(raw) == expected


@pytest.mark.parametrize(
    ("raw", "usable"),
    [
        ("{not json", False),
        ('"a string"', False),
        ("{}", False),
        ('{"tokens": {}}', False),
        ('{"tokens": {"access_token": "   "}}', False),
        ('{"tokens": {"access": "at"}}', True),
        ('{"access_token": "at"}', True),
        ('{"refresh_token": "rt"}', True),
    ],
)
def test_codex_subscription_auth_usable_shapes(raw: str, usable: bool) -> None:
    """Only JSON objects carrying a non-blank access/refresh token count as usable."""
    assert codex_module._codex_subscription_auth_usable(raw) is usable


def test_setup_codex_auth_writes_auth_json_and_records_writeback_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Usable subscription JSON is persisted and its refresh token recorded for post-run."""
    state_file = tmp_path / "github-state"
    state_file.write_text("", encoding="utf-8")
    raw = json.dumps({"tokens": {"refresh_token": "rt-1", "access_token": "at-1"}})
    monkeypatch.setenv(codex_module.CODEX_AUTH_ENV, raw)
    monkeypatch.setenv("GITHUB_STATE", str(state_file))
    monkeypatch.setenv("STATE_codex_writeback", "")

    codex_home = tmp_path / "home"
    codex_module._setup_codex_auth(
        make_agent_run_context(tmp_path, resolved_model=None), codex_home=codex_home
    )

    assert json.loads((codex_home / "auth.json").read_text(encoding="utf-8")) == json.loads(raw)
    line = state_file.read_text(encoding="utf-8").strip()
    assert line.startswith("codex_writeback=")
    payload = json.loads(line.removeprefix("codex_writeback="))
    assert payload == {
        "authPath": str(codex_home / "auth.json"),
        "originalRefresh": "rt-1",
    }
    import os

    assert json.loads(os.environ["STATE_codex_writeback"]) == payload  # noqa: SIM112


def test_setup_codex_auth_skips_writeback_when_auth_has_no_refresh_token(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Access-token-only auth is written, but nothing is staged for the post-run writeback."""
    state_file = tmp_path / "github-state"
    state_file.write_text("", encoding="utf-8")
    monkeypatch.setenv(codex_module.CODEX_AUTH_ENV, '{"access_token": "at-only"}')
    monkeypatch.setenv("GITHUB_STATE", str(state_file))

    codex_home = tmp_path / "home"
    codex_module._setup_codex_auth(
        make_agent_run_context(tmp_path, resolved_model=None), codex_home=codex_home
    )

    assert (codex_home / "auth.json").read_text(encoding="utf-8") == '{"access_token": "at-only"}'
    assert state_file.read_text(encoding="utf-8") == ""


def test_setup_codex_auth_warns_and_writes_nothing_for_unusable_auth_json(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A set-but-unusable ``CODEX_AUTH_JSON`` must not produce an ``auth.json`` Codex rejects."""
    monkeypatch.setenv(codex_module.CODEX_AUTH_ENV, "{}")
    monkeypatch.setenv(codex_module.OPENAI_API_KEY_ENV, "sk-test")
    records, sink_id = _capture_logs()
    codex_home = tmp_path / "home"
    try:
        codex_module._setup_codex_auth(
            make_agent_run_context(tmp_path, resolved_model=None), codex_home=codex_home
        )
    finally:
        logger.remove(sink_id)

    assert not (codex_home / "auth.json").exists()
    assert any(
        level == "WARNING" and codex_module.CODEX_AUTH_ENV in message for level, message in records
    )
    assert any(
        level == "INFO" and codex_module.OPENAI_API_KEY_ENV in message for level, message in records
    )


# ---------------------------------------------------------------------------
# Sandbox selection — operator override, typos, and shell mode
# ---------------------------------------------------------------------------


def test_unrecognised_sandbox_override_is_ignored_with_a_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A typo must not widen the sandbox: the value is dropped, not passed through."""
    monkeypatch.setenv(codex_module.CODEX_SANDBOX_ENV, "danger-full-acces")
    records, sink_id = _capture_logs()
    try:
        override = codex_module._operator_sandbox_override()
        mode = codex_module._sandbox_mode(make_agent_run_context(tmp_path, resolved_model=None))
    finally:
        logger.remove(sink_id)

    assert override is None
    assert mode == "read-only"
    assert any(level == "WARNING" and "ignoring" in message for level, message in records)


def test_operator_sandbox_override_accepts_the_documented_value(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """The documented opt-out (case-insensitive) disables the nested sandbox."""
    monkeypatch.setenv(codex_module.CODEX_SANDBOX_ENV, "DANGER-FULL-ACCESS")

    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    assert codex_module._sandbox_mode(ctx) == codex_module.CODEX_SANDBOX_UNSANDBOXED
    assert codex_module._codex_use_permission_profiles(ctx) is False


def test_shell_enabled_selects_workspace_write_sandbox(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """shell=enabled + MCP → workspace-write with network access, not permission profiles."""
    monkeypatch.delenv(codex_module.CODEX_SANDBOX_ENV, raising=False)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    ctx.payload.shell = "enabled"

    config = tomllib.loads(
        Path(codex_module.write_mcp_config(ctx)).read_text(encoding="utf-8"),
    )

    assert config["sandbox_mode"] == "workspace-write"
    assert config["sandbox_workspace_write"] == {"network_access": True}
    assert "permissions" not in config


def test_write_mcp_config_without_mcp_url_emits_no_server_table(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """No MCP endpoint → legacy read-only sandbox, no server table, no tool preamble."""
    monkeypatch.delenv(codex_module.CODEX_SANDBOX_ENV, raising=False)
    monkeypatch.setenv("CI", "true")
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    ctx.mcp_server_url = ""
    ctx.instructions.system = "SYSTEM PROMPT MARKER"

    config_path = Path(codex_module.write_mcp_config(ctx))
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    instructions = (config_path.parent / "mergecraft-instructions.md").read_text(encoding="utf-8")

    assert config["sandbox_mode"] == "read-only"
    assert config["approval_policy"] == "never"
    assert "mcp_servers" not in config
    assert "sandbox_workspace_write" not in config
    assert instructions.startswith("SYSTEM PROMPT MARKER")
    assert "mergeCraft MCP tools (Codex)" not in instructions


def test_write_mcp_config_outside_ci_keeps_on_request_approval(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Off the Action path, approvals stay interactive rather than silently ``never``."""
    monkeypatch.delenv("CI", raising=False)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    config = tomllib.loads(
        Path(codex_module.write_mcp_config(ctx)).read_text(encoding="utf-8"),
    )

    assert config["approval_policy"] == "on-request"
    assert config["mcp_servers"][MERGECRAFT_MCP_NAME]["url"].endswith("/mcp/reviewer")
    assert config["mcp_servers"][MERGECRAFT_VERIFIER_MCP_NAME]["url"].endswith("/mcp/verifier")


def test_empty_custom_provider_env_does_not_emit_a_model_providers_table(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A set-but-empty singleton gateway var is not a configured provider."""
    monkeypatch.setenv(codex_module.CUSTOM_PROVIDER_BASE_URL_ENV, "")
    monkeypatch.setenv(codex_module.CUSTOM_PROVIDER_API_KEY_ENV, "   ")

    assert codex_module._has_any_custom_provider_env() is False

    config = tomllib.loads(
        Path(
            codex_module.write_mcp_config(make_agent_run_context(tmp_path, resolved_model=None))
        ).read_text(encoding="utf-8"),
    )

    assert "model_providers" not in config


# ---------------------------------------------------------------------------
# TOML rendering — hostile values from consumer-supplied env vars
# ---------------------------------------------------------------------------


def test_render_toml_escapes_control_characters_so_the_file_still_parses() -> None:
    """A control char in a consumer-supplied value must not produce unparseable TOML."""
    rendered = "\n".join(
        codex_module._render_toml(
            {"model_providers": {"gw": {"base_url": 'https://x/\n\t\x07\x7f"q"\\'}}}
        )
    )

    assert tomllib.loads(rendered)["model_providers"]["gw"]["base_url"] == (
        'https://x/\n\t\x07\x7f"q"\\'
    )


def test_render_toml_keeps_scalars_under_their_own_table_header() -> None:
    """Scalars declared after a nested table stay in the parent table (#222)."""
    rendered = "\n".join(
        codex_module._render_toml(
            {
                "permissions": {
                    "network": {"enabled": True},
                    "extends": ":read-only",
                    "dotted.key": "quoted",
                }
            }
        )
    )

    assert tomllib.loads(rendered) == {
        "permissions": {
            "extends": ":read-only",
            "dotted.key": "quoted",
            "network": {"enabled": True},
        }
    }


# ---------------------------------------------------------------------------
# Legacy stdout parsing — empty, non-object and partially malformed streams
# ---------------------------------------------------------------------------


def test_parse_codex_stdout_returns_no_usage_for_an_empty_stream() -> None:
    """An empty stream is not a zero-token run — usage stays ``None``."""
    assert codex_module._parse_codex_stdout("   \n  ") == ("", None)


def test_parse_codex_stdout_keeps_raw_text_when_the_blob_is_not_an_object() -> None:
    """A JSON array is not a result payload; the raw text survives as the output."""
    output, usage = codex_module._parse_codex_stdout("[1, 2]")

    assert output == "[1, 2]"
    assert usage is None


def test_parse_codex_stdout_skips_malformed_lines_and_reads_the_terminal_event() -> None:
    """Non-JSON noise and non-object lines are skipped; the last event wins."""
    stdout = "\n".join(
        [
            "not json",
            "[]",
            "",
            json.dumps({"type": "message", "content": "ignored earlier message"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "result": "final answer",
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 5},
                    "total_cost_usd": 0.25,
                }
            ),
        ]
    )

    output, usage = codex_module._parse_codex_stdout(stdout)

    assert output == "final answer"
    assert usage is not None
    assert usage.input_tokens == 15
    assert usage.cache_read_tokens == 5
    assert usage.cost_usd == 0.25


def test_parse_codex_payload_reports_cost_only_runs() -> None:
    """A payload with cost but no token counts still yields usage, not ``None``."""
    output, usage = parse_codex_payload({"message": "done", "total_cost_usd": 0.5})

    assert output == "done"
    assert usage is not None
    assert usage.cost_usd == 0.5
    assert usage.input_tokens == 0
    assert usage.cache_read_tokens is None


# ---------------------------------------------------------------------------
# Subprocess failure handling
# ---------------------------------------------------------------------------


def _run_once(
    ctx: AgentRunContext,
    monkeypatch: MonkeyPatch,
    process: _FakeProcess | Exception,
    *,
    continue_session: bool = False,
) -> tuple[Any, list[list[str]]]:
    captured: list[list[str]] = []

    def _fake_spawn(cmd: list[str], **kwargs: object) -> Any:
        captured.append(list(cmd))
        if isinstance(process, Exception):
            raise process
        return process

    monkeypatch.setattr(codex_module, "spawn_agent_cli", _fake_spawn)
    result = codex_module._run_codex_once(
        cli="/usr/bin/codex",
        prompt="",
        ctx=ctx,
        mcp_config="unused",
        continue_session=continue_session,
    )
    return result, captured


def test_missing_codex_binary_surfaces_the_spawn_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A missing binary is a failed result carrying the OS error, not an exception."""
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        FileNotFoundError("no such file: codex"),
    )

    assert result.success is False
    assert result.error == "no such file: codex"
    assert result.output is None


def test_nonzero_exit_without_stderr_names_the_exit_code(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """With no stderr to quote, the error still identifies the failing exit code."""
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout="", stderr="   \n", returncode=3),
    )

    assert result.success is False
    assert result.error == "codex exited 3"
    assert result.metadata == {}


def test_rate_limited_exit_is_marked_retryable_and_keeps_partial_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A 429 exit must be flagged retryable so the chain re-dispatches instead of failing."""
    stdout = json.dumps({"type": "message.completed", "message": {"content": "partial review"}})
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout=stdout, stderr="429 Too Many Requests", returncode=1),
    )

    assert result.success is False
    assert result.metadata == {"retryable": True}
    assert result.error == "429 Too Many Requests"
    assert result.output == "partial review"


def test_nested_sandbox_failure_adds_the_operator_remedy(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """bubblewrap's namespace error is environmental — the error must say how to fix it."""
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(
            stdout="",
            stderr="bwrap: No permissions to create a new namespace",
            returncode=1,
        ),
    )

    assert result.success is False
    assert result.error is not None
    assert codex_module.CODEX_SANDBOX_ENV in result.error
    assert codex_module.CODEX_SANDBOX_UNSANDBOXED in result.error
    assert "No permissions to create a new namespace" in result.error
    assert result.error.startswith("Codex could not start its Linux platform sandbox")


def test_codex_timeout_returns_a_timeout_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A hung CLI is reported as a timeout rather than raising into the review loop."""
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout="", stderr="", returncode=0, timeout=True),
    )

    assert result.success is False
    assert result.error == "codex CLI timed out"
    assert result.usage is None


def test_clean_exit_with_no_events_reports_success_and_no_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """An empty-but-clean stream yields ``output=None``, never an empty-string review."""
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout="\n \n", stderr="", returncode=0),
    )

    assert result.success is True
    assert result.output is None
    assert result.usage is None


def test_resume_argv_omits_model_and_carries_the_sandbox_flag(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Without a resolved model and without MCP, argv resumes the last session bare."""
    monkeypatch.delenv(codex_module.CODEX_SANDBOX_ENV, raising=False)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    ctx.mcp_server_url = ""
    ctx.instructions.user = "fallback prompt"

    _, captured = _run_once(
        ctx,
        monkeypatch,
        _FakeProcess(stdout="", stderr="", returncode=0),
        continue_session=True,
    )

    assert captured[0] == [
        "/usr/bin/codex",
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "resume",
        "--last",
        "fallback prompt",
    ]


def test_permission_profile_runs_omit_the_sandbox_flag(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Read-only + MCP is owned by the config profile: ``--sandbox`` must not be passed."""
    monkeypatch.delenv(codex_module.CODEX_SANDBOX_ENV, raising=False)
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")

    _, captured = _run_once(ctx, monkeypatch, _FakeProcess(stdout="", stderr="", returncode=0))

    assert "--sandbox" not in captured[0]
    assert captured[0][:6] == [
        "/usr/bin/codex",
        "exec",
        "--json",
        "--model",
        "gpt-5.3-codex",
        "review this diff",
    ]


# ---------------------------------------------------------------------------
# CLI discovery
# ---------------------------------------------------------------------------


async def test_install_falls_back_to_a_locally_installed_binary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """No ``codex`` on PATH → the node_modules binary under the temp dir is used."""
    monkeypatch.setattr(codex_module.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(tmp_path))
    local = tmp_path / "node_modules" / ".bin" / "codex"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n", encoding="utf-8")

    assert await codex_module._install(None) == str(local)


async def test_install_raises_an_actionable_error_when_no_binary_exists(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """With no binary anywhere, the error names the package to install."""
    monkeypatch.setattr(codex_module.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(tmp_path))

    with pytest.raises(FileNotFoundError, match="@openai/codex"):
        await codex_module._install(None)


# ---------------------------------------------------------------------------
# NDJSON event handler — tracer-live and tracer-absent decision paths
# ---------------------------------------------------------------------------


def _events_of(sink: MemorySink, kind: str) -> list[dict[str, Any]]:
    return [event.attrs for event in sink.events if event.kind == kind]


def _handler_with_tracer(
    *,
    capture_policy: ContentCapture | None = None,
) -> tuple[Any, Any, MemorySink, StreamSpanAccumulator]:
    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="session-431", run_id="run-431")
    handler, close_all = codex_stream_event_handler(
        tracer=tracer,
        model_id="gpt-5.3-codex",
        capture_policy=capture_policy,
    )
    return handler, close_all, sink, StreamSpanAccumulator(agent_name="codex")


def test_handler_without_a_tracer_still_accumulates_output_and_usage() -> None:
    """Tracing off must not cost the run its output: the accumulator is still fed."""
    handler, close_all = codex_stream_event_handler(
        tracer=None,
        model_id="gpt-5.3-codex",
    )
    accumulator = StreamSpanAccumulator(agent_name="codex")

    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(accumulator, {"type": "item.started", "item": {"type": "tool_call", "id": "c1"}})
    handler(accumulator, {"type": "message.completed", "message": {"content": "verdict"}})
    handler(
        accumulator,
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 7, "output_tokens": 3},
            "total_cost_usd": 0.125,
        },
    )
    close_all()

    usage = accumulator.to_usage()
    assert accumulator.final_output == "verdict"
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (7, 3, 0.125)


def test_handler_reads_a_legacy_untyped_result_blob() -> None:
    """A pre-streaming single-blob payload (no ``type``) still yields output and usage."""
    handler, close_all = codex_stream_event_handler(
        tracer=None,
        model_id="gpt-5.3-codex",
    )
    accumulator = StreamSpanAccumulator(agent_name="codex")

    handler(
        accumulator,
        {"result": "legacy verdict", "usage": {"input_tokens": 4, "output_tokens": 2}},
    )
    close_all()

    usage = accumulator.to_usage()
    assert accumulator.final_output == "legacy verdict"
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (4, 2)


def test_tool_call_span_carries_the_name_and_input_from_the_completed_event() -> None:
    """codex sends the tool input on ``item.completed``; the span must pick it up there."""
    handler, close_all, sink, accumulator = _handler_with_tracer()

    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(
        accumulator,
        {"type": "item.started", "item": {"type": "tool_call", "id": "call-1", "name": "shell"}},
    )
    handler(
        accumulator,
        {
            "type": "item.completed",
            "item": {
                "type": "tool_call",
                "id": "call-1",
                "name": "mergecraft_checkout_pr",
                "input": '{"pr": 431}',
            },
        },
    )
    handler(accumulator, {"type": "item.completed", "item": {"type": "tool_result", "id": "x"}})
    close_all()

    tool_spans = _events_of(sink, "tool.call")
    assert len(tool_spans) == 1
    attrs = tool_spans[0]
    assert attrs["tool.name"] == "mergecraft_checkout_pr"
    assert attrs["gen_ai.tool.name"] == "mergecraft_checkout_pr"
    assert attrs["gen_ai.tool.call.id"] == "call-1"
    assert attrs["tool.input"] == '{"pr": 431}'


def test_tool_call_without_an_id_opens_no_span() -> None:
    """An id-less tool_call cannot be correlated to its result — it must be dropped."""
    handler, close_all, sink, accumulator = _handler_with_tracer()

    handler(accumulator, {"type": "item.started", "item": {"type": "tool_call", "name": "shell"}})
    handler(accumulator, {"type": "item.started", "item": "not-a-dict"})
    handler(accumulator, {"type": "item.started", "item": {"type": "reasoning"}})
    close_all()

    assert _events_of(sink, "tool.call") == []


def test_completed_tool_call_with_no_open_span_is_ignored() -> None:
    """A completion for a tool call we never saw start must not fabricate a span."""
    handler, close_all, sink, accumulator = _handler_with_tracer()

    handler(
        accumulator,
        {"type": "item.completed", "item": {"type": "tool_call", "id": "ghost"}},
    )
    close_all()

    assert _events_of(sink, "tool.call") == []


def test_repeated_thread_started_does_not_open_a_second_llm_span() -> None:
    """One thread means one ``llm.call`` row, however many ``thread.started`` events arrive."""
    handler, close_all, sink, accumulator = _handler_with_tracer()

    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(accumulator, {"type": "turn.completed", "usage": {"input_tokens": 1}})
    close_all()

    llm_spans = _events_of(sink, "llm.call")
    assert len(llm_spans) == 1
    assert llm_spans[0]["gen_ai.request.model"] == "gpt-5.3-codex"
    assert llm_spans[0]["mergecraft.reasoning_effort"] == "high"
    assert len(_events_of(sink, "provider.call")) == 1


def test_turn_completed_records_reasoning_tokens_and_replaces_usage() -> None:
    """Reasoning tokens are usage metadata and must survive onto the llm span."""
    handler, close_all, sink, accumulator = _handler_with_tracer()
    accumulator.absorb_usage({"input_tokens": 999})

    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(
        accumulator,
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 20,
                "output_tokens": 5,
                "output_tokens_details": {"reasoning_tokens": 4},
            },
            "total_cost_usd": 0.75,
        },
    )
    close_all()

    usage = accumulator.to_usage()
    assert usage is not None
    assert usage.input_tokens == 20
    assert usage.cost_usd == 0.75
    assert _events_of(sink, "llm.call")[0]["mergecraft.usage.reasoning_tokens"] == 4


def test_turn_completed_ignores_a_cost_without_usage() -> None:
    """A cost with no usage payload is not authoritative and must not be recorded."""
    handler, close_all, _sink, accumulator = _handler_with_tracer()

    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(accumulator, {"type": "turn.completed", "total_cost_usd": 9.99})
    close_all()

    assert accumulator.cost_usd is None


def test_reasoning_and_output_are_captured_only_under_a_content_policy() -> None:
    """``capture_policy=None`` keeps payload attrs off the span; FULL turns them on."""
    handler, close_all, sink, accumulator = _handler_with_tracer(capture_policy=None)
    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(
        accumulator,
        {"type": "item.completed", "item": {"type": "reasoning", "text": "secret plan"}},
    )
    handler(accumulator, {"type": "message.completed", "message": {"content": "verdict"}})
    handler(accumulator, {"type": "turn.completed", "usage": {"input_tokens": 1}})
    close_all()

    ungated = _events_of(sink, "llm.call")[0]
    assert "mergecraft.thinking" not in ungated
    assert "gen_ai.output.messages" not in ungated

    handler, close_all, sink, accumulator = _handler_with_tracer(capture_policy=ContentCapture.FULL)
    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(
        accumulator,
        {"type": "item.completed", "item": {"type": "reasoning", "text": "secret plan"}},
    )
    handler(accumulator, {"type": "item.completed", "item": {"type": "reasoning", "text": 17}})
    handler(accumulator, {"type": "message.completed", "message": {"content": "verdict"}})
    handler(accumulator, {"type": "turn.completed", "usage": {"input_tokens": 1}})
    close_all()

    gated = _events_of(sink, "llm.call")[0]
    assert gated["mergecraft.thinking"] == "secret plan"
    assert "verdict" in json.dumps(gated["gen_ai.output.messages"])
    assert accumulator.final_output == "verdict"


def test_empty_message_completed_does_not_overwrite_the_output() -> None:
    """A blank ``message.completed`` must not erase the text already accumulated."""
    handler, close_all, _sink, accumulator = _handler_with_tracer()

    handler(accumulator, {"type": "message.completed", "message": {"content": "real verdict"}})
    handler(accumulator, {"type": "message.completed", "message": {"content": ""}})
    handler(accumulator, {"type": "message.completed", "message": "not-a-dict"})
    close_all()

    assert accumulator.final_output == "real verdict"


def test_close_all_flushes_spans_left_open_by_a_truncated_stream() -> None:
    """A stream that dies mid-tool-call still emits both spans, not a silent gap."""
    handler, close_all, sink, accumulator = _handler_with_tracer()

    handler(accumulator, {"type": "thread.started", "thread_id": "t1"})
    handler(
        accumulator,
        {"type": "item.started", "item": {"type": "tool_call", "id": "call-1", "name": "shell"}},
    )
    assert _events_of(sink, "tool.call") == []

    close_all()

    assert [attrs["tool.name"] for attrs in _events_of(sink, "tool.call")] == ["shell"]
    assert len(_events_of(sink, "llm.call")) == 1


def test_error_event_message_is_captured_from_stdout() -> None:
    """#445 — Codex reports fatal failures as stdout events, not on stderr.

    The handler had no branch for them, so the message was counted into
    ``parsed_event_count`` and dropped. PR #443 then reported an unrelated
    stderr line ("Reading additional input from stdin...") as the run's error,
    hiding a quota exhaustion.
    """
    handler, _close_all = codex_stream_event_handler(
        tracer=None,
        model_id="gpt-5.3-codex",
    )
    accumulator = StreamSpanAccumulator(agent_name="codex")
    quota = "You've hit your usage limit. Upgrade to Pro or try again at Aug 27th."

    handler(accumulator, {"type": "error", "message": quota})

    assert accumulator.stream_error == quota


def test_turn_failed_nested_error_message_is_captured() -> None:
    """``turn.failed`` nests the message under ``error``, unlike ``error``."""
    handler, _close_all = codex_stream_event_handler(
        tracer=None,
        model_id="gpt-5.3-codex",
    )
    accumulator = StreamSpanAccumulator(agent_name="codex")

    handler(accumulator, {"type": "turn.failed", "error": {"message": "boom"}})

    assert accumulator.stream_error == "boom"


def test_the_first_stream_error_wins() -> None:
    """A turn emits ``error`` then ``turn.failed`` for the same cause; the
    run's reason should not be overwritten by the echo.
    """
    handler, _close_all = codex_stream_event_handler(
        tracer=None,
        model_id="gpt-5.3-codex",
    )
    accumulator = StreamSpanAccumulator(agent_name="codex")

    handler(accumulator, {"type": "error", "message": "first"})
    handler(accumulator, {"type": "turn.failed", "error": {"message": "second"}})

    assert accumulator.stream_error == "first"


def test_a_captured_quota_error_classifies_as_retryable() -> None:
    """The captured message must reach classification, not just the log.

    Together with #444 this is what lets a quota wall fail over to the next
    model instead of terminating the run.
    """
    from mergecraft.utils.retry_policy import is_retryable_cli_failure

    handler, _close_all = codex_stream_event_handler(
        tracer=None,
        model_id="gpt-5.3-codex",
    )
    accumulator = StreamSpanAccumulator(agent_name="codex")
    handler(
        accumulator,
        {"type": "error", "message": "You've hit your usage limit."},
    )

    # The driver classifies against the stream error joined with stderr; stderr
    # here is the benign chatter that used to be the only signal.
    assert (
        is_retryable_cli_failure(
            returncode=1,
            stderr=f"{accumulator.stream_error}\nReading additional input from stdin...",
        )
        is True
    )
