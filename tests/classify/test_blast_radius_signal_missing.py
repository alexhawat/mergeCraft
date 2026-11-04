"""#1056 part 1 — unknown is never green: missing inputs escalate the lane.

A blast-radius classification with no changed paths used to come out ``low`` /
``eligible``, an unrecognised risk band ranked as ``low``, and the gate's
``low_risk_passing`` row trusted ``lane == "low"`` without asking whether the
classification measured anything. Each missing signal may now only keep or
raise the lane, never lower it.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.agents.gates import _is_low_risk_passing, decide_action, select_rule_id
from mergecraft.classify.blast_radius import (
    SIGNAL_MISSING_CATEGORY,
    BlastRadiusClassification,
    ChangeSet,
    classify_blast_radius,
)
from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES, GateAction
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    Decision,
    MergeEvidencePacket,
)
from mergecraft.utils.risk_bands import risk_at_or_above

_SMALL_SOURCE_STATS: dict[str, object] = {"lines_added": 2, "lines_deleted": 1}

MISSING_SIGNAL_CASES: list[tuple[str, dict[str, Any], tuple[str, ...]]] = [
    ("empty-change", {}, ("changed_paths", "diff_stats")),
    ("empty-paths", {"changed_paths": [], "diff_stats": {}}, ("changed_paths",)),
    ("empty-paths-no-stats", {"changed_paths": []}, ("changed_paths", "diff_stats")),
    ("stats-only", {"diff_stats": _SMALL_SOURCE_STATS}, ("changed_paths",)),
    ("docs-without-stats", {"changed_paths": ["docs/guide.md"]}, ("diff_stats",)),
    ("tests-without-stats", {"changed_paths": ["tests/unit/test_x.py"]}, ("diff_stats",)),
    ("small-source-without-stats", {"changed_paths": ["src/pkg/time.py"]}, ("diff_stats",)),
    ("generated-without-stats", {"changed_paths": ["generated/client.py"]}, ("diff_stats",)),
    ("paths-not-a-list", {"changed_paths": "docs/guide.md", "diff_stats": {}}, ("changed_paths",)),
    ("stats-not-a-dict", {"changed_paths": ["docs/guide.md"], "diff_stats": []}, ("diff_stats",)),
]


@pytest.mark.parametrize(
    ("change", "missing"),
    [(change, missing) for _id, change, missing in MISSING_SIGNAL_CASES],
    ids=[case_id for case_id, _change, _missing in MISSING_SIGNAL_CASES],
)
def test_a_missing_signal_is_never_low_or_eligible(
    change: dict[str, Any], missing: tuple[str, ...]
) -> None:
    # Passes malformed ChangeSet shapes on purpose (non-list paths, non-dict stats).
    result = classify_blast_radius(change)  # type: ignore[arg-type]  # malformed ChangeSet on purpose

    assert result.lane == "medium"
    assert result.auto_merge_lane == "assisted"
    assert SIGNAL_MISSING_CATEGORY in result.categories
    for name in missing:
        assert name in result.reason


@pytest.mark.parametrize("change", [{}, {"changed_paths": []}])
def test_the_issue_acceptance_examples(change: ChangeSet) -> None:
    result = classify_blast_radius(change)

    assert result.lane != "low"
    assert result.auto_merge_lane != "eligible"


def test_a_higher_lane_from_another_category_still_wins() -> None:
    result = classify_blast_radius({"changed_paths": ["migrations/0001_init.sql"]})

    assert result.lane == "high"
    assert result.auto_merge_lane == "forbidden"
    assert SIGNAL_MISSING_CATEGORY in result.categories


def test_a_repository_override_cannot_lower_a_missing_signal() -> None:
    result = classify_blast_radius(
        {"changed_paths": ["generated/client.py"]},
        rule_set={"generated_files": {"lane": "low"}},
    )

    assert result.lane == "medium"


@pytest.mark.parametrize(
    "change",
    [
        {"changed_paths": ["docs/guide.md"], "diff_stats": {}},
        {"changed_paths": ["src/pkg/time.py"], "diff_stats": _SMALL_SOURCE_STATS},
    ],
    ids=["docs", "small-source"],
)
def test_a_complete_low_change_is_unchanged(change: ChangeSet) -> None:
    result = classify_blast_radius(change)

    assert result.lane == "low"
    assert result.auto_merge_lane == "eligible"
    assert SIGNAL_MISSING_CATEGORY not in result.categories


@pytest.mark.parametrize("threshold", ["low", "medium", "high", "critical"])
@pytest.mark.parametrize("band", ["bogus", "", "unknown", "HIGHEST"])
def test_an_unknown_risk_band_ranks_highest(band: str, threshold: str) -> None:
    assert risk_at_or_above(band, threshold) is True


def test_the_issue_risk_band_example() -> None:
    assert risk_at_or_above("bogus", "high") is True


def test_known_risk_bands_keep_their_order() -> None:
    assert risk_at_or_above("low", "high") is False
    assert risk_at_or_above("medium", "high") is False
    assert risk_at_or_above("high", "high") is True
    assert risk_at_or_above("Critical", "high") is True


def _decided_packet(
    blast_radius: BlastRadiusClassification, *, files_changed: list[str]
) -> MergeEvidencePacket:
    """A blocker-free packet carrying the trusted ``success`` decision row."""
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY

    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="acme/demo#42",
        agent=AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        files_changed=files_changed,
        findings=[],
        deterministic_checks=[],
        blast_radius=blast_radius,
        decision=Decision(verdict="success", reason="clean", decided_by=TRUSTED_PACKET_DECIDED_BY),
    )


def _forged_low(categories: list[str]) -> BlastRadiusClassification:
    return BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="low",
        next_action="eligible",
        categories=categories,
    )


@pytest.mark.parametrize(
    ("blast_radius", "files_changed"),
    [
        (classify_blast_radius({}), []),
        (classify_blast_radius({"changed_paths": []}), []),
        (classify_blast_radius({"changed_paths": ["docs/guide.md"]}), ["docs/guide.md"]),
        (_forged_low([]), []),
        (_forged_low([SIGNAL_MISSING_CATEGORY]), ["docs/guide.md"]),
    ],
    ids=[
        "classified-empty-change",
        "classified-empty-paths",
        "classified-missing-stats",
        "low-lane-no-files",
        "low-lane-signal-missing",
    ],
)
def test_a_blast_radius_without_inputs_never_selects_low_risk_auto_merge(
    blast_radius: BlastRadiusClassification, files_changed: list[str]
) -> None:
    packet = _decided_packet(blast_radius, files_changed=files_changed)

    assert _is_low_risk_passing(packet) is False
    assert select_rule_id(packet) != "low_risk_passing"
    assert decide_action(packet, policy=DEFAULT_GATE_POLICIES) is not GateAction.AUTO_MERGE


def test_a_measured_low_change_still_selects_low_risk_passing() -> None:
    """Control: the gate row is reachable when the classification had inputs."""
    change: ChangeSet = {"changed_paths": ["docs/guide.md"], "diff_stats": {"lines_added": 3}}
    packet = _decided_packet(classify_blast_radius(change), files_changed=["docs/guide.md"])

    assert _is_low_risk_passing(packet) is True
    assert select_rule_id(packet) == "low_risk_passing"
