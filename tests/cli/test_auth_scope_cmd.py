"""Contracts for ``mergecraft auth logfire --scope`` and shared auth helpers (issue #221 / D11).

After provider credentials moved to ``mergecraft provider auth``, the ``auth`` Typer
app keeps ``logfire`` only. These tests pin scope behaviour and the shared
persistence helpers the provider path still imports.
"""

from __future__ import annotations

import getpass
import importlib
import inspect
import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
import typer
from dotenv import dotenv_values
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_REAL_SUBPROCESS_RUN = subprocess.run

LOGFIRE_TOKEN = "pylf_v1_eu_scope-red-token"
LOGFIRE_PROJECT = "mergecraft-scope-red"
LOGFIRE_RUNTIME_ENV = "MERGECRAFT_LOGFIRE_TOKEN"
LOGFIRE_PROJECT_ENV = "MERGECRAFT_TRACING_PROJECT"
LOGFIRE_SECRET = "LOGFIRE_TOKEN"

PRESERVED_KEY = "MERGECRAFT_SCOPE_RED_PRESERVED"
PRESERVED_VALUE = "keep-me"

CODEX_AUTH_PAYLOAD = (
    '{"tokens": {"access_token": "codex-red-access", "refresh_token": "codex-red-refresh"}, '
    '"last_refresh": "2026-08-19T00:00:00Z"}'
)
PRETTY_CODEX_PAYLOAD = json.dumps(json.loads(CODEX_AUTH_PAYLOAD), indent=2)


def _load_auth_cmd() -> Any:
    try:
        return importlib.import_module("mergecraft.cli.auth_cmd")
    except ImportError as exc:
        pytest.fail(f"mergecraft.cli.auth_cmd not importable: {exc}")


EXPECTED_VALIDATORS = frozenset(
    {
        "_validate_gemini_api_key",
        "_validate_cursor_api_key",
        "_validate_openai_compatible_key",
        "_validate_nous_api_key",
        "_validate_minimax_api_key",
        "_validate_logfire_token",
    }
)


def _stub_validators(module: Any, monkeypatch: MonkeyPatch) -> None:
    stubbed = {name for name in dir(module) if name.startswith("_validate_")}
    missing = EXPECTED_VALIDATORS - stubbed
    assert not missing, (
        f"{sorted(missing)} no longer exist on mergecraft.cli.auth_cmd — update "
        "EXPECTED_VALIDATORS deliberately."
    )
    for name in stubbed:
        monkeypatch.setattr(module, name, lambda *_a, **_kw: True)


def _arrange_logfire(module: Any, monkeypatch: MonkeyPatch) -> None:
    _stub_validators(module, monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: LOGFIRE_TOKEN)
    monkeypatch.setattr(typer, "prompt", lambda *_a, **_kw: LOGFIRE_PROJECT)


class GhRecorder:
    def __init__(self) -> None:
        self.token_calls = 0
        self.remote_calls = 0
        self.secrets: list[dict[str, str]] = []
        self.secret_result = True

    def install(self, module: Any, monkeypatch: MonkeyPatch) -> None:
        def _token() -> str:
            self.token_calls += 1
            return "gh-token"

        def _remote() -> tuple[str, str]:
            self.remote_calls += 1
            return "acme", "widgets"

        def _secret(*, name: str, value: str, repo_slug: str) -> bool:
            self.secrets.append({"name": name, "value": value, "repo_slug": repo_slug})
            return self.secret_result

        monkeypatch.setattr(module, "_get_gh_token", _token)
        monkeypatch.setattr(module, "_parse_git_remote", _remote)
        monkeypatch.setattr(module, "_set_gh_secret", _secret)

    @property
    def touched_gh(self) -> bool:
        return bool(self.token_calls or self.remote_calls or self.secrets)


def _pin_env_path(tmp_path: Path, monkeypatch: MonkeyPatch, *, precreate: bool) -> Path:
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    if precreate:
        env_path.write_text(f"{PRESERVED_KEY}={PRESERVED_VALUE}\n", encoding="utf-8")
    return env_path


def _read_back(env_path: Path, key: str) -> str | None:
    return dotenv_values(str(env_path)).get(key)


