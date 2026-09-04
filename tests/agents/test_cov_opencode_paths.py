"""Error, guard, and fallback paths in ``mergecraft.agents.opencode``.

The existing opencode suite pins the happy paths: a provider block built
from well-formed env, a 200 session response, a clean exit. This module
drives the other way out of each decision — the serve boot failing, the
HTTP session endpoint 4xx-ing, the CLI fallback exiting non-zero or timing
out, and every numeric/model guard that currently only ever sees valid input.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import opencode as oc
from mergecraft.agents.openai_compatible_gateways import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    ProviderConfig,
)
from mergecraft.tracing.genai import ModelParams
from mergecraft.types import MERGECRAFT_MCP_NAME

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_BASE_URL = "https://gateway.example.com/v1"


@pytest.fixture(autouse=True)
def _clear_gateway_env(monkeypatch: MonkeyPatch) -> None:
    """Keep operator gateway env out of every case in this module."""
    for name in (
        CUSTOM_PROVIDER_BASE_URL_ENV,
        CUSTOM_PROVIDER_API_KEY_ENV,
        "NOUS_API_KEY",
        "NOUS_BASE_URL",
        "TOKENHUB_API_KEY",
        "TOKENHUB_BASE_URL",
        "BEDROCK_MODEL_ID",
        "VERTEX_MODEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    for index in range(1, 8):
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{index}", raising=False)
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{index}", raising=False)


def _config(**overrides: Any) -> ProviderConfig:
    base: dict[str, Any] = {
        "provider_id": "gw",
        "base_url": _BASE_URL,
        "api_key_env": "GW_KEY",
    }
    base.update(overrides)
    return ProviderConfig(**base)


# ---------------------------------------------------------------------------
# _api_key_from_env / _positive_int — value guards
# ---------------------------------------------------------------------------


def test_api_key_is_read_at_emit_time_and_whitespace_trimmed(monkeypatch: MonkeyPatch) -> None:
    """The key is not captured at config build time and is stripped when read."""
    monkeypatch.delenv("GW_KEY", raising=False)
    assert oc._api_key_from_env("GW_KEY") == ""

    monkeypatch.setenv("GW_KEY", "  secret-key \n")
    assert oc._api_key_from_env("GW_KEY") == "secret-key"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),  # bool is an int subclass — must not become 1
        (False, None),
        (0, None),
        (-5, None),
        (7, 7),
        (8.0, 8),  # integral float from JSON
        (8.5, None),  # non-integral float is not a token budget
        ("9", None),  # a string is not a number here
        (float("nan"), None),
    ],
)
def test_positive_int_accepts_only_positive_whole_numbers(value: Any, expected: int | None) -> None:
    """Each rejected shape would otherwise become a bogus ``limit``/``max_tokens``."""
    assert oc._positive_int(value) == expected


# ---------------------------------------------------------------------------
# option splitting — transport keys vs generation knobs
# ---------------------------------------------------------------------------


def test_provider_options_carry_transport_keys_only() -> None:
    """Generation knobs must not leak into OpenCode's ``provider.options``."""
    config = _config(
        extra_options={
            "timeout": 900,
            "headerTimeout": 30,
            "temperature": 0.2,
            "max_tokens": 4096,
            "setCacheKey": None,
        }
    )
    options = oc._opencode_provider_options(config)

    assert options == {
        "baseURL": _BASE_URL,
        "apiKey": "",
        "timeout": 900,
        "headerTimeout": 30,
    }


def test_generation_options_drop_reserved_keys_and_none_values() -> None:
    """Transport keys, limit sources, and unset values are all excluded."""
    result = oc._opencode_generation_options(
        {
            "timeout": 900,
            "context_limit": 100_000,
            "max_tokens": 4096,
            "temperature": 0.2,
            "top_p": None,
        }
    )

    assert result == {"temperature": 0.2}


# ---------------------------------------------------------------------------
# context limit / model entry — the "both values known" requirement
# ---------------------------------------------------------------------------


def test_typed_context_limit_wins_over_extra_options() -> None:
    """A declared ``context_limit`` field beats the loose ``extra_options`` copies."""
    config = _config(context_limit=200_000, extra_options={"context_limit": 1, "context": 2})
    assert oc._opencode_model_context_limit(config) == 200_000


def test_non_positive_typed_context_limit_falls_through_to_extra_options() -> None:
    """``context_limit=0`` is not a window — the loose keys are consulted in order."""
    assert oc._opencode_model_context_limit(_config(extra_options={"context": 64_000})) == 64_000
    assert (
        oc._opencode_model_context_limit(
            _config(extra_options={"context_limit": 32_000, "context": 64_000})
        )
        == 32_000
    )


