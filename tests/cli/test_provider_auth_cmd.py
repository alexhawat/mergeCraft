"""RED tests for ``mergecraft provider auth`` (#478 / BB).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BB — test-creator. Pins unified provider auth: indexed secret naming, interactive
picker, auth-kind strategies, legacy shim (D7), and ``auth logfire`` isolation (D6).
"""

from __future__ import annotations

import getpass
import importlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import typer
from dotenv import dotenv_values
from tests.cli.support_provider_registry import (
    AUTH_KIND_API_KEY,
    AUTH_KIND_CLOUD_CHAIN,
    AUTH_KIND_PRIMARY_SUFFIX,
    BB_XFAIL,
    BEDROCK_INDEXED_KEYS,
    CUSTOM_BASE_URL,
    LEGACY_AUTH_SUBCOMMANDS,
    NOUS_BASE_URL,
    VERTEX_INDEXED_KEYS,
    indexed_env_key,
    read_env_file,
    scaffold_mergecraft_home,
    write_provider_entry,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _load_auth_cmd() -> Any:
    try:
        return importlib.import_module("mergecraft.cli.auth_cmd")
    except ImportError as exc:
        pytest.fail(f"mergecraft.cli.auth_cmd not importable: {exc}")


def _patch_nous_validator(monkeypatch: MonkeyPatch) -> None:
    """Stub Nous validation so provider auth tests never hit the network."""
    module = _load_auth_cmd()
    monkeypatch.setattr(module, "_validate_nous_api_key", lambda _key: True)


def _patch_httpx_noop(monkeypatch: MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, json={"choices": []}))
    real_client = httpx.Client

    def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("mergecraft.cli.auth_cmd.httpx.Client", _factory)


