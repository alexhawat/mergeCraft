"""CC2 — ``mergecraft config show|explain|validate`` (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC2.1** (RED). Implementation: **CC2.2**.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_CC2_2_XFAIL = pytest.mark.xfail(reason="green after CC2.2: config surface verbs", strict=False)

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@_CC2_2_XFAIL
def test_config_show_reports_resolved_values_with_source(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``config show`` prints each resolved value alongside its winning source layer."""
    _write_config(
        tmp_path,
        "models:\n  - anthropic/claude-sonnet\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_MODEL", "openai/gpt-5.3-codex")

    result = runner.invoke(
        app,
        ["config", "show", "model"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert "openai/gpt-5.3-codex" in output
    assert "env" in output.lower() or "environment" in output.lower()


@_CC2_2_XFAIL
def test_config_explain_names_the_winning_layer(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``config explain`` names the winning precedence layer (CLI > env > YAML > default)."""
    _write_config(
        tmp_path,
        "tracing:\n  enabled: true\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_TRACING", "false")

    result = runner.invoke(
        app,
        ["config", "explain", "tracing.enabled"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert "env" in output.lower() or "environment" in output.lower()
    assert "yaml" in output.lower() or "config" in output.lower()


@_CC2_2_XFAIL
def test_config_validate_rejects_an_unknown_key(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``config validate`` rejects unknown keys (``extra='forbid'`` surface)."""
    _write_config(tmp_path, "unknown_future_key: true\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["config", "validate"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != 0, output
    assert "unknown" in output.lower() or "forbid" in output.lower()


@_CC2_2_XFAIL
def test_config_validate_runs_before_expensive_execution(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A review with invalid config fails fast without invoking the agent."""
    _write_config(tmp_path, "bogus_key: 1\n")
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    agent_called = {"value": False}

    async def _fake_run_offline_diff_review(**kwargs: object) -> object:
        agent_called["value"] = True
        from mergecraft.offline_review import OfflineReviewResult

        return OfflineReviewResult(success=False, output="", outcome=RunOutcome.failed)

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        _fake_run_offline_diff_review,
    )

    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path)],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != 0, output
    assert not agent_called["value"], "agent must not run when config validation fails"
