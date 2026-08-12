"""Plan W6.3 — ``extra="forbid"`` on optional-feature config models (D8, F5).

Contracts (D8, D9):

- Optional-feature config models reject unknown keys with a
  ``ValidationError`` — same fail-closed posture as security/runtime models
  (``D4``). The one-release warning shim has served its window and ends.
- Broken YAML still falls back to defaults (D9): only unknown keys within a
  parsed model fail closed. A syntactically unparseable
  ``.mergecraft/config.yaml`` keeps warn-and-default — defaults are the
  restrictive push/shell posture, so that path stays fail-safe.
- The error message names the offending key so a consumer can fix a typo
  without bisecting their config.
- The shipped ``examples/config.yaml`` and every valid optional block
  (``staticChecks``, ``ciEvidence``, ``modes``, ``tracing.sinks``) still
  loads.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import (
    RepoSettings,
    load_repo_settings,
)
from mergecraft.run_outcome import RunOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_with_unknown_static_check() -> dict[str, object]:
    """Return a top-level config carrying one valid + one unknown-key entry."""
    return {
        "staticChecks": [
            {"name": "lint", "command": "make lint"},
            {"name": "types", "command": "mypy {files}", "mysterySuffix": [".rs"]},
        ]
    }


def _settings_with_unknown_ci_evidence() -> dict[str, object]:
    """Unknown key inside ``ciEvidence`` block (D8)."""
    return {"ciEvidence": {"gates": {"lint": "Lint"}, "sirifs": ["some-artifact"]}}


def _settings_with_unknown_mode_def() -> dict[str, object]:
    """Unknown key inside a custom mode definition (D8)."""
    return {
        "modes": [
            {
                "id": "triage",
                "name": "Triage",
                "description": "Label issues",
                "promppt": "Label the issue",  # typo: `prompt` is the real field
            }
        ]
    }


def _settings_with_unknown_sink_entry() -> dict[str, object]:
    """Unknown key inside a tracing sink entry (D8)."""
    return {
        "tracing": {
            "sinks": [
                {"type": "jsonl_file", "path": ".mergecraft/traces/", "tier": "hot"},
            ]
        }
    }


# ---------------------------------------------------------------------------
# 1. Unknown keys raise ValidationError (one test per optional block)
# ---------------------------------------------------------------------------


def test_unknown_key_on_static_checks_raises() -> None:
    """D8 — ``staticChecks`` entries with unknown keys fail closed."""
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate(_settings_with_unknown_static_check())
    text = str(exc_info.value)
    assert "mysterySuffix" in text, f"error does not name the offending key: {text}"


def test_unknown_key_on_ci_evidence_raises() -> None:
    """D8 — ``ciEvidence`` blocks with unknown keys fail closed."""
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate(_settings_with_unknown_ci_evidence())
    text = str(exc_info.value)
    assert "sirifs" in text, f"error does not name the offending key: {text}"


def test_unknown_key_on_mode_def_raises() -> None:
    """D8 — a custom ``modes`` entry with an unknown key fails closed."""
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate(_settings_with_unknown_mode_def())
    text = str(exc_info.value)
    assert "promppt" in text, f"error does not name the offending key: {text}"


def test_unknown_key_on_sink_entry_raises() -> None:
    """D8 — a ``tracing.sinks`` entry with an unknown key fails closed."""
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate(_settings_with_unknown_sink_entry())
    text = str(exc_info.value)
    assert "tier" in text, f"error does not name the offending key: {text}"


# ---------------------------------------------------------------------------
# 2. The fail-closed posture matches the security/runtime convention
# ---------------------------------------------------------------------------


def test_unknown_optional_key_maps_to_configuration_error() -> None:
    """D8 — a ``ValidationError`` from optional-feature models maps to
    ``RunOutcome.configuration_error`` (same as security/runtime models).

    Pydantic ``ValidationError`` is reclassified by
    ``mergecraft.main._classify_error_outcome`` to the
    ``configuration_error`` bucket — verify the wiring exists rather than
    relying on the reclassifier to change.
    """
    from mergecraft.main import _classify_error_outcome

    try:
        RepoSettings.model_validate(_settings_with_unknown_static_check())
    except ValidationError as exc:
        outcome = _classify_error_outcome(exc)
    else:  # pragma: no cover — defensive
        pytest.fail("expected ValidationError")

    assert outcome is RunOutcome.configuration_error, (
        f"unknown optional key mapped to {outcome!r}, expected configuration_error"
    )


def test_error_message_names_the_offending_key() -> None:
    """D8 — the message is actionable: it names the offending key AND its block.

    Two unknowns at different depths in one payload make sure the path
    identifies the block, not just the leaf — a consumer with a typo in a
    nested block needs the block named in the error to find the typo
    without bisecting their config.
    """
    payload = {
        "ciEvidence": {"gates": {"lint": "Lint"}, "extra_unknown": 1},
        "modes": [
            {"id": "triage", "name": "Triage", "description": "x", "prompt": "x", "mystery": 1}
        ],
    }
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate(payload)
    text = str(exc_info.value)
    assert "extra_unknown" in text, f"ciEvidence-level key not named: {text}"
    assert "mystery" in text, f"mode-level key not named: {text}"


# ---------------------------------------------------------------------------
# 3. Regression pins — valid optional blocks still load
# ---------------------------------------------------------------------------


def test_valid_optional_config_still_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D8 — every optional block still validates after the flip.

    Regression pin: ``examples/config.yaml`` plus a representative valid
    ``ciEvidence``, ``modes``, and ``tracing.sinks`` block round-trip without
    error. If the flip ever leaks into one of these blocks, this test turns
    red before any consumer breaks.
    """
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        (
            "model: anthropic/claude-sonnet\n"
            "push: restricted\n"
            "shell: restricted\n"
            "signedCommits: false\n"
            "prApproveEnabled: false\n"
            "autoMergeEnabled: false\n"
            "modes:\n"
            "  - id: triage\n"
            "    name: Triage\n"
            "    description: Label issues\n"
            "    prompt: Label the issue\n"
            "staticChecks:\n"
            "  - name: lint\n"
            "    command: make lint\n"
            "    suffixes: ['.py']\n"
            "ciEvidence:\n"
            "  gates:\n"
            "    lint: Lint\n"
            "  sarifArtifacts:\n"
            "    - codeql-results\n"
            "tracing:\n"
            "  enabled: false\n"
            "  sinks:\n"
            "    - type: jsonl_file\n"
            "      path: .mergecraft/traces/\n"
        ),
        encoding="utf-8",
    )
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert settings.model == "anthropic/claude-sonnet"
    assert settings.push == "restricted"
    assert settings.shell == "restricted"
    assert len(settings.modes) == 1
    assert settings.modes[0].id == "triage"
    assert len(settings.static_checks) == 1
    assert settings.static_checks[0].name == "lint"
    assert settings.ci_evidence.gates == {"lint": "Lint"}
    assert settings.ci_evidence.sarif_artifacts == ["codeql-results"]
    assert settings.tracing.enabled is False
    assert len(settings.tracing.sinks) == 1
    assert settings.tracing.sinks[0].type == "jsonl_file"


# ---------------------------------------------------------------------------
# 4. D9 — broken YAML still falls back to defaults
# ---------------------------------------------------------------------------


def test_broken_yaml_still_falls_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D9 — a syntactically unparseable ``.mergecraft/config.yaml`` warns and
    falls back to ``default_settings()``.

    D8 flips *unknown keys within a parsed model*. An unparseable file is a
    different shape: the loader catches ``yaml.YAMLError`` at
    ``settings.py`` and warns, returning the restrictive defaults so the
    run can still proceed. This test pins that path so a future refactor
    cannot silently turn a syntax error into a hard failure.
    """
    from mergecraft.config.settings import default_settings

    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("push: [not, a, scalar\n", encoding="utf-8")

    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    defaults = default_settings()
    assert settings.push == defaults.push, "broken YAML must fall back to default push"
    assert settings.shell == defaults.shell, "broken YAML must fall back to default shell"