def _stub_scope_local(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


@BB_XFAIL
def test_provider_help_lists_auth_verb() -> None:
    result = _invoke("provider", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "auth" in output


@BB_XFAIL
def test_provider_auth_help_documents_scope_flag() -> None:
    result = _invoke("provider", "auth", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "scope" in output
    assert "local" in output


# ---------------------------------------------------------------------------
# Non-interactive ``provider auth <label>`` — indexed secret naming
# ---------------------------------------------------------------------------


@BB_XFAIL
def test_provider_auth_nous_writes_indexed_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="nous",
        env_index=1,
        url=NOUS_BASE_URL,
        auth_kind=AUTH_KIND_API_KEY,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    _patch_nous_validator(monkeypatch)
    _patch_httpx_noop(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "nous-indexed-key")

    result = _invoke("provider", "auth", "nous", "--scope", "local")

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    env = dotenv_values(tmp_path / ".env")
    assert env.get("LLM_PROVIDER_1") == "nous"
    assert env.get(indexed_env_key(1, "API_KEY")) == "nous-indexed-key"
    assert "NOUS_API_KEY" not in env


@BB_XFAIL
def test_provider_auth_unknown_label_exits_nonzero(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)

    result = _invoke("provider", "auth", "not-registered", "--scope", "local")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "not-registered" in output or "unknown" in output


@BB_XFAIL
def test_provider_auth_reauth_overwrites_indexed_key_in_place(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="nous",
        env_index=1,
        url=NOUS_BASE_URL,
        auth_kind=AUTH_KIND_API_KEY,
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"LLM_PROVIDER_1=nous\n{indexed_env_key(1, 'API_KEY')}=old-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    _patch_nous_validator(monkeypatch)
    _patch_httpx_noop(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "fresh-key")

    result = _invoke("provider", "auth", "nous", "--scope", "local")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    written = env_path.read_text(encoding="utf-8")
    assert written.count(indexed_env_key(1, "API_KEY")) == 1
    env = dotenv_values(env_path)
    assert env[indexed_env_key(1, "API_KEY")] == "fresh-key"


# ---------------------------------------------------------------------------
# Interactive picker (label omitted)
# ---------------------------------------------------------------------------


@BB_XFAIL
def test_provider_auth_interactive_picker_selects_provider(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="alpha",
        env_index=1,
        url=CUSTOM_BASE_URL,
        auth_kind=AUTH_KIND_API_KEY,
    )
    write_provider_entry(
        tmp_path,
        label="beta",
        env_index=2,
        url="https://beta.example/v1",
        auth_kind=AUTH_KIND_API_KEY,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    _patch_nous_validator(monkeypatch)
    _patch_httpx_noop(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "beta-key")

    def _prompt(message: str, **kwargs: Any) -> str:
        return "2"

    monkeypatch.setattr(typer, "prompt", _prompt)

    result = _invoke("provider", "auth", "--scope", "local")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "beta" in output.lower() or "select" in output.lower()

    env = dotenv_values(tmp_path / ".env")
    assert env.get(indexed_env_key(2, "API_KEY")) == "beta-key"
    assert indexed_env_key(1, "API_KEY") not in env


@BB_XFAIL
def test_provider_auth_picker_lists_registered_labels_and_urls(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="nous",
        env_index=1,
        url=NOUS_BASE_URL,
        auth_kind=AUTH_KIND_API_KEY,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)

    # Cancel at the picker — we only assert the menu content.
    monkeypatch.setattr(typer, "prompt", lambda *_a, **_kw: "")

    result = _invoke("provider", "auth", "--scope", "local")
    output = _plain(result.stdout + result.stderr).lower()
    assert "nous" in output
    assert "inference-api.nousresearch.com" in output or NOUS_BASE_URL in output


# ---------------------------------------------------------------------------
# D6 — ``auth logfire`` stays separate from provider auth
# ---------------------------------------------------------------------------


def test_auth_logfire_remains_under_auth_namespace() -> None:
    """``auth logfire`` is telemetry — not an LLM provider (D6). Always green."""
    result = _invoke("auth", "--help")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE
    assert "logfire" in _plain(result.stdout).lower()


@BB_XFAIL
def test_provider_auth_logfire_is_rejected(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)

    result = _invoke("provider", "auth", "logfire", "--scope", "local")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "logfire" in output
    assert not (tmp_path / ".env").exists() or "MERGECRAFT_LOGFIRE_TOKEN" not in read_env_file(
        tmp_path
    )


@BB_XFAIL
def test_provider_auth_picker_excludes_logfire(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="nous",
        env_index=1,
        url=NOUS_BASE_URL,
        auth_kind=AUTH_KIND_API_KEY,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    monkeypatch.setattr(typer, "prompt", lambda *_a, **_kw: "")

    result = _invoke("provider", "auth", "--scope", "local")
    output = _plain(result.stdout + result.stderr).lower()
    assert "logfire" not in output


# ---------------------------------------------------------------------------
# Auth-kind strategies — cloud_chain (D10) and api_key
# ---------------------------------------------------------------------------


@BB_XFAIL
@pytest.mark.parametrize("suffix", BEDROCK_INDEXED_KEYS)
def test_provider_auth_bedrock_cloud_chain_writes_indexed_aws_keys(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    suffix: str,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="bedrock",
        env_index=3,
        harness="claude",
        auth_kind=AUTH_KIND_CLOUD_CHAIN,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)

    prompts = {
        "AWS_ACCESS_KEY_ID": "AKIATEST",
        "AWS_SECRET_ACCESS_KEY": "secret-test",
    }

    def _getpass(message: str) -> str:
        for key, value in prompts.items():
            if key.lower().replace("_", " ") in message.lower() or key in message:
                return value
        return "placeholder"

    monkeypatch.setattr(getpass, "getpass", _getpass)

    result = _invoke("provider", "auth", "bedrock", "--scope", "local")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    env = dotenv_values(tmp_path / ".env")
    assert env.get("LLM_PROVIDER_3") == "bedrock"
    assert env.get(indexed_env_key(3, suffix)) == prompts[suffix]
    assert indexed_env_key(3, "API_KEY") not in env


@BB_XFAIL
def test_provider_auth_vertex_writes_credentials_path_not_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="vertex",
        env_index=4,
        harness="claude",
        auth_kind=AUTH_KIND_CLOUD_CHAIN,
    )
    creds_path = tmp_path / "sa.json"
    creds_path.write_text('{"type":"service_account"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    monkeypatch.setattr(
        typer,
        "prompt",
        lambda _msg, **kwargs: str(creds_path),
    )

    result = _invoke("provider", "auth", "vertex", "--scope", "local")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    env = dotenv_values(tmp_path / ".env")
    key = indexed_env_key(4, VERTEX_INDEXED_KEYS[0])
    assert env.get(key) == str(creds_path)
    assert indexed_env_key(4, "API_KEY") not in env


@BB_XFAIL
def test_provider_auth_vertex_refuses_multiline_json_for_local_scope(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Multi-line service-account JSON must not corrupt ``.env`` (#478 blocker)."""
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="vertex",
        env_index=4,
        harness="claude",
        auth_kind=AUTH_KIND_CLOUD_CHAIN,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)

    multiline_json = json.dumps({"type": "service_account", "project_id": "demo"}, indent=2)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: multiline_json)

    result = _invoke("provider", "auth", "vertex", "--scope", "local")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "multiple lines" in output or "multi-line" in output or "json" in output
    assert (
        "google_application_credentials" in output
        or "path" in output
        or "base64" in output
        or "github" in output
    )
    assert not (tmp_path / ".env").exists() or indexed_env_key(
        4, "VERTEX_SERVICE_ACCOUNT_JSON"
    ) not in read_env_file(tmp_path)


# ---------------------------------------------------------------------------
# Legacy shim — warn once per process, delegate to unified path (D7)
# ---------------------------------------------------------------------------


@BB_XFAIL
@pytest.mark.parametrize("legacy_cmd", LEGACY_AUTH_SUBCOMMANDS)
def test_legacy_auth_commands_warn_and_write_indexed_secret(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    legacy_cmd: str,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label=legacy_cmd if legacy_cmd != "minimax" else "minimax",
        env_index=1,
        url=CUSTOM_BASE_URL if legacy_cmd not in {"codex", "claude", "gemini", "cursor"} else None,
        harness={
            "codex": "codex",
            "claude": "claude",
            "gemini": "gemini",
            "cursor": "cursor",
        }.get(legacy_cmd, "opencode"),
        auth_kind=AUTH_KIND_API_KEY,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    _patch_httpx_noop(monkeypatch)

    module = _load_auth_cmd()
    for validator_name in (
        "_validate_gemini_api_key",
        "_validate_cursor_api_key",
        "_validate_nous_api_key",
        "_validate_tokenhub_api_key",
        "_validate_minimax_api_key",
    ):
        if hasattr(module, validator_name):
            monkeypatch.setattr(module, validator_name, lambda _key: True)

    if legacy_cmd == "codex":
        monkeypatch.setattr(module, "shutil.which", lambda _name: "/usr/bin/codex")
        monkeypatch.setattr(
            module.subprocess,
            "run",
            lambda *_a, **_kw: None,
        )
        monkeypatch.setattr(
            module.tempfile,
            "TemporaryDirectory",
            lambda **_kw: _FakeCodexHome(),
        )
    elif legacy_cmd == "claude":
        monkeypatch.setattr(
            getpass,
            "getpass",
            lambda _prompt: "sk-ant-oat-legacy-delegate",
        )
    else:
        monkeypatch.setattr(getpass, "getpass", lambda _prompt: f"{legacy_cmd}-legacy-key")

    result = _invoke("auth", legacy_cmd, "--scope", "local")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    assert "deprecated" in output or "provider auth" in output or "unified" in output

    suffix = AUTH_KIND_PRIMARY_SUFFIX.get(AUTH_KIND_API_KEY, "API_KEY")
    env = dotenv_values(tmp_path / ".env")
    assert env.get(indexed_env_key(1, suffix)) is not None


class _FakeCodexHome:
    """Minimal ``TemporaryDirectory`` stand-in that leaves a one-line auth.json."""

    def __enter__(self) -> str:
        import tempfile

        self._dir = tempfile.mkdtemp(prefix="mergecraft-codex-test-")
        auth_path = Path(self._dir) / "auth.json"
        auth_path.write_text(
            '{"tokens":{"access_token":"codex-legacy","refresh_token":"r"}}',
            encoding="utf-8",
        )
        return self._dir

    def __exit__(self, *_exc: object) -> None:
        import shutil

        shutil.rmtree(self._dir, ignore_errors=True)


@BB_XFAIL
def test_legacy_auth_warning_emitted_once_per_process(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    write_provider_entry(
        tmp_path,
        label="nous",
        env_index=1,
        url=NOUS_BASE_URL,
        auth_kind=AUTH_KIND_API_KEY,
    )
    monkeypatch.chdir(tmp_path)
    _stub_scope_local(monkeypatch, tmp_path)
    _patch_nous_validator(monkeypatch)
    _patch_httpx_noop(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "nous-key")

    warnings: list[str] = []

    def _warn(message: str) -> None:
        warnings.append(message)

    module = _load_auth_cmd()
    if hasattr(module, "_warn_legacy_auth_once"):
        monkeypatch.setattr(module, "_warn_legacy_auth_once", _warn)

    first = _invoke("auth", "nous", "--scope", "local")
    second = _invoke("auth", "nous", "--scope", "local")
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE
    assert second.exit_code == CLI_SUCCESS_EXIT_CODE
    assert len(warnings) <= 1
