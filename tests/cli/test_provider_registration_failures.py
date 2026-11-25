"""Provider registration failure contracts (#1592, #1593).

- #1592: a nonnumeric ``envIndex`` in the registry makes ``provider add`` and
  ``provider status`` exit with the configuration code and name the field,
  without a traceback and without touching ``config.yaml`` or ``.env``.
- #1593: a failed local label write fails ``provider add`` (and
  ``workflow provider add``) and leaves nothing behind, so repeating the same
  command registers the provider once, with the index the first attempt would
  have taken.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from tests.cli.support_provider_registry import (
    CUSTOM_BASE_URL,
    WORKFLOW_ONE_STEP_TEMPLATE,
    provider_entries,
    read_config,
    read_env_file,
    scaffold_mergecraft_home,
    scaffold_workflow_file,
    stub_mergecraft_env,
)
from typer.testing import CliRunner

from mergecraft.cli import auth_cmd, provider_cmd
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE, CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from typer.testing import Result

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1", "COLUMNS": "200"}

_BROKEN_REGISTRY = (
    "providers:\n"
    "  - label: broken\n"
    "    harness: opencode\n"
    "    envIndex: abc\n"
    "    url: https://broken.example/v1\n"
)
_ADD_ALPHA = (
    "provider",
    "add",
    "--label",
    "alpha",
    "--url",
    CUSTOM_BASE_URL,
    "--harness",
    "opencode",
)


def _invoke(*argv: str) -> Result:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _output(result: Result) -> str:
    return " ".join(_ANSI.sub("", result.stdout + result.stderr).split())


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, config_body: str = "") -> Path:
    """A throwaway git checkout with a registry and a paired ``.env``."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    config = scaffold_mergecraft_home(tmp_path, config_body=config_body)
    stub_mergecraft_env(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    return config


def _labels(tmp_path: Path) -> dict[str, str]:
    return {k: v for k, v in read_env_file(tmp_path).items() if k.startswith("LLM_PROVIDER_")}


def _raise(exc: BaseException) -> Any:
    def _raiser(*_args: object, **_kwargs: object) -> None:
        raise exc

    return _raiser


# ── #1592: malformed envIndex ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(_ADD_ALPHA, id="add"),
        pytest.param(("provider", "status"), id="status"),
        pytest.param(("provider", "status", "--json"), id="status-json"),
    ],
)
def test_nonnumeric_env_index_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: tuple[str, ...]
) -> None:
    config = _repo(tmp_path, monkeypatch, config_body=_BROKEN_REGISTRY)
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=1\n", encoding="utf-8")
    config_before = config.read_bytes()

    result = _invoke(*argv)

    output = _output(result)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, output
    assert result.exception is None or isinstance(result.exception, SystemExit), output
    assert "envIndex" in output
    assert "'broken'" in output
    assert "Traceback" not in output
    assert config.read_bytes() == config_before
    assert env_file.read_text(encoding="utf-8") == "OTHER=1\n"


def test_valid_registry_still_supports_add_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, monkeypatch)

    add = _invoke(*_ADD_ALPHA)
    status = _invoke("provider", "status")
    status_json = _invoke("provider", "status", "--json")

    assert add.exit_code == CLI_SUCCESS_EXIT_CODE, _output(add)
    assert status.exit_code == CLI_SUCCESS_EXIT_CODE, _output(status)
    assert status_json.exit_code == CLI_SUCCESS_EXIT_CODE, _output(status_json)
    assert [entry["envIndex"] for entry in provider_entries(read_config(tmp_path))] == [1]


# ── #1593: failed local label write ──────────────────────────────────────────


def test_failed_label_write_fails_add_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _repo(tmp_path, monkeypatch)
    config_before = config.read_bytes()
    monkeypatch.setattr(auth_cmd, "_dotenv_set_key", _raise(PermissionError("read-only .env")))

    result = _invoke(*_ADD_ALPHA)

    output = _output(result)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, output
    assert "registered provider" not in output
    assert "LLM_PROVIDER_1" in output
    assert "not registered" in output
    assert config.read_bytes() == config_before
    assert _labels(tmp_path) == {}


