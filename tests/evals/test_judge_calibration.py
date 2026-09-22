"""Saved-verdict judge calibration is strict, offline, and fail closed."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.agents.verifier import VerdictOutcome
from mergecraft.cli.app import app
from mergecraft.evals.judge_calibration import (
    HumanJudgeReference,
    JudgeCalibrationCase,
    JudgeCalibrationProtocol,
    JudgeCandidateSeal,
    calibration_report_sha256,
    case_sha256,
    compute_calibration_metrics,
    evaluate_judge_calibration,
    protocol_sha256,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _case(
    case_id: str,
    *,
    human: str = "confirm",
    judge: str = "confirm",
    lane: str = "normal",
    evidence: str | None = None,
) -> JudgeCalibrationCase:
    fingerprint = f"fingerprint-{case_id}"
    human_severity = "Minor" if human == "downgrade" else None
    judge_severity = "Minor" if judge == "downgrade" else None
    outcome = None
    if lane == "high" and judge == "drop":
        outcome = VerdictOutcome(
            fingerprint=fingerprint,
            verdict="drop",
            recorded_withdrawn=False,
            publishable=True,
            escalated_to_human=True,
            reason="saved policy result",
        )
    return JudgeCalibrationCase.model_validate(
        {
            "case_id": case_id,
            "finding": {
                "path": "src/a.py",
                "line": 3,
                "body": f"finding {case_id}",
                "severity": "Major",
                "fingerprint": fingerprint,
            },
            "deterministic_checks": [{"name": "ruff", "status": "passed", "command": "ruff check"}],
            "lane": lane,
            "evidence_sha256": evidence or (case_id.encode().hex() + "0" * 64)[:64],
            "human_reference": {"verdict": human, "new_severity": human_severity},
            "human_adjudicator_login": "reviewer",
            "human_adjudicated_at": NOW.isoformat(),
            "saved_judge_verdict": {
                "fingerprint": fingerprint,
                "verdict": judge,
                "reason": "saved judge result",
                "pin": {
                    "provider": "openai",
                    "model": "judge-v1",
                    "model_pinned": True,
                    "judge_version": "1",
                    "rubric_version": "1",
                },
                "deterministic_checks": ["ruff"],
                "new_severity": judge_severity,
                "lane": lane,
            },
            "prompt_sha256": "9" * 64,
            "policy_id": "verifier-policy-v1",
            "policy_parameters": {"high_stakes_drop": "human-escalation"},
            "provenance": "human",
            "adjudication": {
                "adjudicated_by": "human",
                "independence": "independent",
                "at": NOW.isoformat(),
            },
            "saved_policy_outcome": (
                outcome.model_dump(mode="json") if outcome is not None else None
            ),
        }
    )


def _paired_cases() -> list[JudgeCalibrationCase]:
    cases: list[JudgeCalibrationCase] = []
    for split in ("cal", "hold"):
        cases.extend(
            [
                _case(f"{split}-confirm"),
                _case(f"{split}-downgrade", human="downgrade", judge="downgrade"),
                _case(f"{split}-drop", human="drop", judge="drop", lane="high"),
            ]
        )
    return cases


def _protocol(cases: list[JudgeCalibrationCase]) -> JudgeCalibrationProtocol:
    return JudgeCalibrationProtocol(
        schema_version="1.0.0",
        calibration_case_ids=[case.case_id for case in cases if case.case_id.startswith("cal-")],
        held_out_case_ids=[case.case_id for case in cases if case.case_id.startswith("hold-")],
        case_hashes={case.case_id: case_sha256(case) for case in cases},
        minimum_per_class=1,
        minimum_macro_f1=0.9,
        minimum_drop_precision=0.9,
        minimum_confirm_recall=0.9,
        minimum_kappa=0.8,
        maximum_disagreement_rate=0.1,
        required_high_stakes_escalation_recall=1.0,
    )


def _seal(
    protocol: JudgeCalibrationProtocol,
    cases: list[JudgeCalibrationCase],
) -> JudgeCandidateSeal:
    provisional = evaluate_judge_calibration(protocol, cases)
    assert provisional.state == "provisional"
    return JudgeCandidateSeal(
        schema_version="1.0.0",
        candidate_id=provisional.candidate_id,
        prompt_sha256=provisional.prompt_sha256,
        policy_id=provisional.policy_id,
        protocol_sha256=protocol_sha256(protocol),
        case_hashes=protocol.case_hashes,
        calibration_report_sha256=calibration_report_sha256(provisional.calibration),
        policy_parameters=provisional.policy_parameters,
        sealed_by="release-operator",
        sealed_at=NOW,
    )


def test_human_reference_requires_downgrade_severity() -> None:
    with pytest.raises(ValidationError, match="new_severity"):
        HumanJudgeReference(verdict="downgrade")


def test_case_rejects_missing_deterministic_checks() -> None:
    payload = _case("missing-checks").model_dump(mode="python")
    payload["deterministic_checks"] = []
    with pytest.raises(ValidationError, match="deterministic checks"):
        JudgeCalibrationCase.model_validate(payload)


def test_case_rejects_unpinned_or_agent_seeded_truth() -> None:
    payload = _case("bad-pin").model_dump(mode="python")
    payload["saved_judge_verdict"]["pin"]["model_pinned"] = False
    with pytest.raises(ValidationError, match="pinned"):
        JudgeCalibrationCase.model_validate(payload)

    payload = _case("seeded").model_dump(mode="python")
    payload["provenance"] = "agent-seeded"
    with pytest.raises(ValidationError, match="ineligible"):
        JudgeCalibrationCase.model_validate(payload)


def test_protocol_rejects_overlap_and_missing_explicit_thresholds() -> None:
    case = _case("same")
    with pytest.raises(ValidationError, match="overlap"):
        JudgeCalibrationProtocol(
            schema_version="1.0.0",
            calibration_case_ids=["same"],
            held_out_case_ids=["same"],
            case_hashes={"same": case_sha256(case)},
            minimum_per_class=1,
            minimum_macro_f1=0.5,
            minimum_drop_precision=0.5,
            minimum_confirm_recall=0.5,
            minimum_kappa=0.0,
            maximum_disagreement_rate=0.5,
            required_high_stakes_escalation_recall=1.0,
        )
    with pytest.raises(ValidationError):
        JudgeCalibrationProtocol.model_validate(
            {
                "schema_version": "1.0.0",
                "calibration_case_ids": ["a"],
                "held_out_case_ids": ["b"],
                "case_hashes": {"a": "0" * 64, "b": "1" * 64},
            }
        )


def test_metrics_handle_missed_class_and_kappa_edges() -> None:
    missed = compute_calibration_metrics([_case("missed", human="confirm", judge="drop")])
    assert missed.per_class["confirm"].precision is None
    assert missed.per_class["confirm"].recall == 0
    assert missed.per_class["confirm"].f1 == 0

    varying = compute_calibration_metrics(
        [_case("one"), _case("two", human="confirm", judge="drop")]
    )
    assert varying.cohen_kappa == pytest.approx(0.0)
    identical = compute_calibration_metrics([_case("only")])
    assert identical.cohen_kappa is None


def test_cross_split_evidence_reuse_is_rejected() -> None:
    cases = _paired_cases()
    repeated = "a" * 64
    cases[0] = _case(cases[0].case_id, evidence=repeated)
    cases[3] = _case(cases[3].case_id, evidence=repeated)
    with pytest.raises(ValueError, match="reuse frozen evidence"):
        evaluate_judge_calibration(_protocol(cases), cases)


def test_hash_drift_is_rejected() -> None:
    cases = _paired_cases()
    protocol = _protocol(cases)
    protocol.case_hashes[cases[0].case_id] = "f" * 64
    with pytest.raises(ValueError, match="hash drift"):
        evaluate_judge_calibration(protocol, cases)


def test_candidate_contract_must_match_across_both_splits() -> None:
    cases = _paired_cases()
    changed = cases[-1].model_dump(mode="python")
    changed["prompt_sha256"] = "8" * 64
    cases[-1] = JudgeCalibrationCase.model_validate(changed)
    with pytest.raises(ValueError, match="one prompt and policy contract"):
        evaluate_judge_calibration(_protocol(cases), cases)


def test_no_seal_is_provisional_and_does_not_report_heldout() -> None:
    cases = _paired_cases()
    report = evaluate_judge_calibration(_protocol(cases), cases)
    assert report.state == "provisional"
    assert report.held_out is None


def test_valid_precommitted_seal_allows_one_heldout_report() -> None:
    cases = _paired_cases()
    protocol = _protocol(cases)
    report = evaluate_judge_calibration(protocol, cases, seal=_seal(protocol, cases))
    assert report.state == "validated"
    assert report.held_out is not None
    assert report.held_out.metrics.confusion_matrix["drop"]["drop"] == 1
    assert report.held_out.metrics.cohen_kappa == pytest.approx(1.0)
    assert report.held_out.metrics.high_stakes_escalation_recall == 1.0
    assert "human-human reliability" in report.limitations[0]
    assert report.seal_sha256 is not None
    assert report.sealed_by == "release-operator"
    assert report.sealed_at == NOW


def test_failing_heldout_is_rejected_with_hand_computed_metrics(tmp_path: Path) -> None:
    cases = _paired_cases()
    cases[3] = _case("hold-confirm", human="confirm", judge="drop")
    protocol = _protocol(cases)
    seal = _seal(protocol, cases)
    report = evaluate_judge_calibration(protocol, cases, seal=seal)
    assert report.state == "rejected"
    assert report.held_out is not None
    assert report.held_out.metrics.confusion_matrix["confirm"]["drop"] == 1
    assert report.held_out.metrics.macro_f1 == pytest.approx(5 / 9)
    assert report.held_out.metrics.cohen_kappa == pytest.approx(0.5)
    assert report.held_out.threshold_results["minimum_confirm_recall"] is False

    cases_path = tmp_path / "cases.json"
    protocol_path = tmp_path / "protocol.json"
    seal_path = tmp_path / "seal.json"
    cases_path.write_text(
        json.dumps([case.model_dump(mode="json") for case in cases]), encoding="utf-8"
    )
    protocol_path.write_text(protocol.model_dump_json(), encoding="utf-8")
    seal_path.write_text(seal.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "judge-calibration",
            "--protocol",
            str(protocol_path),
            "--cases",
            str(cases_path),
            "--seal",
            str(seal_path),
            "--json",
        ],
    )
    assert result.exit_code != 0
    assert json.loads(result.output)["state"] == "rejected"


def test_undefined_required_escalation_metric_fails_closed() -> None:
    cases = _paired_cases()
    cases[2] = _case("cal-drop", human="drop", judge="drop", lane="normal")
    protocol = _protocol(cases)
    report = evaluate_judge_calibration(protocol, cases)
    assert report.state == "rejected"
    assert report.calibration.metrics.high_stakes_escalation_recall is None
    assert report.calibration.threshold_results["required_high_stakes_escalation_recall"] is False


def test_seal_mismatch_is_rejected_before_heldout_scoring() -> None:
    cases = _paired_cases()
    protocol = _protocol(cases)
    seal = _seal(protocol, cases).model_copy(update={"protocol_sha256": "0" * 64})
    with pytest.raises(ValueError, match="protocol hash mismatch"):
        evaluate_judge_calibration(protocol, cases, seal=seal)


def test_seal_policy_mismatch_is_rejected_before_heldout_scoring() -> None:
    cases = _paired_cases()
    protocol = _protocol(cases)
    seal = _seal(protocol, cases).model_copy(update={"policy_parameters": {"changed": True}})
    with pytest.raises(ValueError, match="policy contract mismatch"):
        evaluate_judge_calibration(protocol, cases, seal=seal)


def test_cli_reads_saved_verdicts_without_provider_credentials(tmp_path: Path) -> None:
    cases = _paired_cases()
    protocol = _protocol(cases)
    seal = _seal(protocol, cases)
    cases_path = tmp_path / "cases.json"
    protocol_path = tmp_path / "protocol.json"
    seal_path = tmp_path / "seal.json"
    cases_path.write_text(
        json.dumps([case.model_dump(mode="json") for case in cases]), encoding="utf-8"
    )
    protocol_path.write_text(protocol.model_dump_json(), encoding="utf-8")
    seal_path.write_text(seal.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "judge-calibration",
            "--protocol",
            str(protocol_path),
            "--cases",
            str(cases_path),
            "--seal",
            str(seal_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "validated"


def test_cli_fails_closed_without_a_seal_but_emits_provisional_json(tmp_path: Path) -> None:
    cases = _paired_cases()
    protocol = _protocol(cases)
    cases_path = tmp_path / "cases.json"
    protocol_path = tmp_path / "protocol.json"
    cases_path.write_text(
        json.dumps([case.model_dump(mode="json") for case in cases]), encoding="utf-8"
    )
    protocol_path.write_text(protocol.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "judge-calibration",
            "--protocol",
            str(protocol_path),
            "--cases",
            str(cases_path),
            "--json",
        ],
    )
    assert result.exit_code != 0
    assert json.loads(result.output)["state"] == "provisional"