def _flat(result: Any) -> str:
    return " ".join((result.stdout + result.stderr).split()).lower()


def test_auth_logfire_scope_local_writes_env_without_gh(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.secret_result = False
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=True)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "local"])

    assert result.exit_code == 0, _flat(result)
    assert not gh.touched_gh
    assert _read_back(env_path, LOGFIRE_RUNTIME_ENV) == LOGFIRE_TOKEN
    assert _read_back(env_path, LOGFIRE_PROJECT_ENV) == LOGFIRE_PROJECT
    assert _read_back(env_path, PRESERVED_KEY) == PRESERVED_VALUE


def test_auth_logfire_scope_github_writes_secret_only(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "github"])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == [LOGFIRE_SECRET]
    assert gh.secrets[0]["value"] == LOGFIRE_TOKEN
    assert gh.secrets[0]["repo_slug"] == "acme/widgets"
    assert not env_path.exists()


def test_auth_logfire_scope_both_writes_env_and_secret(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=True)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "both"])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == [LOGFIRE_SECRET]
    assert gh.secrets[0]["value"] == LOGFIRE_TOKEN
    assert _read_back(env_path, LOGFIRE_RUNTIME_ENV) == LOGFIRE_TOKEN
    assert _read_back(env_path, LOGFIRE_PROJECT_ENV) == LOGFIRE_PROJECT


def test_auth_logfire_default_scope_is_both(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", "logfire"])

    assert result.exit_code == 0, _flat(result)
    assert gh.secrets
    assert _read_back(env_path, LOGFIRE_RUNTIME_ENV) == LOGFIRE_TOKEN


def test_auth_logfire_rejects_unknown_scope(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "must-not-prompt")
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "everywhere"])

    assert result.exit_code == CLI_USAGE_EXIT_CODE
    output = _flat(result)
    assert "expected one of" in output
    for valid in ("local", "github", "both"):
        assert valid in output
    assert gh.secrets == []
    assert not env_path.exists()


def test_auth_logfire_scope_both_survives_a_failed_gh_secret_set(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.secret_result = False
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "both"])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == [LOGFIRE_SECRET]
    assert _read_back(env_path, LOGFIRE_RUNTIME_ENV) == LOGFIRE_TOKEN
    output = _flat(result)
    assert "warning" in output or "manually" in output


def test_auth_logfire_scope_both_bails_when_neither_half_lands(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.secret_result = False
    gh.install(module, monkeypatch)
    _pin_env_path(tmp_path, monkeypatch, precreate=False)
    monkeypatch.setattr(module, "_write_env_value", lambda *_a, **_kw: False)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "both"])

    assert result.exit_code != 0, _flat(result)
    assert "nothing was written" in _flat(result)


