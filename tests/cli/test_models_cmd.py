"""RED tests for ``mergecraft models show`` (issue #14 / W18)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_ORDERED_MODELS = (
    "anthropic/claude-sonnet",
    "openai/gpt-5.3-codex",
    "google/gemini-3.1-pro-preview",
)


def _write_models_config(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
""",
        encoding="utf-8",
    )


def test_models_show_prints_config_order_with_env_override(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_models_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_MODEL", "openai/gpt-5.3-codex")

    result = runner.invoke(app, ["models", "show"])

    assert result.exit_code == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    for slug in _ORDERED_MODELS:
        assert slug in output
    assert "openai/gpt-5.3-codex" in output
    assert output.index("openai/gpt-5.3-codex") < output.index("google/gemini-3.1-pro-preview")
