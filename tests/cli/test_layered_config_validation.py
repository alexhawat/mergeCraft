"""Explicit validation diagnoses all contributors without changing runtime policy."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.config_surface_cmd import validate_repo_config_or_raise
from mergecraft.config import load_repo_settings


@pytest.fixture
def config_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir()
    committed = config_dir / "config.yaml"
    local = config_dir / "config.local.yaml"
    committed.write_text("shell: disabled\n", encoding="utf-8")
    local.write_text("models: []\n", encoding="utf-8")
    return tmp_path, committed, local


@pytest.mark.parametrize("terminal_width", [40, 80])
def test_malformed_base_is_reported_and_runtime_fails_closed(
    config_pair: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    terminal_width: int,
) -> None:
    from mergecraft.cli import errors

    monkeypatch.setattr(errors, "console", Console(stderr=True, width=terminal_width))
    root, committed, _local = config_pair
    assert load_repo_settings(root=root, load_learnings_files=False).shell == "disabled"
    committed.write_text("shell: disabled\nrunBounds: [\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "validate", "--cwd", str(root)])
    assert result.exit_code != 0
    assert "config parse error" in result.output
    assert str(committed) in result.output.replace("\n", "")
    # #1249 - runtime must not widen to defaults (`restricted`) on a parse error.
    with pytest.raises(ValueError, match="config parse error"):
        load_repo_settings(root=root, load_learnings_files=False)
    with pytest.raises(ValueError, match="config parse error"):
        validate_repo_config_or_raise(cwd=root)


def test_inherited_schema_error_is_not_hidden_by_local_overlay(
    config_pair: tuple[Path, Path, Path],
) -> None:
    root, committed, _local = config_pair
    committed.write_text("shell: misspelled\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["config", "validate", "--cwd", str(root)])
    assert result.exit_code != 0
    assert "shell" in result.output
    with pytest.raises(ValueError, match="shell"):
        validate_repo_config_or_raise(cwd=root)


def test_effective_override_can_replace_invalid_lower_scalar(
    config_pair: tuple[Path, Path, Path],
) -> None:
    root, committed, local = config_pair
    committed.write_text("shell: misspelled\ntracing:\n  enabled: false\n", encoding="utf-8")
    local.write_text("shell: disabled\ntracing:\n  content: 'off'\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["config", "validate", "--cwd", str(root)])
    assert result.exit_code == 0, result.output
    validate_repo_config_or_raise(cwd=root)
    settings = load_repo_settings(root=root, load_learnings_files=False)
    assert settings.shell == "disabled"
    assert settings.tracing.enabled is False


@pytest.mark.parametrize("override", ["env", "explicit"])
def test_replacement_file_excludes_broken_workspace_layers(
    config_pair: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    root, committed, local = config_pair
    committed.write_text("shell: [", encoding="utf-8")
    local.write_text("models: [", encoding="utf-8")
    replacement = root / "replacement.yaml"
    replacement.write_text("shell: disabled\n", encoding="utf-8")
    args = ["config", "validate", "--cwd", str(root)]
    if override == "env":
        monkeypatch.setenv("MERGECRAFT_CONFIG", str(replacement))
    else:
        args.extend(["--config", str(replacement)])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output


def test_ci_does_not_validate_noncontributing_local_file(
    config_pair: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _committed, local = config_pair
    local.write_text("models: [", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = CliRunner().invoke(app, ["config", "validate", "--cwd", str(root)])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("override", ["env", "explicit"])
def test_missing_requested_file_is_not_reported_as_valid(
    config_pair: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    root, _committed, _local = config_pair
    missing = root / "missing.yaml"
    args = ["config", "validate", "--cwd", str(root)]
    if override == "env":
        monkeypatch.setenv("MERGECRAFT_CONFIG", str(missing))
    else:
        args.extend(["--config", str(missing)])
    assert CliRunner().invoke(app, args).exit_code != 0


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [(b"secret-canary: [\xff", "UnicodeDecodeError"), (b"secret-canary: [", "ParserError")],
)
def test_doctor_reports_config_error_without_values(
    config_pair: tuple[Path, Path, Path], payload: bytes, error_type: str
) -> None:
    from mergecraft.cli.doctor_cmd import _config_probe

    root, committed, _local = config_pair
    committed.write_bytes(payload)
    result = _config_probe(root)
    assert result.hard_failure
    assert result.status == "fail"
    assert result.detail == f"config parse error: {committed} ({error_type})"