def test_repeating_add_after_a_failed_label_write_registers_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(auth_cmd, "_dotenv_set_key", _raise(PermissionError("read-only .env")))
        failed = _invoke(*_ADD_ALPHA)
    assert failed.exit_code != CLI_SUCCESS_EXIT_CODE, _output(failed)

    retry = _invoke(*_ADD_ALPHA)

    assert retry.exit_code == CLI_SUCCESS_EXIT_CODE, _output(retry)
    assert "registered provider alpha (envIndex=1" in _output(retry)
    entries = provider_entries(read_config(tmp_path))
    assert [(entry["label"], entry["envIndex"]) for entry in entries] == [("alpha", 1)]
    assert _labels(tmp_path) == {"LLM_PROVIDER_1": "alpha"}

    duplicate = _invoke(*_ADD_ALPHA)

    assert duplicate.exit_code != CLI_SUCCESS_EXIT_CODE, _output(duplicate)
    assert "duplicate provider label 'alpha'" in _output(duplicate)
    assert len(provider_entries(read_config(tmp_path))) == 1
    assert _labels(tmp_path) == {"LLM_PROVIDER_1": "alpha"}


@pytest.mark.parametrize(
    "env_before",
    [None, b"# local settings\nOTHER=1\nQUOTED='a b'\n"],
    ids=["no-env-file", "existing-env-file"],
)
def test_failed_config_write_restores_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_before: bytes | None
) -> None:
    """The rollback leaves ``.env`` exactly as it was, including absent (MC-48de7f)."""
    config = _repo(tmp_path, monkeypatch)
    env_file = tmp_path / ".env"
    if env_before is not None:
        env_file.write_bytes(env_before)
    config_before = config.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(provider_cmd, "_write_config_dict", _raise(OSError("disk full")))
        failed = _invoke(*_ADD_ALPHA)

    output = _output(failed)
    assert failed.exit_code == CLI_CONFIGURATION_EXIT_CODE, output
    assert "disk full" in output
    assert "registered provider" not in output
    assert config.read_bytes() == config_before
    assert (env_file.read_bytes() if env_file.exists() else None) == env_before

    retry = _invoke(*_ADD_ALPHA)

    assert retry.exit_code == CLI_SUCCESS_EXIT_CODE, _output(retry)
    assert [entry["envIndex"] for entry in provider_entries(read_config(tmp_path))] == [1]
    assert _labels(tmp_path) == {"LLM_PROVIDER_1": "alpha"}


def test_workflow_provider_add_rolls_back_on_a_failed_label_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other entry point that shares the label writer keeps the same contract."""
    config = _repo(tmp_path, monkeypatch)
    workflow = scaffold_workflow_file(tmp_path, WORKFLOW_ONE_STEP_TEMPLATE)
    config_before = config.read_bytes()
    argv = (
        "workflow",
        "provider",
        "add",
        "--label",
        "alpha",
        "--url",
        CUSTOM_BASE_URL,
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
        "--apply",
    )
    with monkeypatch.context() as patch:
        patch.setattr(auth_cmd, "_dotenv_set_key", _raise(PermissionError("read-only .env")))
        failed = _invoke(*argv)

    assert failed.exit_code == CLI_CONFIGURATION_EXIT_CODE, _output(failed)
    assert "LLM_PROVIDER_1" in _output(failed)
    assert config.read_bytes() == config_before
    assert workflow.read_text(encoding="utf-8") == WORKFLOW_ONE_STEP_TEMPLATE
    assert _labels(tmp_path) == {}

    retry = _invoke(*argv)

    assert retry.exit_code == CLI_SUCCESS_EXIT_CODE, _output(retry)
    entries = provider_entries(read_config(tmp_path))
    assert [(entry["label"], entry["envIndex"]) for entry in entries] == [("alpha", 1)]
    assert _labels(tmp_path) == {"LLM_PROVIDER_1": "alpha"}
    assert workflow.read_text(encoding="utf-8") != WORKFLOW_ONE_STEP_TEMPLATE