def test_unknown_context_window_yields_no_limit() -> None:
    """Nothing to resolve → ``None``, so no partial ``limit`` object is emitted."""
    assert oc._opencode_model_context_limit(_config(extra_options={"context": 0})) is None
    assert oc._opencode_model_context_limit(_config()) is None


def test_model_entry_omits_limit_when_only_max_tokens_is_known() -> None:
    """OpenCode 1.18.x rejects a ``limit`` missing ``context`` — emit neither half."""
    entry = oc._opencode_model_entry("m1", _config(extra_options={"max_tokens": 4096}))

    assert entry == {"name": "m1"}


def test_model_entry_omits_limit_when_only_the_context_window_is_known() -> None:
    """The mirror case: a context window with no output cap emits no ``limit``."""
    entry = oc._opencode_model_entry("m1", _config(context_limit=128_000))

    assert entry == {"name": "m1"}


def test_model_entry_emits_both_limit_halves_and_generation_options() -> None:
    """Both values known → a complete ``limit`` plus the generation knobs."""
    entry = oc._opencode_model_entry(
        "m1",
        _config(context_limit=128_000, extra_options={"max_tokens": 4096, "temperature": 0.1}),
    )

    assert entry == {
        "name": "m1",
        "limit": {"context": 128_000, "output": 4096},
        "options": {"temperature": 0.1},
    }


# ---------------------------------------------------------------------------
# applied ModelParams / build-agent overrides
# ---------------------------------------------------------------------------


def test_applied_model_params_is_none_without_a_config_or_options() -> None:
    """No config, or a config with no extra options, applies no parameters."""
    assert oc._opencode_applied_model_params_from_config(None) is None
    assert oc._opencode_applied_model_params_from_config(_config()) is None


def test_unrecognised_extra_options_apply_no_model_params() -> None:
    """Options OpenCode does not map to a knob must not be reported as applied."""
    config = _config(extra_options={"someVendorFlag": "on"})
    assert oc._opencode_applied_model_params_from_config(config) is None


def test_max_tokens_is_only_reported_as_applied_when_a_context_window_is_known() -> None:
    """``max_tokens`` reaches the model entry only alongside ``context`` — mirror that."""
    without_context = oc._opencode_applied_model_params_from_config(
        _config(extra_options={"max_tokens": 4096, "temperature": 0.3})
    )
    assert without_context == ModelParams(temperature=0.3)

    with_context = oc._opencode_applied_model_params_from_config(
        _config(context_limit=128_000, extra_options={"max_tokens": 4096, "temperature": 0.3})
    )
    assert with_context == ModelParams(temperature=0.3, max_tokens=4096)


def test_applied_model_params_for_an_unconfigured_model_is_none() -> None:
    """No model slug and no gateway env → nothing applied."""
    assert oc.opencode_applied_model_params(None) is None
    assert oc.opencode_applied_model_params("nous/some-model") is None


def test_build_agent_overrides_only_carry_the_knobs_that_are_set() -> None:
    """``top_p`` alone must not drag a ``temperature`` key into the build agent."""
    assert oc._opencode_build_agent_overrides(None) == {}
    assert oc._opencode_build_agent_overrides(_config()) == {}
    assert oc._opencode_build_agent_overrides(_config(extra_options={"top_p": 0.9})) == {
        "top_p": 0.9
    }
    assert oc._opencode_build_agent_overrides(
        _config(extra_options={"temperature": 0.4, "top_p": 0.9})
    ) == {"temperature": 0.4, "top_p": 0.9}


# ---------------------------------------------------------------------------
# _parse_model — the slug guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "gpt-5", "/leading-slash"])
def test_unprefixed_model_slugs_yield_no_model_object(value: str | None) -> None:
    """Without a real ``provider/model`` split there is no provider id to send."""
    assert oc._parse_model(value) is None


def test_only_the_first_slash_splits_the_model_slug() -> None:
    """Nested model ids keep their slashes in ``modelID``."""
    assert oc._parse_model("nous/deepseek/deepseek-v4") == {
        "providerID": "nous",
        "modelID": "deepseek/deepseek-v4",
    }


# ---------------------------------------------------------------------------
# _custom_provider_ids / build_custom_provider — unconfigured environment
# ---------------------------------------------------------------------------


def test_no_provider_ids_without_a_resolvable_gateway() -> None:
    """An unconfigured environment registers no ``enabled_providers``."""
    assert oc._custom_provider_ids(None) == []
    assert oc._custom_provider_ids("nous/deepseek-v4") == []


def test_custom_provider_is_none_without_a_model() -> None:
    """No model → no provider block, even with the singleton env set."""
    assert oc.build_custom_provider(None) is None


# ---------------------------------------------------------------------------
# build_security_config — model-shape branches
# ---------------------------------------------------------------------------


