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


# ── #1056 part 2 — the checklist marks what was never measured ───────────────
#
# ``None`` means "not measured". With ``changed_paths`` missing every path gate is
# unknown. With ``diff_stats`` missing but paths present, the gates that read
# only paths are still measured; a gate that already failed from paths stays
# ``False``; ``migrations``, ``secrets_config_deployment``, ``irreversible_infra``
# and ``tests`` (which also read diff text or line counts) are otherwise ``None``.
# ``inputs`` is ``False`` whenever either input is missing.

_NO_PATHS: dict[str, bool | None] = {
    "inputs": False,
    "migrations": None,
    "auth_security_payment": None,
    "secrets_config_deployment": None,
    "irreversible_infra": None,
    "public_api": None,
    "dependencies": None,
    "tests": None,
    "review_config": None,
    "source": None,
}
_PATHS_WITHOUT_STATS: dict[str, bool | None] = {
    "inputs": False,
    "migrations": None,
    "auth_security_payment": True,
    "secrets_config_deployment": None,
    "irreversible_infra": None,
    "public_api": True,
    "dependencies": True,
    "tests": None,
    "review_config": True,
    "source": None,
}

MISSING_SIGNAL_CHECKLIST: dict[str, dict[str, bool | None]] = {
    "empty-change": _NO_PATHS,
    "empty-paths": _NO_PATHS,
    "empty-paths-no-stats": _NO_PATHS,
    "stats-only": _NO_PATHS,
    "paths-not-a-list": _NO_PATHS,
    "docs-without-stats": _PATHS_WITHOUT_STATS,
    "tests-without-stats": _PATHS_WITHOUT_STATS,
    "generated-without-stats": _PATHS_WITHOUT_STATS,
    "stats-not-a-dict": _PATHS_WITHOUT_STATS,
    # Source without tests already fails from paths alone: ``tests`` stays ``False``.
    # The source change is seen, but the carve-out needs line counts, so ``source``
    # fails too.
    "small-source-without-stats": {**_PATHS_WITHOUT_STATS, "tests": False, "source": False},
}
_MISSING_CODE: dict[str, str] = {
    "changed_paths": "signal.missing.paths",
    "diff_stats": "signal.missing.diff",
}
_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def _classify_any(change: Any, rule_set: Any = None) -> Any:
    """Classify a possibly malformed table row (non-list paths, non-dict stats)."""
    return classify_blast_radius(change, rule_set=rule_set)


def _checklist(result: Any) -> dict[str, bool | None]:
    return {gate.gate: gate.passed for gate in result.checklist}


@pytest.mark.parametrize(
    ("case_id", "change"),
    [(case_id, change) for case_id, change, _missing in MISSING_SIGNAL_CASES],
    ids=[case_id for case_id, _change, _missing in MISSING_SIGNAL_CASES],
)
def test_a_missing_signal_marks_its_unmeasured_gates_unknown(
    case_id: str, change: dict[str, Any]
) -> None:
    expected = MISSING_SIGNAL_CHECKLIST[case_id]
    checklist = _checklist(_classify_any(change))

    # Later gates (appended after these) are not this table's concern.
    assert {gate: checklist.get(gate, "absent") for gate in expected} == expected


def test_gate_order_starts_with_the_missing_signal_table_gates() -> None:
    from mergecraft.classify.blast_radius import GATE_ORDER

    assert tuple(GATE_ORDER[: len(_NO_PATHS)]) == tuple(_NO_PATHS)
    assert [gate.gate for gate in classify_blast_radius({}).checklist] == list(GATE_ORDER)


@pytest.mark.parametrize(
    ("change", "missing"),
    [(change, missing) for _id, change, missing in MISSING_SIGNAL_CASES],
    ids=[case_id for case_id, _change, _missing in MISSING_SIGNAL_CASES],
)
def test_a_missing_signal_emits_its_coded_reason(
    change: dict[str, Any], missing: tuple[str, ...]
) -> None:
    result = _classify_any(change)
    reasons = {reason.code: reason for reason in result.reasons}

    for name in missing:
        assert reasons[_MISSING_CODE[name]].lane == "medium"
    for name in set(_MISSING_CODE) - set(missing):
        assert _MISSING_CODE[name] not in reasons
    assert set(reasons) & set(_MISSING_CODE.values())


@pytest.mark.parametrize(
    "change",
    [change for _id, change, _missing in MISSING_SIGNAL_CASES],
    ids=[case_id for case_id, _change, _missing in MISSING_SIGNAL_CASES],
)
def test_a_missing_signal_holds_the_lane_and_eligibility_invariants(
    change: dict[str, Any],
) -> None:
    result = _classify_any(change)
    passed = [gate.passed for gate in result.checklist]

    assert result.lane == max((r.lane for r in result.reasons), key=_RANK.__getitem__)
    assert any(value is not True for value in passed)
    assert result.auto_merge_lane != "eligible"
    assert _checklist(result)["inputs"] is False


def test_a_gate_failed_from_paths_stays_false_without_diff_stats() -> None:
    result = classify_blast_radius({"changed_paths": ["migrations/0001_init.sql"]})
    gates = _checklist(result)

    assert gates["migrations"] is False
    assert gates["secrets_config_deployment"] is None
    assert gates["inputs"] is False
    assert result.lane == "high"


def test_a_path_only_gate_is_measured_without_diff_stats() -> None:
    result = classify_blast_radius({"changed_paths": ["ruff.toml"]})
    gates = _checklist(result)

    assert gates["review_config"] is False
    assert gates["dependencies"] is True
    assert gates["tests"] is None


