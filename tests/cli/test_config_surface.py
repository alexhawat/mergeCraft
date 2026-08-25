"""CC2 — ``mergecraft config show|explain|validate`` (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC2.1** (RED). Implementation: **CC2.2**.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

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


def test_config_explain_model_reports_cli_over_env_and_yaml(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#468: ``model`` resolves CLI > env > YAML, and each layer is reported as itself."""
    from mergecraft.cli.config_precedence import ConfigLayer, explain_setting

    _write_config(tmp_path, "models:\n  - anthropic/claude-sonnet\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_MODEL", "openai/gpt-5.3-codex")

    explained = explain_setting("model", cwd=tmp_path, cli_model="nous/tencent/hy3")
    assert explained["winner"] == ConfigLayer.CLI.value
    assert explained["value"] == "nous/tencent/hy3"

    layers = explained["layers"]
    assert layers[ConfigLayer.CLI.value] == "nous/tencent/hy3"
    assert layers[ConfigLayer.ENV.value] == "openai/gpt-5.3-codex"
    # The YAML layer is the config file on its own — not the env value
    # promoted to the front of the effective list.
    assert layers[ConfigLayer.YAML.value] == "anthropic/claude-sonnet"

    without_cli = explain_setting("model", cwd=tmp_path)
    assert without_cli["winner"] == ConfigLayer.ENV.value
    assert without_cli["value"] == "openai/gpt-5.3-codex"

    monkeypatch.delenv("MERGECRAFT_MODEL")
    yaml_only = explain_setting("model", cwd=tmp_path)
    assert yaml_only["winner"] == ConfigLayer.YAML.value
    assert yaml_only["value"] == "anthropic/claude-sonnet"