def test_multiline_credential_is_compacted_to_one_env_line(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)
    target = module.AuthTarget(local=True, github=None)

    module._persist_credential(
        target=target,
        name="CODEX_AUTH_JSON",
        value=PRETTY_CODEX_PAYLOAD,
    )

    lines = [line for line in env_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    stored = _read_back(env_path, "CODEX_AUTH_JSON")
    assert stored is not None
    assert "\n" not in stored
    assert json.loads(stored) == json.loads(PRETTY_CODEX_PAYLOAD)


def test_multiline_non_json_credential_bails_instead_of_writing(tmp_path: Path) -> None:
    module = _load_auth_cmd()
    with pytest.raises(module.typer.Exit):
        module._single_line_credential(
            name="NOUS_API_KEY",
            value="-----BEGIN KEY-----\nabc\n",
        )


def test_gh_secret_receives_compacted_payload(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    module = _load_auth_cmd()
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)
    compact = json.dumps(json.loads(PRETTY_CODEX_PAYLOAD))
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    target = module.AuthTarget(
        local=True,
        github=module.GitHubSecretTarget(repo_slug="acme/widgets"),
    )

    module._persist_credential(target=target, name="CODEX_AUTH_JSON", value=PRETTY_CODEX_PAYLOAD)

    assert [record["name"] for record in gh.secrets] == ["CODEX_AUTH_JSON"]
    assert gh.secrets[0]["value"] == compact
    stored = _read_back(env_path, "CODEX_AUTH_JSON")
    assert stored == compact


def test_local_env_line_survives_shell_sourcing(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    module = _load_auth_cmd()
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)
    target = module.AuthTarget(local=True, github=None)
    module._persist_credential(
        target=target,
        name="CODEX_AUTH_JSON",
        value=PRETTY_CODEX_PAYLOAD,
    )

    line = next(line for line in env_path.read_text(encoding="utf-8").splitlines() if line.strip())
    assert line.startswith("CODEX_AUTH_JSON='")
    assert line.endswith("'")

    sourced = _REAL_SUBPROCESS_RUN(
        ["/bin/sh", "-c", 'set -e; . "$1"; printf %s "$CODEX_AUTH_JSON"', "sh", str(env_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert sourced.returncode == 0, sourced.stderr
    assert sourced.stdout == _read_back(env_path, "CODEX_AUTH_JSON")


def test_write_env_value_derives_quoting_from_the_value(tmp_path: Path) -> None:
    module = _load_auth_cmd()
    assert "quote_mode" not in inspect.signature(module._write_env_value).parameters

    env_path = tmp_path / ".env"
    assert module._write_env_value(env_path, "MERGECRAFT_QUOTE_DEFAULT", "plain-token") is True
    assert [line for line in env_path.read_text(encoding="utf-8").splitlines() if line.strip()] == [
        "MERGECRAFT_QUOTE_DEFAULT=plain-token"
    ]

    json_path = tmp_path / "json.env"
    payload = '{"tokens": {"access_token": "x"}}'
    assert module._write_env_value(json_path, "MERGECRAFT_QUOTE_JSON", payload) is True
    assert [
        line for line in json_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ] == [f"MERGECRAFT_QUOTE_JSON='{payload}'"]


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_logfire_local_write_restricts_env_permissions(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    _arrange_logfire(module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=True)
    env_path.chmod(0o644)

    result = runner.invoke(app, ["auth", "logfire", "--scope", "local"])

    assert result.exit_code == 0, _flat(result)
    assert _read_back(env_path, LOGFIRE_RUNTIME_ENV) is not None
    assert _mode(env_path) == 0o600


def test_write_env_value_restricts_permissions_on_a_preexisting_file(tmp_path: Path) -> None:
    module = _load_auth_cmd()
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    env_path.chmod(0o644)

    assert module._write_env_value(env_path, "MERGECRAFT_MODE_PIN", "value") is True
    assert _mode(env_path) == 0o600


def test_write_env_value_narrows_the_mode_before_the_secret_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    env_path.chmod(0o644)

    observed: list[int] = []
    real_set_key = module._dotenv_set_key

    def _recording_set_key(path: str, key: str, value: str, **kwargs: object) -> object:
        observed.append(_mode(env_path))
        return real_set_key(path, key, value, **kwargs)

    monkeypatch.setattr(module, "_dotenv_set_key", _recording_set_key)

    assert module._write_env_value(env_path, "MERGECRAFT_MODE_WINDOW", "s3cret") is True
    assert observed == [0o600]
    assert _mode(env_path) == 0o600


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "deep").mkdir(parents=True)
    _REAL_SUBPROCESS_RUN(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True, text=True
    )
    return root


def test_local_env_path_resolves_the_repo_root_from_a_subdirectory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    root = _git_repo(tmp_path)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(root / "src" / "deep")

    assert module._local_env_path() == (root / ".env").resolve()


def test_local_env_path_bails_outside_a_git_repository(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = _load_auth_cmd()
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(outside)

    with pytest.raises(module.typer.Exit):
        module._local_env_path()


def test_configured_env_path_still_wins(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    module = _load_auth_cmd()
    pinned = tmp_path / "pinned.env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(pinned))

    assert module._local_env_path() == pinned.resolve()


def test_auth_help_lists_logfire_only() -> None:
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    output = result.stdout.lower()
    assert "logfire" in output
    for removed in ("codex", "claude", "gemini", "cursor", "nous", "tokenhub", "minimax"):
        assert removed not in output
