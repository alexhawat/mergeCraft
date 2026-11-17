"""Feature-flag blast-radius rules (#1489)."""

from __future__ import annotations

from mergecraft.classify.blast_radius import classify_blast_radius


def test_flag_added_off_is_low() -> None:
    change = {
        "changed_paths": ["service/flags/new_experiment.yaml"],
        "diff_stats": {
            "diff_text": "+new_feature:\n+  default: false\n",
        },
    }
    result = classify_blast_radius(change)
    codes = [r.code for r in result.reasons]
    assert "flag.added_off" in codes
    assert "flag.added_off" in [r.code for r in result.reasons]


def test_flag_enabled_is_high() -> None:
    change = {
        "changed_paths": ["config/flags/experiment.yaml"],
        "diff_stats": {
            "diff_text": "+experiment:\n+  default: true\n",
        },
    }
    result = classify_blast_radius(change)
    codes = [r.code for r in result.reasons]
    assert "flag.enabled" in codes
    assert result.lane == "high"
