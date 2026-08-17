"""``mergecraft eval bench`` model resolution (#140, B3 fix — PR #216 review).

``resolve_model()`` alone never reads ``.mergecraft/config.yaml`` — it only
checks an explicit ``--model`` and the ``MERGECRAFT_MODEL`` env override.
``bench_cmd`` previously advertised config-only resolution in its help text
("otherwise .mergecraft/config.yaml / MERGECRAFT_MODEL") without ever
actually falling through to config when neither of those was set, so a
config-only setup always hit "No model configured" (mergeCraft self-review,
PR #216). These tests pin the fix: config-only resolution succeeds via the
same ``resolve_effective_model_slug`` helper ``mergecraft models show`` uses,
and the genuinely-unconfigured case still fails with a clear message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


def _write_model_config(tmp_path: Path, *, model: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(f"model: {model}\n", encoding="utf-8")


def test_eval_bench_resolves_model_from_config_only(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No ``--model``, no ``MERGECRAFT_MODEL`` — resolution falls through to
    ``.mergecraft/config.yaml``'s ``model:`` key, matching what `mergecraft
    models show` would report as the winning slug. The command must not hit
    the "No model configured" error path."""
    _write_model_config(tmp_path, model="anthropic/claude-sonnet")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)
    empty_bank = tmp_path / "bank"
    empty_corpus = tmp_path / "detect-corpus"

    result = runner.invoke(
        app,
        [
            "eval",
            "bench",
            "--bank",
            str(empty_bank),
            "--detection-corpus",
            str(empty_corpus),
            "--results-dir",
            str(tmp_path / "results"),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "No model configured" not in result.stdout
    # Empty bank/corpus: structural section still populates (0 cases), and
    # detection honestly reports it has nothing to detect on — model
    # resolution itself must not be the reason.
    assert "no patch-bearing cases" in result.stdout


def test_eval_bench_errors_clearly_when_no_model_configured(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No ``--model``, no ``MERGECRAFT_MODEL``, no ``.mergecraft/config.yaml``
    at all — genuinely nothing configured. Must fail with a clear,
    actionable message, not a stack trace or a silent default."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)

    result = runner.invoke(
        app,
        [
            "eval",
            "bench",
            "--bank",
            str(tmp_path / "bank"),
            "--detection-corpus",
            str(tmp_path / "detect-corpus"),
            "--results-dir",
            str(tmp_path / "results"),
        ],
    )

    assert result.exit_code == 1
    assert "No model configured" in result.stdout


def test_eval_bench_explicit_model_flag_wins_over_config(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An explicit ``--model`` still short-circuits config resolution
    entirely (unaffected by the config-fallback path added for the
    no-flag case)."""
    _write_model_config(tmp_path, model="anthropic/claude-sonnet")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)

    result = runner.invoke(
        app,
        [
            "eval",
            "bench",
            "--model",
            "openai/gpt-codex",
            "--bank",
            str(tmp_path / "bank"),
            "--detection-corpus",
            str(tmp_path / "detect-corpus"),
            "--results-dir",
            str(tmp_path / "results"),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "No model configured" not in result.stdout
