"""CC2 — ``mergecraft doctor`` environment probes (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC2.1** (RED). Implementation: **CC2.2**.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_REQUIRED_PROBE_LABELS = ("git", "provider", "analyzer", "auth", "config", "mcp")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _init_git_repo(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "doctor@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Doctor Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("probe\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_reports_git_provider_analyzer_auth_config_rows(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Doctor prints a table row for git, provider, analyzer, auth, config, and MCP."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["doctor"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == 0, output
    for label in _REQUIRED_PROBE_LABELS:
        assert label in output, f"missing doctor probe row for {label!r}: {output}"


def test_exits_nonzero_on_a_hard_failure(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A hard probe failure (unparseable config) yields a non-zero exit code."""
    _init_git_repo(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("not: [valid: yaml\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["doctor"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != 0, output
    assert "config" in output.lower(), output


def test_never_prints_a_credential_value(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Doctor reports auth presence but never echoes credential material."""
    _init_git_repo(tmp_path)
    secret = "sk-super-secret-doctor-token-abc123"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "lf-doctor-secret-xyz")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["doctor"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert secret not in output
    assert "lf-doctor-secret-xyz" not in output
    assert "auth" in output.lower()


def test_doctor_mcp_probe_does_not_treat_3764_as_the_mcp_port(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """W14.2: doctor may report ephemeral / in-use, not a fixed 3764 band."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["doctor"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert "mcp" in output.lower()
    lowered = output.lower()
    names_fixed_port = "3764" in lowered and "ephemeral" not in lowered
    assert not names_fixed_port, output
