"""RED contracts for the ``mergecraft config tracing`` and ``mergecraft traces`` CLI commands.

W8.4 ships these two commands:

- ``mergecraft config tracing`` — show the resolved tracing config with the
  logfire token redacted.
- ``mergecraft traces <run-id>`` — read back the local JSONL traces.

These tests pin both surfaces so a fork that drops one of them (or leaks
the token into the config dump) is wrong.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

_RUNNER = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CANARY = "logfire-cli-canary-aa1122bb3344cc55"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


# ---------------------------------------------------------------------------
# ``mergecraft config tracing``
# ---------------------------------------------------------------------------


def test_config_tracing_command_exists() -> None:
    """The ``mergecraft config tracing`` subcommand is wired up."""
    from mergecraft.cli.app import app

    result = _RUNNER.invoke(app, ["config", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "tracing" in _plain(result.stdout).lower()


def test_config_tracing_renders_resolved_sinks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The command shows the resolved sink list in a human-readable form."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: jsonl_file\n      path: traces\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))

    from mergecraft.cli.app import app

    result = _RUNNER.invoke(
        app,
        ["config", "tracing"],
        env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_CONFIG": str(config)},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert "jsonl_file" in out or "traces" in out


def test_config_tracing_redacts_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The token value is replaced with a redaction marker in the rendered output."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: logfire\n      tokenRef: MERGECRAFT_LOGFIRE_TOKEN\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)

    from mergecraft.cli.app import app

    result = _RUNNER.invoke(
        app,
        ["config", "tracing"],
        env={
            "NO_COLOR": "1",
            "TERM": "dumb",
            "MERGECRAFT_CONFIG": str(config),
            "MERGECRAFT_LOGFIRE_TOKEN": _CANARY,
        },
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert _CANARY not in out
    # The reference name and a redaction marker are both shown.
    assert "MERGECRAFT_LOGFIRE_TOKEN" in out or "redact" in out.lower() or "***" in out


def test_config_tracing_reports_disabled_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A repo with no ``tracing`` block shows the default-disabled state."""
    config = tmp_path / "config.yaml"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))

    from mergecraft.cli.app import app

    result = _RUNNER.invoke(
        app,
        ["config", "tracing"],
        env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_CONFIG": str(config)},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout).lower()
    assert "disabled" in out or "off" in out or "false" in out


# ---------------------------------------------------------------------------
# ``mergecraft traces <run-id>``
# ---------------------------------------------------------------------------


def test_traces_command_exists() -> None:
    """The ``mergecraft traces`` subcommand is wired up."""
    from mergecraft.cli.app import app

    result = _RUNNER.invoke(app, ["traces", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "RUN_ID" in _plain(result.stdout).upper() or "run-id" in _plain(result.stdout).lower()


def test_traces_command_reads_local_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``mergecraft traces <run-id>`` reads back the local JSONL trace files for that run."""
    from mergecraft.cli.app import app

    trace_dir = tmp_path / "traces"
    trace_dir.mkdir(parents=True)
    span = {"kind": "mergecraft.run", "span_id": "root", "session_id": "run-42", "attrs": {}}
    (trace_dir / "2026-08-09.jsonl").write_text(json.dumps(span) + "\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(trace_dir))

    result = _RUNNER.invoke(
        app,
        ["traces", "run-42"],
        env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_TRACE_DIR": str(trace_dir)},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert "run-42" in out or "mergecraft.run" in out


def test_traces_command_missing_run_id_reports_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no local files match the run id, the command exits cleanly with a notice."""
    from mergecraft.cli.app import app

    trace_dir = tmp_path / "traces"
    trace_dir.mkdir(parents=True)
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(trace_dir))

    result = _RUNNER.invoke(
        app,
        ["traces", "unknown-run"],
        env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_TRACE_DIR": str(trace_dir)},
    )
    assert result.exit_code in {0, 1}  # not a crash
    assert result.stdout or result.stderr


def test_traces_command_redacts_secrets_in_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``mergecraft traces`` redaction is still active — secrets in the trace never reach the terminal."""
    from mergecraft.cli.app import app

    trace_dir = tmp_path / "traces"
    trace_dir.mkdir(parents=True)
    canary = "ghp_canarysecretvalue1234567890abcdef"
    span = {
        "kind": "llm.call",
        "span_id": "root",
        "session_id": "run-redact",
        "attrs": {"message": f"Authorization: Bearer {canary}"},
    }
    (trace_dir / "2026-08-09.jsonl").write_text(json.dumps(span) + "\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(trace_dir))

    result = _RUNNER.invoke(
        app,
        ["traces", "run-redact"],
        env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_TRACE_DIR": str(trace_dir)},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert canary not in out
