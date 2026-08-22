"""Batch HE — auth partial local write honesty (#437).

Pins that a mixed local write of the logfire pair
(``MERGECRAFT_LOGFIRE_TOKEN`` + ``MERGECRAFT_TRACING_PROJECT``) is not
collapsed into "nothing was written" and does not name the Actions secret
``LOGFIRE_TOKEN`` when the failed keys were local env vars.

Moved from ``tests/cli/test_cov_auth_cmd_paths.py`` (strict xfail from #431)
with non-strict W10 markers.
"""

from __future__ import annotations

import contextlib
import getpass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import typer
from dotenv import dotenv_values
from typer.testing import CliRunner

from mergecraft.cli import auth_cmd
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_ENV_WIDE = {"COLUMNS": "200", "TERM": "dumb"}

_LOGFIRE_LOCAL_ENTRIES = {
    "MERGECRAFT_LOGFIRE_TOKEN": "pylf_v1_eu_abc",
    "MERGECRAFT_TRACING_PROJECT": "mergecraft",
}


def _local_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> Path:
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    return env_path


def _patch_write_fail_key(monkeypatch: MonkeyPatch, fail_key: str) -> None:
    real_write = auth_cmd._write_env_value

    def _write(path: Path, key: str, value: str) -> bool:
        if key == fail_key:
            return False
        return real_write(path, key, value)

    monkeypatch.setattr(auth_cmd, "_write_env_value", _write)


def _mock_httpx(
    monkeypatch: MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_cmd.httpx, "Client", _factory)


# --- #437 partial local write — _persist_credential unit contracts ----------


@pytest.mark.xfail(
    reason="green after W10: report partial local auth writes honestly (#437)",
    strict=False,
)
def test_partial_local_write_must_not_claim_that_nothing_was_written(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """When the project label lands but the token write fails, disk is not empty."""
    env_path = _local_env(monkeypatch, tmp_path)
    _patch_write_fail_key(monkeypatch, "MERGECRAFT_LOGFIRE_TOKEN")
    auth_cmd._persist_credential(
        target=auth_cmd.AuthTarget(local=True, github=None),
        name="LOGFIRE_TOKEN",
        value="pylf_v1_eu_abc",
        local_entries=_LOGFIRE_LOCAL_ENTRIES,
    )
    assert dotenv_values(env_path)["MERGECRAFT_TRACING_PROJECT"] == "mergecraft"
    assert "nothing was written" not in capsys.readouterr().err


@pytest.mark.xfail(
    reason="green after W10: report partial local auth writes honestly (#437)",
    strict=False,
)
def test_partial_local_write_must_not_name_actions_secret_in_stderr(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Local-only failures must name env keys, not the Actions secret ``LOGFIRE_TOKEN``."""
    _local_env(monkeypatch, tmp_path)
    _patch_write_fail_key(monkeypatch, "MERGECRAFT_LOGFIRE_TOKEN")
    with contextlib.suppress(typer.Exit):
        auth_cmd._persist_credential(
            target=auth_cmd.AuthTarget(local=True, github=None),
            name="LOGFIRE_TOKEN",
            value="pylf_v1_eu_abc",
            local_entries=_LOGFIRE_LOCAL_ENTRIES,
        )
    err = capsys.readouterr().err
    assert "LOGFIRE_TOKEN" not in err
    assert "MERGECRAFT_LOGFIRE_TOKEN" in err or "MERGECRAFT_TRACING_PROJECT" in err


@pytest.mark.xfail(
    reason="green after W10: report partial local auth writes honestly (#437)",
    strict=False,
)
def test_partial_local_write_reports_which_local_keys_landed(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A mixed result must report the env keys that did land, not deny all writes."""
    env_path = _local_env(monkeypatch, tmp_path)
    _patch_write_fail_key(monkeypatch, "MERGECRAFT_LOGFIRE_TOKEN")
    auth_cmd._persist_credential(
        target=auth_cmd.AuthTarget(local=True, github=None),
        name="LOGFIRE_TOKEN",
        value="pylf_v1_eu_abc",
        local_entries=_LOGFIRE_LOCAL_ENTRIES,
    )
    assert dotenv_values(env_path)["MERGECRAFT_TRACING_PROJECT"] == "mergecraft"
    err = capsys.readouterr().err
    assert "MERGECRAFT_TRACING_PROJECT" in err or "mergecraft" in err


@pytest.mark.xfail(
    reason="green after W10: report partial local auth writes honestly (#437)",
    strict=False,
)
def test_partial_local_write_token_landed_when_project_write_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Reverse partial: token on disk when only the project label write fails."""
    env_path = _local_env(monkeypatch, tmp_path)
    _patch_write_fail_key(monkeypatch, "MERGECRAFT_TRACING_PROJECT")
    auth_cmd._persist_credential(
        target=auth_cmd.AuthTarget(local=True, github=None),
        name="LOGFIRE_TOKEN",
        value="pylf_v1_eu_abc",
        local_entries=_LOGFIRE_LOCAL_ENTRIES,
    )
    assert dotenv_values(env_path)["MERGECRAFT_LOGFIRE_TOKEN"] == "pylf_v1_eu_abc"
    assert "nothing was written" not in capsys.readouterr().err


# --- #437 CLI integration — auth logfire --scope local ----------------------


@pytest.mark.xfail(
    reason="green after W10: report partial local auth writes honestly (#437)",
    strict=False,
)
def test_auth_logfire_scope_local_partial_write_is_honest(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """``auth logfire --scope local`` must not claim nothing landed on a partial write."""
    env_path = _local_env(monkeypatch, tmp_path)
    _patch_write_fail_key(monkeypatch, "MERGECRAFT_LOGFIRE_TOKEN")
    _mock_httpx(monkeypatch, lambda _request: httpx.Response(200, json=[]))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "pylf_v1_eu_token")
    result = runner.invoke(
        app,
        ["auth", "logfire", "--scope", "local"],
        input="mergecraft\n",
        env=_ENV_WIDE,
    )
    combined = result.stdout + result.stderr
    assert dotenv_values(env_path)["MERGECRAFT_TRACING_PROJECT"] == "mergecraft"
    assert "nothing was written" not in combined
    assert "LOGFIRE_TOKEN" not in combined


# --- regression guard — total local failure may still bail honestly ----------


def test_total_local_failure_may_still_report_nothing_was_written(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """When every local entry fails, the existing bail message remains valid."""
    _local_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cmd, "_write_env_value", lambda *a, **k: False)
    with pytest.raises(typer.Exit) as excinfo:
        auth_cmd._persist_credential(
            target=auth_cmd.AuthTarget(local=True, github=None),
            name="LOGFIRE_TOKEN",
            value="pylf_v1_eu_abc",
            local_entries=_LOGFIRE_LOCAL_ENTRIES,
        )
    assert excinfo.value.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "nothing was written" in capsys.readouterr().err