def test_security_config_without_a_model_omits_model_and_provider_keys(tmp_path: Path) -> None:
    """A run with no resolved model still emits the deny-by-default permissions."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    config = json.loads(oc.build_security_config(ctx, None))

    assert "model" not in config
    assert "enabled_providers" not in config
    assert "provider" not in config
    assert config["permission"]["bash"] == "deny"
    assert config["permission"]["webfetch"] == "deny"


def test_unprefixed_model_registers_no_enabled_providers(tmp_path: Path) -> None:
    """A bare model id has no provider segment to enable."""
    ctx = make_agent_run_context(tmp_path, resolved_model="gpt-5")
    config = json.loads(oc.build_security_config(ctx, "gpt-5"))

    assert config["model"] == "gpt-5"
    assert "enabled_providers" not in config
    assert "provider" not in config


def test_mcp_entry_omits_headers_without_a_run_token(tmp_path: Path) -> None:
    """No per-run MCP token → no ``headers`` key at all on the remote MCP entry."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    config = json.loads(oc.build_security_config(ctx, None))

    entry = config["mcp"][MERGECRAFT_MCP_NAME]
    assert entry["type"] == "remote"
    assert entry["timeout"] == 300_000
    assert "headers" not in entry


def test_mcp_entry_carries_the_bearer_header_when_a_token_is_issued(tmp_path: Path) -> None:
    """A per-run token becomes the MCP ``Authorization`` header."""
    from dataclasses import replace

    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model=None),
        mcp_auth_token="run-token",
    )
    config = json.loads(oc.build_security_config(ctx, None))

    assert config["mcp"][MERGECRAFT_MCP_NAME]["headers"] == {"Authorization": "Bearer run-token"}


def _render_result(agent_block: dict[str, Any]) -> Any:
    from mergecraft.agents.harness_render import HarnessRenderResult

    return HarnessRenderResult(
        harness="opencode",
        payload={"agent": agent_block},
        selected_agent_ids=(),
    )


def test_build_agent_overrides_merge_into_an_existing_build_agent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Gateway generation knobs extend the rendered ``build`` agent, not replace it."""
    monkeypatch.setattr(
        "mergecraft.agents.harness_render.render_for_run",
        lambda ctx, harness, **kwargs: _render_result(
            {"build": {"prompt": "keep me"}, "other": {"x": 1}}
        ),
    )
    monkeypatch.setattr(
        oc,
        "_provider_config_for_model",
        lambda _model: _config(extra_options={"temperature": 0.25, "top_p": 0.8}),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model="gw/model-a")

    config = json.loads(oc.build_security_config(ctx, "gw/model-a"))

    assert config["agent"]["build"] == {
        "prompt": "keep me",
        "temperature": 0.25,
        "top_p": 0.8,
    }
    assert config["agent"]["other"] == {"x": 1}


def test_build_agent_overrides_create_the_build_agent_when_absent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No rendered ``build`` agent → the overrides become the whole entry."""
    monkeypatch.setattr(
        "mergecraft.agents.harness_render.render_for_run",
        lambda ctx, harness, **kwargs: _render_result({}),
    )
    monkeypatch.setattr(
        oc,
        "_provider_config_for_model",
        lambda _model: _config(extra_options={"temperature": 0.25}),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model="gw/model-a")

    config = json.loads(oc.build_security_config(ctx, "gw/model-a"))

    assert config["agent"]["build"] == {"temperature": 0.25}


