"""J1.5 — predictions land through ``evidence/shadow.py`` (D6, D8)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.jev.support import PINNED_MODEL, import_jev, shadow_packet

if TYPE_CHECKING:
    from pathlib import Path


def _policy() -> Any:
    return import_jev("policy")


def test_jev_prediction_is_a_shadow_jsonl_row(tmp_path: Path) -> None:
    from mergecraft.evidence.shadow import load_shadow_records

    policy = _policy()
    types = import_jev("types")
    assessment = types.UnitAssessment(
        unit_id="unit-1",
        choice="defective",
        confidence=0.92,
        severity="Critical",
        severity_score=3.0,
        pack_id="unit/v1",
    )
    prediction = policy.predict_jev_action(assessment, trust_tier="untrusted")
    path = tmp_path / "shadow.jsonl"
    record = policy.record_jev_prediction(
        shadow_packet(),
        prediction,
        output_path=path,
        run_id="run-jev-1",
        change_id="acme/demo#724",
    )
    rows = load_shadow_records(path)
    assert len(rows) == 1
    assert rows[0].policy_id == "jev"
    assert rows[0].run_id == "run-jev-1"
    assert record.policy_id == "jev"
    assert rows[0].metadata["model"] == PINNED_MODEL
    assert rows[0].metadata["pack_id"] == "unit/v1"
    assert rows[0].metadata["raw_confidence"] == 0.92
    assert rows[0].metadata["unit_id"] == "unit-1"


def test_shadow_row_does_not_change_a_published_review(tmp_path: Path) -> None:
    policy = _policy()
    types = import_jev("types")
    assessment = types.UnitAssessment(
        unit_id="unit-1",
        choice="defective",
        confidence=0.92,
        severity="Critical",
        severity_score=3.0,
        pack_id="unit/v1",
    )
    prediction = policy.predict_jev_action(assessment, trust_tier="trusted")
    policy.record_jev_prediction(
        shadow_packet(),
        prediction,
        output_path=tmp_path / "shadow.jsonl",
        run_id="run-jev-1",
        change_id="acme/demo#724",
    )
    assert prediction.enforced is False
    assert prediction.skip_reviewer is False


def test_disagreement_report_groups_by_lane_and_rule(tmp_path: Path) -> None:
    from mergecraft.evidence.shadow import disagreement_report, load_shadow_records

    policy = _policy()
    types = import_jev("types")
    path = tmp_path / "shadow.jsonl"
    first = types.UnitAssessment(
        unit_id="a",
        choice="defective",
        confidence=0.92,
        severity="Critical",
        severity_score=3.0,
        pack_id="unit/v1",
        lane="high",
    )
    second = types.UnitAssessment(
        unit_id="b",
        choice="suspicious",
        confidence=0.70,
        severity="Minor",
        severity_score=1.0,
        pack_id="unit/v1",
        lane="low",
    )
    policy.record_jev_prediction(
        shadow_packet(change_id="acme/demo#1"),
        policy.predict_jev_action(first, trust_tier="trusted"),
        output_path=path,
        run_id="run-1",
        change_id="acme/demo#1",
    )
    policy.record_jev_prediction(
        shadow_packet(change_id="acme/demo#2"),
        policy.predict_jev_action(second, trust_tier="trusted"),
        output_path=path,
        run_id="run-2",
        change_id="acme/demo#2",
    )
    rows = load_shadow_records(path)
    report = disagreement_report(
        rows,
        outcomes={"acme/demo#1": "merged", "acme/demo#2": "merged"},
    )
    assert len(report) == 2
    lanes = {row["lane"] for row in report}
    rules = {row["rule_id"] for row in report}
    assert len(lanes) >= 1
    assert len(rules) >= 1
    assert all("disagreement" in row for row in report)
