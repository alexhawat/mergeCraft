"""Feature-flag blast-radius rules (#1489)."""

from __future__ import annotations

import pytest

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
    assert result.lane == "low"


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


def test_flag_default_is_read_only_from_its_file_hunks() -> None:
    """A document and an unrelated setting cannot turn an off flag on."""
    result = classify_blast_radius(
        {
            "changed_paths": ["service/flags/experiment.yaml", "service/settings.yaml"],
            "diff_stats": {
                "diff": (
                    "diff --git a/service/settings.yaml b/service/settings.yaml\n"
                    "@@ -1 +1 @@\n-enabled: false\n+enabled: true\n"
                    "diff --git a/service/flags/experiment.yaml b/service/flags/experiment.yaml\n"
                    "@@ -1 +1,3 @@\n enabled: true\n+experiment:\n+  default: false\n"
                )
            },
        }
    )
    assert result.lane == "low"
    assert [reason.code for reason in result.reasons] == ["flag.added_off"]


@pytest.mark.parametrize(
    "content", ["rollout: 100%", '{"enabled": true}'], ids=("full-rollout", "json-boolean")
)
def test_flag_on_values(content: str) -> None:
    """Full rollout and JSON booleans both enable a matched flag."""
    result = classify_blast_radius(
        {
            "changed_paths": ["feature_flags.json"],
            "diff_stats": {"diff": f"+{content}\n"},
        }
    )
    assert result.lane == "high"
    assert "flag.enabled" in [reason.code for reason in result.reasons]