def test_non_mapping_render_payload_degrades_to_an_empty_agent_block(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A string payload (the claude/gemini projection shape) is not an agent block."""
    from mergecraft.agents.harness_render import HarnessRenderResult

    monkeypatch.setattr(
        "mergecraft.agents.harness_render.render_for_run",
        lambda ctx, harness, **kwargs: HarnessRenderResult(
            harness="opencode", payload="not-a-mapping", selected_agent_ids=()
        ),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    config = json.loads(oc.build_security_config(ctx, None))

    assert config["agent"] == {}


# ---------------------------------------------------------------------------
# _install — CLI absent
# ---------------------------------------------------------------------------


async def test_install_raises_with_an_actionable_message_when_cli_is_absent(
    monkeypatch: MonkeyPatch,
) -> None:
    """A missing binary names the package the operator has to install."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(FileNotFoundError) as excinfo:
        await oc._install(None)

    assert "opencode-ai" in str(excinfo.value)


# ---------------------------------------------------------------------------
# _ServerHandle.close — teardown branches
# ---------------------------------------------------------------------------


class _FakeServeProc:
    """``Popen`` look-alike for the ``opencode serve`` boot + teardown paths."""

    def __init__(
        self,
        *,
        stdout_lines: list[bytes] | None = None,
        stderr: bytes = b"",
        poll_values: list[int | None] | None = None,
        wait_raises: bool = False,
    ) -> None:
        self._lines = list(stdout_lines or [])
        self.stdout: Any = self
        self.stderr: Any = _FakeBytesStream(stderr)
        self._poll_values = list(poll_values or [])
        self._wait_raises = wait_raises
        self.pid = 777_001
        self.wait_calls = 0
        self.kill_calls = 0

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def poll(self) -> int | None:
        return self._poll_values.pop(0) if self._poll_values else None

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.wait_calls += 1
        if self._wait_raises:
            raise subprocess.TimeoutExpired(cmd="opencode", timeout=5)
        return 0

    def kill(self) -> None:
        self.kill_calls += 1


class _FakeBytesStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def readline(self) -> bytes:
        """Terminate ``opencode._drain`` instead of raising in its thread.

        ``_drain`` consumes this stream with ``iter(stream.readline, b"")`` on a
        background thread. Without ``readline`` that thread died with an
        ``AttributeError`` *after* the owning test had finished, and the
        traceback was printed to whatever ``sys.stderr`` happened to be current
        — inside another test's Click ``CliRunner`` capture, where it broke an
        unrelated assertion (``tests/cli/test_doctor.py``). Returning ``b""``
        ends the drain loop cleanly.
        """
        return b""


class _FakeClock:
    """Deterministic stand-in for the ``time`` module inside opencode."""

    def __init__(self) -> None:
        self._now = 0.0

    def time(self) -> float:
        self._now += 1.0
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += max(seconds, 1.0)


@pytest.fixture
def killed_pids(monkeypatch: MonkeyPatch) -> list[int]:
    """Capture ``kill_process_group`` targets instead of signalling real pids."""
    killed: list[int] = []
    monkeypatch.setattr(oc, "kill_process_group", lambda pid: killed.append(pid))
    monkeypatch.setattr(oc, "register_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    return killed


def test_server_handle_close_is_idempotent(killed_pids: list[int]) -> None:
    """A second ``close()`` must not signal the process group again."""
    proc = _FakeServeProc(poll_values=[None])
    handle = oc._ServerHandle(base_url="http://127.0.0.1:1", proc=proc)  # type: ignore[arg-type]

    handle.close()
    handle.close()

    assert killed_pids == [proc.pid]
    assert proc.wait_calls == 1


def test_server_handle_close_skips_the_kill_for_an_already_exited_process(
    killed_pids: list[int],
) -> None:
    """An exited serve process is only unregistered, never signalled."""
    proc = _FakeServeProc(poll_values=[0])
    handle = oc._ServerHandle(base_url="http://127.0.0.1:1", proc=proc)  # type: ignore[arg-type]

    handle.close()

    assert killed_pids == []
    assert proc.wait_calls == 0


def test_server_handle_close_hard_kills_a_process_that_ignores_the_group_signal(
    killed_pids: list[int],
) -> None:
    """A serve process still alive after the grace wait gets ``kill()``."""
    proc = _FakeServeProc(poll_values=[None], wait_raises=True)
    handle = oc._ServerHandle(base_url="http://127.0.0.1:1", proc=proc)  # type: ignore[arg-type]

    handle.close()

    assert killed_pids == [proc.pid]
    assert proc.kill_calls == 1


# ---------------------------------------------------------------------------
# _boot_opencode_server — the two failure modes and the URL parse
# ---------------------------------------------------------------------------


def _patch_popen(monkeypatch: MonkeyPatch, proc: _FakeServeProc) -> list[list[str]]:
    captured: list[list[str]] = []

    def _fake_popen(cmd: list[str], **kwargs: object) -> _FakeServeProc:
        captured.append(list(cmd))
        return proc

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    return captured


def test_boot_reports_the_child_stderr_when_serve_exits_early(
    monkeypatch: MonkeyPatch, killed_pids: list[int]
) -> None:
    """The EACCES-class failure is surfaced verbatim so the operator can act."""
    proc = _FakeServeProc(
        poll_values=[1],
        stderr=b"EACCES: permission denied, mkdir '/github/home/.local'",
    )
    _patch_popen(monkeypatch, proc)
    monkeypatch.setattr(oc, "time", _FakeClock())

    with pytest.raises(RuntimeError) as excinfo:
        oc._boot_opencode_server(cli="opencode", env={}, cwd=".")

    assert "opencode serve exited early" in str(excinfo.value)
    assert "EACCES: permission denied" in str(excinfo.value)
    # The child already exited — no signal is sent to a dead group.
    assert killed_pids == []


def test_boot_kills_the_group_when_no_listening_url_is_printed(
    monkeypatch: MonkeyPatch, killed_pids: list[int]
) -> None:
    """A serve process that never announces a URL is torn down, not leaked."""
    proc = _FakeServeProc(stdout_lines=[b"starting up\n", b"still starting\n"])
    _patch_popen(monkeypatch, proc)
    monkeypatch.setattr(oc, "time", _FakeClock())

    with pytest.raises(RuntimeError) as excinfo:
        oc._boot_opencode_server(cli="opencode", env={}, cwd=".")

    assert "did not print a listening URL" in str(excinfo.value)
    assert killed_pids == [proc.pid]


def test_boot_returns_a_handle_on_the_announced_url_without_a_trailing_slash(
    monkeypatch: MonkeyPatch, killed_pids: list[int]
) -> None:
    """The first URL printed becomes the base url, normalised."""
    proc = _FakeServeProc(
        stdout_lines=[b"boot\n", b"opencode server listening on http://127.0.0.1:41235/\n"]
    )
    captured = _patch_popen(monkeypatch, proc)
    monkeypatch.setattr(oc, "time", _FakeClock())

    handle = oc._boot_opencode_server(cli="/usr/bin/opencode", env={}, cwd=".")

    assert handle.base_url == "http://127.0.0.1:41235"
    assert killed_pids == []
    assert captured[0][-4:] == ["--port", "0", "--hostname", "127.0.0.1"]


# ---------------------------------------------------------------------------
# _prompt_session_http — HTTP fallback and error shapes
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, *, status_code: int, body: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text
        self.content = b"{}" if body is not None else b""

    def json(self) -> Any:
        return self._body


class _RoutedClient:
    """AsyncClient stub that answers by URL suffix."""

    routes: dict[str, _StubResponse] = {}  # noqa: RUF012
    calls: list[str] = []  # noqa: RUF012

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _RoutedClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _StubResponse:
        del kwargs
        type(self).calls.append(url)
        for suffix, response in type(self).routes.items():
            if url.endswith(suffix):
                return response
        msg = f"unrouted url: {url}"
        raise AssertionError(msg)


def _route(monkeypatch: MonkeyPatch, routes: dict[str, _StubResponse]) -> type[_RoutedClient]:
    client = type("_Client", (_RoutedClient,), {"routes": routes, "calls": []})
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(oc, "instrument_httpx", lambda _client, tracer=None: None)
    return client


async def test_prompt_falls_back_to_the_legacy_prompt_endpoint_on_a_4xx(
    monkeypatch: MonkeyPatch,
) -> None:
    """A 404 from ``/message`` retries ``/prompt`` — the older API shape."""
    client = _route(
        monkeypatch,
        {
            "/message": _StubResponse(status_code=404, text="not found"),
            "/prompt": _StubResponse(status_code=200, body={"text": "fallback answer"}),
        },
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.success is True
    assert result.output == "fallback answer"
    assert [url.rsplit("/", 1)[-1] for url in client.calls] == ["message", "prompt"]


async def test_prompt_failure_reports_the_status_code_and_a_truncated_body(
    monkeypatch: MonkeyPatch,
) -> None:
    """Both endpoints failing produce a diagnosable error, not a success."""
    _route(
        monkeypatch,
        {
            "/message": _StubResponse(status_code=500, text="x" * 900),
            "/prompt": _StubResponse(status_code=500, text="x" * 900),
        },
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("opencode prompt failed (500): ")
    assert result.error.count("x") == 500


async def test_non_object_response_body_yields_no_output(monkeypatch: MonkeyPatch) -> None:
    """A JSON array is not a session payload — output is ``None``, not ``"[]"``."""
    _route(monkeypatch, {"/message": _StubResponse(status_code=200, body=["unexpected"])})

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.success is True
    assert result.output is None
    assert result.usage is None


async def test_non_mapping_info_field_reports_no_usage(monkeypatch: MonkeyPatch) -> None:
    """A malformed ``info`` must degrade to "no usage", never crash the attempt."""
    _route(
        monkeypatch,
        {"/message": _StubResponse(status_code=200, body={"text": "answer", "info": ["bad"]})},
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.success is True
    assert result.output == "answer"
    assert result.usage is None


async def test_cost_only_usage_is_still_reported(monkeypatch: MonkeyPatch) -> None:
    """A response with cost but no token counts is a usage record."""
    _route(
        monkeypatch,
        {
            "/message": _StubResponse(
                status_code=200, body={"text": "answer", "info": {"costUsd": 0.125}}
            )
        },
    )

    result = await oc._prompt_session_http(
        base_url="http://127.0.0.1:1", session_id="s1", text="hi", model=None
    )

    assert result.usage is not None
    assert result.usage.agent == "opencode"
    assert result.usage.cost_usd == pytest.approx(0.125)
    assert result.usage.input_tokens == 0


async def test_model_is_forwarded_in_the_prompt_payload(monkeypatch: MonkeyPatch) -> None:
    """The resolved provider/model pair rides on the session request body."""
    sent: list[dict[str, Any]] = []

    class _Recorder(_RoutedClient):
        routes = {"/message": _StubResponse(status_code=200, body={"text": "ok"})}  # noqa: RUF012
        calls: list[str] = []  # noqa: RUF012

        async def post(self, url: str, **kwargs: object) -> _StubResponse:
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                sent.append(payload)
            return await super().post(url, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Recorder)
    monkeypatch.setattr(oc, "instrument_httpx", lambda _client, tracer=None: None)

    await oc._prompt_session_http(
        base_url="http://127.0.0.1:1",
        session_id="s1",
        text="hi",
        model={"providerID": "nous", "modelID": "deepseek-v4"},
    )

    assert sent[0]["model"] == {"providerID": "nous", "modelID": "deepseek-v4"}
    assert sent[0]["parts"] == [{"type": "text", "text": "hi"}]


# ---------------------------------------------------------------------------
# _run_opencode_cli_streaming — spawn failure, timeout, non-zero exit
# ---------------------------------------------------------------------------


class _FakeCliProc:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout: list[str] = stdout.splitlines(keepends=True)
        self.stderr: Any = _FakeTextStream(stderr)
        self.returncode = returncode
        self.pid = 777_002

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode


class _FakeTextStream:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def _spawn(process: _FakeCliProc) -> Any:
    def _fake(cmd: list[str], **kwargs: object) -> _FakeCliProc:
        del cmd, kwargs
        return process

    return _fake


def test_cli_streaming_returns_a_failed_result_when_the_binary_is_missing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A spawn failure is a failed ``AgentResult``, never a raised exception."""

    def _boom(cmd: list[str], **kwargs: object) -> Any:
        del cmd, kwargs
        msg = "no such file: opencode"
        raise FileNotFoundError(msg)

    monkeypatch.setattr(oc, "spawn_agent_cli", _boom)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is False
    assert result.error == "no such file: opencode"


def test_cli_streaming_reports_a_timeout_as_a_clean_failed_result(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``TimeoutExpired`` becomes a named failure rather than a traceback."""
    monkeypatch.setattr(oc, "spawn_agent_cli", _spawn(_FakeCliProc()))

    def _timeout(process: Any, *, timeout: float | None) -> int:
        del process, timeout
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=1)

    monkeypatch.setattr(oc, "wait_or_kill_process_group", _timeout)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is False
    assert result.error == "opencode run timed out"


def test_cli_streaming_marks_rate_limited_failures_retryable(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An overload message on stderr sets ``metadata['retryable']`` for the chain."""
    monkeypatch.setattr(
        oc,
        "spawn_agent_cli",
        _spawn(_FakeCliProc(stderr="provider overloaded, retry later\n", returncode=1)),
    )
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is False
    assert result.metadata == {"retryable": True}
    assert result.error == "provider overloaded, retry later"


def test_cli_streaming_falls_back_to_a_generic_message_with_empty_stderr(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No stderr at all → the generic "opencode failed" marker."""
    monkeypatch.setattr(oc, "spawn_agent_cli", _spawn(_FakeCliProc(stderr="", returncode=2)))
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is False
    assert result.error == "opencode failed"
    assert result.metadata == {}


def test_cli_streaming_names_the_exit_code_for_whitespace_only_stderr(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Whitespace-only stderr strips to empty, so the exit code carries the signal."""
    monkeypatch.setattr(oc, "spawn_agent_cli", _spawn(_FakeCliProc(stderr="  \n ", returncode=3)))
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is False
    assert result.error == "opencode exited 3"


def test_cli_streaming_success_with_no_events_reports_none_output(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An empty stream on a clean exit is ``output=None``, not ``""``."""
    monkeypatch.setattr(oc, "spawn_agent_cli", _spawn(_FakeCliProc(stdout="\n\n", returncode=0)))
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={})

    assert result.success is True
    assert result.output is None


# ---------------------------------------------------------------------------
# _run_cli_fallback — argv assembly
# ---------------------------------------------------------------------------


async def test_cli_fallback_prepends_the_system_prompt_and_passes_the_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The fallback argv carries the joined prompt and the resolved model flag."""
    from dataclasses import replace

    from mergecraft.agents.shared import AgentResult, ResolvedInstructions

    captured: dict[str, Any] = {}

    def _fake_streaming(*, cmd: list[str], ctx: Any, env: dict[str, str]) -> AgentResult:
        captured["cmd"] = cmd
        return AgentResult(success=True, output="ok")

    monkeypatch.setattr(oc, "_run_opencode_cli_streaming", _fake_streaming)
    ctx = replace(
        make_agent_run_context(tmp_path, resolved_model="nous/deepseek-v4"),
        instructions=ResolvedInstructions(system="SYSTEM", user="USER"),
    )

    result = await oc._run_cli_fallback(cli="/usr/bin/opencode", ctx=ctx, env={})

    cmd = captured["cmd"]
    assert cmd[:4] == ["/usr/bin/opencode", "run", "--format", "json"]
    assert cmd[4] == "SYSTEM\n\nUSER"
    assert cmd[cmd.index("--model") + 1] == "nous/deepseek-v4"
    assert result.output == "ok"


async def test_cli_fallback_omits_the_model_flag_when_none_is_resolved(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No resolved model → no ``--model`` flag and the user prompt stands alone."""
    from mergecraft.agents.shared import AgentResult

    captured: dict[str, Any] = {}

    def _fake_streaming(*, cmd: list[str], ctx: Any, env: dict[str, str]) -> AgentResult:
        captured["cmd"] = cmd
        return AgentResult(success=True)

    monkeypatch.setattr(oc, "_run_opencode_cli_streaming", _fake_streaming)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    await oc._run_cli_fallback(cli="opencode", ctx=ctx, env={})

    assert "--model" not in captured["cmd"]
    assert captured["cmd"][-1] == "review this diff"


# ---------------------------------------------------------------------------
# _run — install failure, serve fallback, session bootstrap failures
# ---------------------------------------------------------------------------


async def test_run_reports_a_missing_cli_without_touching_the_server(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``_run`` short-circuits on a missing binary before writing any config."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = await oc._run(ctx)

    assert result.success is False
    assert result.error is not None
    assert "opencode CLI not found" in result.error
    assert not (tmp_path / "opencode.json").exists()


async def test_run_falls_back_to_the_cli_when_serve_cannot_boot(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A serve boot failure degrades to ``opencode run`` instead of failing the review."""
    from mergecraft.agents.shared import AgentResult

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")

    def _boom(**kwargs: object) -> Any:
        del kwargs
        msg = "opencode serve did not print a listening URL"
        raise RuntimeError(msg)

    monkeypatch.setattr(oc, "_boot_opencode_server", _boom)

    async def _fallback(*, cli: str, ctx: Any, env: dict[str, str]) -> AgentResult:
        return AgentResult(success=True, output="cli fallback output")

    monkeypatch.setattr(oc, "_run_cli_fallback", _fallback)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = await oc._run(ctx)

    assert result.success is True
    assert result.output == "cli fallback output"
    # The config file is still written before the boot attempt.
    evidence_dir = oc._evidence_dir(ctx)
    assert (evidence_dir / "opencode.json").is_file()


async def test_run_reports_a_session_creation_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A 4xx from ``POST /session`` aborts the run with the server's body."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    proc = _FakeServeProc()
    handle = oc._ServerHandle(base_url="http://127.0.0.1:5", proc=proc)  # type: ignore[arg-type]
    monkeypatch.setattr(oc, "_boot_opencode_server", lambda **kwargs: handle)
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    _route(monkeypatch, {"/session": _StubResponse(status_code=503, text="server busy")})
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = await oc._run(ctx)

    assert result.success is False
    assert result.error == "failed to create opencode session: server busy"


async def test_run_rejects_a_session_response_without_an_id(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A 200 with no usable id is a failure — the run cannot be addressed."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    proc = _FakeServeProc()
    handle = oc._ServerHandle(base_url="http://127.0.0.1:5", proc=proc)  # type: ignore[arg-type]
    monkeypatch.setattr(oc, "_boot_opencode_server", lambda **kwargs: handle)
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    _route(monkeypatch, {"/session": _StubResponse(status_code=200, body={"title": "mergecraft"})})
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = await oc._run(ctx)

    assert result.success is False
    assert result.error == "opencode session missing id"


async def test_run_converts_a_provider_timeout_into_a_clean_failed_attempt(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``ProviderTimeoutError`` is a controlled domain error, not a raised traceback."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    proc = _FakeServeProc()
    handle = oc._ServerHandle(base_url="http://127.0.0.1:5", proc=proc)  # type: ignore[arg-type]
    monkeypatch.setattr(oc, "_boot_opencode_server", lambda **kwargs: handle)
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    _route(
        monkeypatch,
        {
            "/session": _StubResponse(status_code=200, body={"id": "sess-1"}),
            "/message": _StubResponse(status_code=200, body={"text": "hi"}),
        },
    )

    async def _timeout(*args: object, **kwargs: object) -> Any:
        msg = "opencode provider request timed out: read timeout"
        raise oc.ProviderTimeoutError(msg)

    monkeypatch.setattr(oc, "run_post_run_retry_loop", _timeout)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = await oc._run(ctx)

    assert result.success is False
    assert result.error == "opencode provider request timed out: read timeout"
    # #444 — the chain gates on this flag alone. Without it a provider timeout
    # reads as permanent and terminates the run at attempt 1 instead of failing
    # over. Supersedes plan 06 D11's claim that this path stays non-retryable.
    assert (result.metadata or {}).get("retryable") is True
    # The serve handle is always torn down, timeout or not.
    assert proc.wait_calls == 1


async def test_run_converts_an_initial_prompt_timeout_into_a_failed_attempt(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A timeout on the FIRST prompt fails cleanly instead of propagating (#444).

    The initial ``_prompt_session`` call carries the whole review, so it is the
    likeliest place to time out. When it sat outside the handler, the raised
    ``ProviderTimeoutError`` escaped ``_run`` → ``run_once`` →
    ``run_with_model_chain`` and killed the run with no fallback.
    """
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    proc = _FakeServeProc()
    handle = oc._ServerHandle(base_url="http://127.0.0.1:5", proc=proc)  # type: ignore[arg-type]
    handle._recent.append("serve: upstream stalled")
    monkeypatch.setattr(oc, "_boot_opencode_server", lambda **kwargs: handle)
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    _route(monkeypatch, {"/session": _StubResponse(status_code=200, body={"id": "sess-1"})})

    calls: list[str] = []

    async def _timeout(*args: object, **kwargs: object) -> Any:
        calls.append("prompt")
        msg = "opencode provider request timed out: read timeout"
        raise oc.ProviderTimeoutError(msg)

    monkeypatch.setattr(oc, "_prompt_session", _timeout)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    result = await oc._run(ctx)

    assert calls == ["prompt"]
    assert result.success is False
    assert (result.metadata or {}).get("retryable") is True
    # #449 — the operator gets the server's own tail, not a bare "timed out:".
    assert "serve: upstream stalled" in (result.error or "")
    assert proc.wait_calls == 1


def test_recent_output_and_the_drain_thread_share_one_lock() -> None:
    """The tail buffer is lock-guarded on both sides.

    ``deque.append`` being atomic says nothing about *iteration*: joining the
    buffer while a drain thread appends can raise ``RuntimeError: deque mutated
    during iteration`` before it reaches ``maxlen``. ``recent_output()`` runs
    inside the ``ProviderTimeoutError`` handler, so that would replace the clean
    failed result with an exception.
    """
    import threading

    proc = _FakeServeProc()
    handle = oc._ServerHandle(base_url="http://127.0.0.1:5", proc=proc)  # type: ignore[arg-type]
    lines = [b"serve: hello\n"]

    class _OneLineStream:
        def readline(self) -> bytes:
            return lines.pop(0) if lines else b""

    stream: Any = _OneLineStream()
    reads: list[str] = []

    with handle._recent_lock:
        writer = threading.Thread(target=handle._drain, args=(stream, "out"), daemon=True)
        reader = threading.Thread(target=lambda: reads.append(handle.recent_output()), daemon=True)
        writer.start()
        reader.start()
        writer.join(timeout=0.2)
        reader.join(timeout=0.2)
        # Both sides must take the same lock, so both are still blocked here.
        assert writer.is_alive()
        assert reader.is_alive()

    writer.join(timeout=2.0)
    reader.join(timeout=2.0)
    assert not writer.is_alive()
    assert not reader.is_alive()
    assert handle.recent_output() == "serve: hello"


async def test_run_exports_the_bedrock_flag_only_for_a_matching_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``BEDROCK_MODEL_ID`` gates the BYOK flag on an exact model match."""
    from mergecraft.agents.shared import AgentResult

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-x")
    captured: list[dict[str, str]] = []

    def _boom(**kwargs: object) -> Any:
        del kwargs
        msg = "no serve"
        raise RuntimeError(msg)

    monkeypatch.setattr(oc, "_boot_opencode_server", _boom)

    async def _fallback(*, cli: str, ctx: Any, env: dict[str, str]) -> AgentResult:
        captured.append(env)
        return AgentResult(success=True)

    monkeypatch.setattr(oc, "_run_cli_fallback", _fallback)

    await oc._run(make_agent_run_context(tmp_path, resolved_model="anthropic.claude-x"))
    assert captured[-1].get("CLAUDE_CODE_USE_BEDROCK") == "1"

    await oc._run(make_agent_run_context(tmp_path, resolved_model="anthropic.claude-y"))
    assert "CLAUDE_CODE_USE_BEDROCK" not in captured[-1]
