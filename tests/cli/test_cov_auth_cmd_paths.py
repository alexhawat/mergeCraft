"""Decision-path coverage for ``mergecraft auth`` (issue #431).

Drives the arms of ``cli/auth_cmd.py`` the existing suite never reaches: the
``gh``/``git`` probe failures, ``--scope`` normalisation including its reject
path, the partial-failure matrix in ``_persist_credential``, ``.env`` quoting
and permission handling, the multi-line credential flattener, every status
class of every provider validator, and the cancel / warn / bail arms of the
interactive commands.

Every HTTP call goes through ``httpx.MockTransport`` — no test in this file
reaches a real provider, a real ``gh``, a real ``git``, or a real ``.env``.
"""

from __future__ import annotations

import getpass
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import typer
from dotenv import dotenv_values
from typer.testing import CliRunner

from mergecraft.cli import auth_cmd
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE, CLI_USAGE_EXIT_CODE

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_ENV_WIDE = {"COLUMNS": "200", "TERM": "dumb"}


def _mock_httpx(
    monkeypatch: MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Route every ``httpx.Client`` the auth module builds through ``handler``."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_cmd.httpx, "Client", _factory)


def _status(code: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(code, json={})


def _raiser(exc: Exception) -> Callable[..., Any]:
    """A stand-in callable that raises ``exc`` no matter how it is called."""

    def _handler(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _handler


def _local_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> Path:
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    return env_path


# ---------------------------------------------------------------------------
# gh / git probes
# ---------------------------------------------------------------------------


def test_gh_token_probe_bails_when_the_cli_is_missing(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_cmd.subprocess, "check_output", _raiser(FileNotFoundError("gh")), raising=True
    )
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._get_gh_token()
    assert excinfo.value.exit_code == CLI_CONFIGURATION_EXIT_CODE


def test_gh_token_probe_bails_on_an_empty_token(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(auth_cmd.subprocess, "check_output", lambda *a, **k: "  \n")
    with pytest.raises(typer.Exit):
        auth_cmd._get_gh_token()
    assert "empty token" in capsys.readouterr().err


def test_gh_token_probe_returns_the_stripped_token(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(auth_cmd.subprocess, "check_output", lambda *a, **k: "ghp_abc\n")
    assert auth_cmd._get_gh_token() == "ghp_abc"


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@github.com:acme/widgets.git", ("acme", "widgets")),
        ("https://github.com/acme/widgets/", ("acme", "widgets")),
        ("ssh://git@github.com:22/acme/deep.repo", ("acme", "deep.repo")),
    ],
)
def test_git_remote_parser_accepts_the_supported_url_shapes(
    monkeypatch: MonkeyPatch, remote: str, expected: tuple[str, str]
) -> None:
    monkeypatch.setattr(auth_cmd.subprocess, "check_output", lambda *a, **k: remote + "\n")
    assert auth_cmd._parse_git_remote() == expected


def test_git_remote_parser_bails_on_a_non_github_remote(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        auth_cmd.subprocess, "check_output", lambda *a, **k: "https://gitlab.com/acme/widgets.git\n"
    )
    with pytest.raises(typer.Exit):
        auth_cmd._parse_git_remote()
    assert "could not parse github owner/repo" in capsys.readouterr().err


def test_git_remote_parser_bails_when_there_is_no_origin(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_cmd.subprocess,
        "check_output",
        _raiser(subprocess.CalledProcessError(2, ["git"])),
    )
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._parse_git_remote()
    assert excinfo.value.exit_code == CLI_CONFIGURATION_EXIT_CODE


def test_set_gh_secret_reports_failure_instead_of_raising(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_cmd.subprocess,
        "run",
        _raiser(subprocess.CalledProcessError(1, ["gh"])),
    )
    assert auth_cmd._set_gh_secret(name="X", value="v", repo_slug="acme/widgets") is False


def test_set_gh_secret_passes_the_value_on_stdin(monkeypatch: MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def _run(cmd: list[str], **kwargs: Any) -> Any:
        seen["cmd"] = cmd
        seen["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(auth_cmd.subprocess, "run", _run)
    assert auth_cmd._set_gh_secret(name="X", value="v", repo_slug="acme/widgets") is True
    assert seen["cmd"] == ["gh", "secret", "set", "X", "--repo", "acme/widgets"]
    assert seen["input"] == "v"


# ---------------------------------------------------------------------------
# scope normalisation and target resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("local", "local"),
        (" LOCAL ", "local"),
        ("github", "github"),
        ("gh", "github"),
        ("action", "github"),
        ("both", "both"),
        ("all", "both"),
    ],
)
def test_scope_synonyms_normalise_to_the_three_canonical_values(raw: str, expected: str) -> None:
    assert auth_cmd._normalise_scope(raw) == expected


def test_unknown_scope_is_a_usage_error_naming_the_valid_values(
    capsys: CaptureFixture[str],
) -> None:
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._normalise_scope("remote")
    assert excinfo.value.exit_code == CLI_USAGE_EXIT_CODE
    assert "expected one of: local, github, both" in capsys.readouterr().err


def test_local_scope_never_touches_gh_or_git(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(auth_cmd, "_get_gh_token", _raiser(AssertionError("gh probed")))
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", _raiser(AssertionError("git probed")))
    target = auth_cmd._resolve_auth_target("local")
    assert target == auth_cmd.AuthTarget(local=True, github=None)


def test_github_and_both_scopes_resolve_the_repo_slug(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: "ghp_abc")
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", lambda: ("acme", "widgets"))
    github_only = auth_cmd._resolve_auth_target("github")
    assert github_only.local is False
    assert github_only.github == auth_cmd.GitHubSecretTarget(repo_slug="acme/widgets")
    assert auth_cmd._resolve_auth_target("both").local is True


# ---------------------------------------------------------------------------
# .env writing
# ---------------------------------------------------------------------------


def test_env_path_prefers_the_override_then_the_repo_root(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / "custom.env"))
    assert auth_cmd._local_env_path() == (tmp_path / "custom.env").resolve()
    monkeypatch.delenv("MERGECRAFT_ENV")
    monkeypatch.setattr(auth_cmd, "git_repo_root", lambda: tmp_path)
    assert auth_cmd._local_env_path() == tmp_path / ".env"


def test_env_path_bails_outside_a_repository(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.setattr(auth_cmd, "git_repo_root", lambda: None)
    with pytest.raises(typer.Exit):
        auth_cmd._local_env_path()
    assert "could not locate the repository root" in capsys.readouterr().err


def test_env_writer_quotes_only_values_that_need_it(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    assert auth_cmd._write_env_value(env_path, "NOUS_API_KEY", "nk-abc_123") is True
    assert auth_cmd._write_env_value(env_path, "CODEX_AUTH_JSON", '{"a": "b"}') is True
    raw = env_path.read_text(encoding="utf-8")
    assert "NOUS_API_KEY=nk-abc_123" in raw
    assert 'CODEX_AUTH_JSON=\'{"a": "b"}\'' in raw
    assert dotenv_values(env_path)["CODEX_AUTH_JSON"] == '{"a": "b"}'


def test_env_writer_reports_failure_rather_than_raising(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auth_cmd, "_dotenv_set_key", _raiser(OSError("read-only fs")))
    assert auth_cmd._write_env_value(tmp_path / ".env", "K", "v") is False


def test_env_writer_still_succeeds_when_the_file_cannot_be_narrowed(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """A failed ``chmod`` is a warning — refusing to save the credential is worse."""
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")

    def _chmod(_self: Path, _mode: int) -> None:
        raise OSError("chmod not permitted")

    monkeypatch.setattr(Path, "chmod", _chmod)
    assert auth_cmd._write_env_value(env_path, "NOUS_API_KEY", "nk-abc") is True
    assert dotenv_values(env_path)["NOUS_API_KEY"] == "nk-abc"


def test_env_writer_narrows_permissions_on_an_existing_world_readable_file(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    env_path.chmod(0o644)
    assert auth_cmd._write_env_value(env_path, "NOUS_API_KEY", "nk-abc") is True
    assert env_path.stat().st_mode & 0o777 == 0o600


# ---------------------------------------------------------------------------
# _single_line_credential
# ---------------------------------------------------------------------------


def test_single_line_credential_passes_a_one_line_value_through_untouched() -> None:
    assert auth_cmd._single_line_credential(name="K", value="sk-abc") == "sk-abc"


def test_single_line_credential_compacts_pretty_printed_json() -> None:
    pretty = json.dumps({"tokens": {"access_token": "a"}}, indent=2)
    compacted = auth_cmd._single_line_credential(name="CODEX_AUTH_JSON", value=pretty)
    assert "\n" not in compacted
    assert json.loads(compacted) == json.loads(pretty)


def test_single_line_credential_refuses_a_multi_line_non_json_value(
    capsys: CaptureFixture[str],
) -> None:
    with pytest.raises(typer.Exit):
        auth_cmd._single_line_credential(name="CODEX_AUTH_JSON", value="line one\nline two")
    err = capsys.readouterr().err
    assert "spans multiple lines and is not JSON" in err
    assert "--scope github" in err


# ---------------------------------------------------------------------------
# _persist_credential — the partial-failure matrix
# ---------------------------------------------------------------------------


def test_local_only_success_writes_env_and_never_calls_gh(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd, "_set_gh_secret", _raiser(AssertionError("gh called")))
    auth_cmd._persist_credential(
        target=auth_cmd.AuthTarget(local=True, github=None), name="NOUS_API_KEY", value="nk-1"
    )
    assert dotenv_values(env_path)["NOUS_API_KEY"] == "nk-1"
    assert "wrote NOUS_API_KEY" in capsys.readouterr().err


def test_local_only_failure_bails_because_nothing_was_written(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd, "_write_env_value", lambda *a, **k: False)
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._persist_credential(
            target=auth_cmd.AuthTarget(local=True, github=None), name="NOUS_API_KEY", value="nk-1"
        )
    assert excinfo.value.exit_code == CLI_CONFIGURATION_EXIT_CODE
    err = capsys.readouterr().err
    assert "could not update" in err
    assert "nothing was written" in err


def test_github_only_failure_bails_with_the_manual_secrets_url(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(auth_cmd, "_set_gh_secret", lambda **_k: False)
    target = auth_cmd.AuthTarget(
        local=False, github=auth_cmd.GitHubSecretTarget(repo_slug="acme/widgets")
    )
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._persist_credential(target=target, name="NOUS_API_KEY", value="nk-1")
    assert excinfo.value.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "https://github.com/acme/widgets/settings/secrets/actions" in capsys.readouterr().err


def test_both_scope_tolerates_a_failed_secret_when_the_local_write_landed(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Partial success: the operator still got a usable local credential."""
    env_path = _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd, "_set_gh_secret", lambda **_k: False)
    target = auth_cmd.AuthTarget(
        local=True, github=auth_cmd.GitHubSecretTarget(repo_slug="acme/widgets")
    )
    auth_cmd._persist_credential(target=target, name="NOUS_API_KEY", value="nk-1")
    assert dotenv_values(env_path)["NOUS_API_KEY"] == "nk-1"
    assert "gh secret set failed" in capsys.readouterr().err


def test_both_scope_bails_only_when_neither_half_lands(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd, "_write_env_value", lambda *a, **k: False)
    monkeypatch.setattr(auth_cmd, "_set_gh_secret", lambda **_k: False)
    target = auth_cmd.AuthTarget(
        local=True, github=auth_cmd.GitHubSecretTarget(repo_slug="acme/widgets")
    )
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._persist_credential(target=target, name="NOUS_API_KEY", value="nk-1")
    assert excinfo.value.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "both local and github scopes failed" in capsys.readouterr().err


def test_local_entries_override_the_secret_pair_for_the_env_write(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """``auth logfire`` writes two env vars behind one Actions secret."""
    env_path = _local_env(monkeypatch, tmp_path)
    sent: dict[str, Any] = {}
    monkeypatch.setattr(
        auth_cmd, "_set_gh_secret", lambda **kwargs: bool(sent.update(kwargs) or True)
    )
    target = auth_cmd.AuthTarget(
        local=True, github=auth_cmd.GitHubSecretTarget(repo_slug="acme/widgets")
    )
    auth_cmd._persist_credential(
        target=target,
        name="LOGFIRE_TOKEN",
        value="pylf_v1_eu_abc",
        local_entries={
            "MERGECRAFT_LOGFIRE_TOKEN": "pylf_v1_eu_abc",
            "MERGECRAFT_TRACING_PROJECT": "mergecraft",
        },
    )
    values = dotenv_values(env_path)
    assert values["MERGECRAFT_LOGFIRE_TOKEN"] == "pylf_v1_eu_abc"
    assert values["MERGECRAFT_TRACING_PROJECT"] == "mergecraft"
    assert "LOGFIRE_TOKEN" not in values
    assert sent == {"name": "LOGFIRE_TOKEN", "value": "pylf_v1_eu_abc", "repo_slug": "acme/widgets"}


# ---------------------------------------------------------------------------
# provider validators
# ---------------------------------------------------------------------------

_VALIDATORS: list[tuple[str, str]] = [
    ("_validate_gemini_api_key", "gemini"),
    ("_validate_cursor_api_key", "cursor"),
    ("_validate_nous_api_key", "nous"),
    ("_validate_minimax_api_key", "minimax"),
]


@pytest.mark.parametrize(("attr", "_label"), _VALIDATORS)
def test_validators_accept_200_reject_401_403_and_save_anyway_on_5xx(
    monkeypatch: MonkeyPatch, attr: str, _label: str
) -> None:
    validate = getattr(auth_cmd, attr)
    for code, expected in ((200, True), (401, False), (403, False), (503, True)):
        _mock_httpx(monkeypatch, _status(code))
        assert validate("key-under-test") is expected, f"{attr} on HTTP {code}"


@pytest.mark.parametrize(("attr", "_label"), _VALIDATORS)
def test_validators_save_anyway_when_the_probe_cannot_reach_the_provider(
    monkeypatch: MonkeyPatch, attr: str, _label: str
) -> None:
    _mock_httpx(monkeypatch, _raiser(httpx.ConnectError("dns failure")))
    assert getattr(auth_cmd, attr)("key-under-test") is True


def test_openai_compatible_validator_probes_the_models_endpoint_with_a_bearer(
    monkeypatch: MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={})

    _mock_httpx(monkeypatch, _handler)
    assert (
        auth_cmd._validate_openai_compatible_key(
            api_key="th-key", base_url="https://gw.invalid/v1/", label="tokenhub"
        )
        is True
    )
    assert seen["url"].startswith("https://gw.invalid/v1/models")
    assert seen["auth"] == "Bearer th-key"


def test_openai_compatible_validator_rejects_401_and_tolerates_network_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    _mock_httpx(monkeypatch, _status(401))
    assert (
        auth_cmd._validate_openai_compatible_key(
            api_key="bad", base_url="https://gw.invalid/v1", label="tokenhub"
        )
        is False
    )
    _mock_httpx(monkeypatch, _raiser(httpx.ReadTimeout("slow")))
    assert (
        auth_cmd._validate_openai_compatible_key(
            api_key="bad", base_url="https://gw.invalid/v1", label="tokenhub"
        )
        is True
    )


# ---------------------------------------------------------------------------
# logfire probe selection + validation
# ---------------------------------------------------------------------------


def test_logfire_probe_picks_the_regional_host_for_a_write_token() -> None:
    assert auth_cmd._resolve_logfire_probe("pylf_v1_eu_abc") == (
        "https://logfire-eu.pydantic.dev/v1/info",
        "write-token",
    )
    assert auth_cmd._resolve_logfire_probe("pylf_v2_us_abc") == (
        "https://logfire-us.pydantic.dev/v1/info",
        "write-token",
    )


def test_logfire_probe_falls_back_to_the_management_api() -> None:
    """An unknown region and a non-write-token shape both probe the API key path."""
    assert auth_cmd._resolve_logfire_probe("pylf_v1_zz_abc") == (
        auth_cmd.LOGFIRE_API_PROBE_URL,
        "api-key",
    )
    assert auth_cmd._resolve_logfire_probe("lf_api_key_abc") == (
        auth_cmd.LOGFIRE_API_PROBE_URL,
        "api-key",
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [(200, True), (401, False), (403, False), (302, False), (307, False), (500, True)],
)
def test_logfire_token_validation_rejects_redirects_as_well_as_401(
    monkeypatch: MonkeyPatch, code: int, expected: bool
) -> None:
    _mock_httpx(monkeypatch, _status(code))
    assert auth_cmd._validate_logfire_token("pylf_v1_eu_abc") is expected


def test_logfire_token_validation_saves_anyway_when_offline(monkeypatch: MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, _raiser(httpx.ConnectError("offline")))
    assert auth_cmd._validate_logfire_token("pylf_v1_eu_abc") is True


def test_logfire_extra_probe_reports_absence_without_raising(monkeypatch: MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "logfire":
            msg = "no module named logfire"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert auth_cmd._logfire_extra_installed() is False


# ---------------------------------------------------------------------------
# interactive command arms
# ---------------------------------------------------------------------------


def _stub_getpass(monkeypatch: MonkeyPatch, value: str | BaseException) -> None:
    """Replace the interactive prompt with a fixed answer — or a raised signal."""

    def _prompt(_label: str = "") -> str:
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(getpass, "getpass", _prompt)


def test_empty_input_cancels_cleanly_without_writing_anything(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "   ")
    result = runner.invoke(app, ["auth", "claude", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "canceled." in result.stdout + result.stderr
    assert not env_path.exists()


def test_a_keyboard_interrupt_at_the_prompt_cancels_cleanly(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, KeyboardInterrupt())
    result = runner.invoke(app, ["auth", "gemini", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "canceled." in result.stdout + result.stderr
    assert not env_path.exists()


def test_claude_warns_about_an_unexpected_prefix_but_still_saves(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "ghp_not_an_oauth_token")
    result = runner.invoke(app, ["auth", "claude", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "doesn't look like a claude setup-token" in result.stdout + result.stderr
    assert dotenv_values(env_path)["CLAUDE_CODE_OAUTH_TOKEN"] == "ghp_not_an_oauth_token"


def test_a_rejected_provider_key_bails_before_writing_the_env(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "bad-key")
    _mock_httpx(monkeypatch, _status(401))
    result = runner.invoke(app, ["auth", "gemini", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "Gemini API key validation failed" in result.stdout + result.stderr
    assert not env_path.exists()


def test_codex_bails_when_the_cli_is_not_on_path(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd.shutil, "which", lambda _name: None)
    result = runner.invoke(app, ["auth", "codex", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "codex CLI not found on PATH" in result.stdout + result.stderr


def test_codex_bails_when_the_login_writes_no_auth_json(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd.shutil, "which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr(
        auth_cmd.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0)
    )
    result = runner.invoke(app, ["auth", "codex", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "no auth.json was written" in result.stdout + result.stderr


def test_codex_bails_when_the_login_command_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd.shutil, "which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr(
        auth_cmd.subprocess, "run", _raiser(subprocess.CalledProcessError(7, ["codex"]))
    )
    result = runner.invoke(app, ["auth", "codex", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "codex login failed (exit 7)" in result.stdout + result.stderr


def test_nous_success_names_the_model_slug_to_configure(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "nk-good")
    _mock_httpx(monkeypatch, _status(200))
    result = runner.invoke(app, ["auth", "nous", "--scope", "local"], env=_ENV_WIDE)
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert dotenv_values(env_path)["NOUS_API_KEY"] == "nk-good"
    assert "nous/deepseek/deepseek-v4-flash" in combined


def test_tokenhub_rejects_a_bad_key_and_keeps_the_env_untouched(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "th-bad")
    _mock_httpx(monkeypatch, _status(403))
    result = runner.invoke(app, ["auth", "tokenhub", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "TokenHub API key validation failed" in result.stdout + result.stderr
    assert not env_path.exists()


def test_minimax_rejects_a_bad_key_and_names_the_custom_provider_secret(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "mm-good")
    _mock_httpx(monkeypatch, _status(200))
    result = runner.invoke(app, ["auth", "minimax", "--scope", "local"], env=_ENV_WIDE)
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert dotenv_values(env_path)["MERGECRAFT_CUSTOM_PROVIDER_API_KEY"] == "mm-good"
    assert "minimax/MiniMax-M3" in combined


def test_an_invalid_scope_stops_the_command_before_the_prompt(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, AssertionError("prompted despite a bad scope"))
    result = runner.invoke(app, ["auth", "cursor", "--scope", "remote"], env=_ENV_WIDE)
    assert result.exit_code == CLI_USAGE_EXIT_CODE
    assert "expected one of: local, github, both" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# auth logfire
# ---------------------------------------------------------------------------


def test_logfire_cancels_when_the_project_label_is_left_blank(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "pylf_v1_eu_token")
    _mock_httpx(monkeypatch, _status(200))
    result = runner.invoke(app, ["auth", "logfire", "--scope", "local"], input="\n", env=_ENV_WIDE)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "canceled." in result.stdout + result.stderr
    assert not env_path.exists()


def test_logfire_rejects_a_project_label_containing_whitespace(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "pylf_v1_eu_token")
    _mock_httpx(monkeypatch, _status(200))
    result = runner.invoke(
        app, ["auth", "logfire", "--scope", "local"], input="my project\n", env=_ENV_WIDE
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "must not contain whitespace" in result.stdout + result.stderr
    assert not env_path.exists()


def test_logfire_bails_on_a_rejected_token_before_asking_for_a_project(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "pylf_v1_eu_token")
    _mock_httpx(monkeypatch, _status(302))
    result = runner.invoke(app, ["auth", "logfire", "--scope", "local"], env=_ENV_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "Logfire token validation failed" in result.stdout + result.stderr
    assert not env_path.exists()


def test_logfire_warns_when_the_tracing_extra_is_missing_but_still_saves(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_path = _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "pylf_v1_eu_token")
    _mock_httpx(monkeypatch, _status(200))
    monkeypatch.setattr(auth_cmd, "_logfire_extra_installed", lambda: False)
    result = runner.invoke(
        app, ["auth", "logfire", "--scope", "local"], input="mergecraft\n", env=_ENV_WIDE
    )
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "the [tracing] extra is not installed" in combined
    values = dotenv_values(env_path)
    assert values["MERGECRAFT_LOGFIRE_TOKEN"] == "pylf_v1_eu_token"
    assert values["MERGECRAFT_TRACING_PROJECT"] == "mergecraft"


def test_logfire_skips_the_extra_warning_when_the_package_is_present(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _local_env(monkeypatch, tmp_path)
    _stub_getpass(monkeypatch, "pylf_v1_eu_token")
    _mock_httpx(monkeypatch, _status(200))
    monkeypatch.setattr(auth_cmd, "_logfire_extra_installed", lambda: True)
    result = runner.invoke(
        app, ["auth", "logfire", "--scope", "local"], input="mergecraft\n", env=_ENV_WIDE
    )
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "extra is not installed" not in combined
    assert "mergecraft config tracing" in combined
