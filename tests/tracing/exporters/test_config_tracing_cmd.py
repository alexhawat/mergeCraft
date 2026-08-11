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


def test_config_tracing_shows_local_sinks_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A disabled tracing config prints a ``local sinks: none`` row.

    sevn's ``show_tracing_config`` always surfaces the local-sink state even
    when tracing is off; the operator should see at a glance that no sink
    (local or remote) is attached. We mirror that in ``config_tracing``.
    """
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
    out = _plain(result.stdout)
    assert "local sinks" in out.lower()
    assert "none" in out.lower()


def test_config_tracing_lists_trace_env_vars_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Disabled config lists the ``MERGECRAFT_*`` env vars that drive tracing.

    The row tells the operator exactly which keys to set. When the operator
    already has some set (e.g. from a prior ``auth logfire`` run), those names
    appear; otherwise the row shows ``(none set)``.
    """
    config = tmp_path / "config.yaml"
    config.write_text("", encoding="utf-8")
    # Simulate an operator who ran ``auth logfire`` but has not enabled tracing.
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_v2_eu_test")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "mergecraft-dev")

    from mergecraft.cli.app import app

    result = _RUNNER.invoke(
        app,
        ["config", "tracing"],
        env={
            "NO_COLOR": "1",
            "TERM": "dumb",
            "MERGECRAFT_CONFIG": str(config),
            "MERGECRAFT_LOGFIRE_TOKEN": "pylf_v2_eu_test",
            "MERGECRAFT_TRACING_PROJECT": "mergecraft-dev",
        },
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert "trace env" in out.lower()
    assert "MERGECRAFT_LOGFIRE_TOKEN" in out
    assert "MERGECRAFT_TRACING_PROJECT" in out


def test_config_tracing_prints_next_steps_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Disabled config prints the next-step hints (sevn: ``show_tracing_config``).

    The block lists the symmetric commands (``mergecraft tracing logfire
    enable`` with and without flags, plus the local/env path) so the operator
    knows how to turn tracing on without re-reading docs.
    """
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
    assert "next steps" in out
    assert "mergecraft tracing logfire enable" in out
    assert "--token" in out
    assert "--project" in out


def test_config_tracing_omits_next_steps_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Enabled config does not print the remediation hints (the table is enough)."""
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
    out = _plain(result.stdout).lower()
    assert "enabled" in out
    assert "next steps" not in out


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