def test_a_complete_low_change_passes_every_gate() -> None:
    change: ChangeSet = {"changed_paths": ["docs/guide.md"], "diff_stats": {"lines_added": 3}}
    result = classify_blast_radius(change)

    assert result.auto_merge_lane == "eligible"
    assert all(value is True for value in _checklist(result).values())


# ── the gate reads the checklist's ``inputs`` row when the packet carries one ─

_LOCKED_GATES = list(_NO_PATHS)


def _classification_with_checklist(
    *, lane: str, auto_merge_lane: str, inputs: bool | None, categories: list[str]
) -> BlastRadiusClassification:
    """A classification whose categories look measured but whose checklist says otherwise."""
    return BlastRadiusClassification.model_validate(
        {
            "lane": lane,
            "auto_merge_lane": auto_merge_lane,
            "reason": "forged",
            "next_action": "forged",
            "categories": categories,
            "reasons": [{"code": "baseline.clean", "lane": lane, "message": "forged"}],
            "checklist": [
                {"gate": gate, "passed": inputs if gate == "inputs" else True}
                for gate in _LOCKED_GATES
            ],
        }
    )


@pytest.mark.parametrize("inputs", [False, None], ids=["inputs-false", "inputs-unknown"])
def test_low_risk_passing_refuses_a_checklist_without_measured_inputs(
    inputs: bool | None,
) -> None:
    from mergecraft.agents.gates import _is_clean_pass

    blast_radius = _classification_with_checklist(
        lane="low", auto_merge_lane="eligible", inputs=inputs, categories=[]
    )
    packet = _decided_packet(blast_radius, files_changed=["docs/guide.md"])

    assert _is_low_risk_passing(packet) is False
    assert _is_clean_pass(packet) is False
    assert select_rule_id(packet) not in {"low_risk_passing", "clean_pass"}
    assert decide_action(packet, policy=DEFAULT_GATE_POLICIES) is not GateAction.AUTO_MERGE


@pytest.mark.parametrize("inputs", [False, None], ids=["inputs-false", "inputs-unknown"])
def test_clean_pass_refuses_a_medium_checklist_without_measured_inputs(
    inputs: bool | None,
) -> None:
    from mergecraft.agents.gates import _is_clean_pass

    blast_radius = _classification_with_checklist(
        lane="medium",
        auto_merge_lane="assisted",
        inputs=inputs,
        categories=["dependency_changes"],
    )
    packet = _decided_packet(blast_radius, files_changed=["uv.lock"])

    assert _is_clean_pass(packet) is False
    assert select_rule_id(packet) != "clean_pass"
    assert decide_action(packet, policy=DEFAULT_GATE_POLICIES) is not GateAction.AUTO_MERGE


def test_a_checklist_with_measured_inputs_still_reaches_low_risk_passing() -> None:
    """Control: the checklist check is not a blanket refusal."""
    blast_radius = _classification_with_checklist(
        lane="low", auto_merge_lane="eligible", inputs=True, categories=[]
    )
    packet = _decided_packet(blast_radius, files_changed=["docs/guide.md"])

    assert _is_low_risk_passing(packet) is True
    assert select_rule_id(packet) == "low_risk_passing"


def test_a_checklist_with_measured_inputs_still_reaches_clean_pass() -> None:
    """Control: a measured medium lane keeps its merge-shaped route."""
    blast_radius = _classification_with_checklist(
        lane="medium",
        auto_merge_lane="assisted",
        inputs=True,
        categories=["dependency_changes"],
    )
    packet = _decided_packet(blast_radius, files_changed=["uv.lock"])

    assert select_rule_id(packet) == "clean_pass"


def _pre_checklist_packet(blast_radius: dict[str, Any], files_changed: list[str]) -> Any:
    """A packet as written before ``reasons``/``checklist`` existed (schema 1.17.0)."""
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY

    return MergeEvidencePacket.model_validate(
        {
            "schema_version": "1.17.0",
            "change_id": "acme/demo#42",
            "agent": {"id": "claude", "version": "0.0.0", "model": "claude-sonnet-4-5"},
            "files_changed": files_changed,
            "findings": [],
            "deterministic_checks": [],
            "blast_radius": blast_radius,
            "decision": {
                "verdict": "success",
                "reason": "clean",
                "decided_by": TRUSTED_PACKET_DECIDED_BY,
            },
        }
    )


@pytest.mark.parametrize(
    ("blast_radius", "files_changed", "rule_id"),
    [
        (
            {
                "lane": "low",
                "auto_merge_lane": "eligible",
                "reason": "No elevated blast-radius category was detected.",
                "next_action": "Eligible for automatic merge after required checks pass.",
                "categories": [],
            },
            ["docs/guide.md"],
            "low_risk_passing",
        ),
        (
            {
                "lane": "medium",
                "auto_merge_lane": "assisted",
                "reason": "Detected blast-radius categories: dependency_changes.",
                "next_action": "Use assisted review and verify the affected behavior.",
                "categories": ["dependency_changes"],
            },
            ["uv.lock"],
            "clean_pass",
        ),
        (
            {
                "lane": "medium",
                "auto_merge_lane": "assisted",
                "reason": "Missing classifier input: diff_stats.",
                "next_action": "Use assisted review and verify the affected behavior.",
                "categories": [SIGNAL_MISSING_CATEGORY],
            },
            ["docs/guide.md"],
            "needs_human_review",
        ),
    ],
    ids=["low", "medium", "signal-missing"],
)
def test_a_packet_written_before_the_checklist_decides_as_before(
    blast_radius: dict[str, Any], files_changed: list[str], rule_id: str
) -> None:
    packet = _pre_checklist_packet(blast_radius, files_changed)

    assert packet.blast_radius is not None
    assert select_rule_id(packet) == rule_id
