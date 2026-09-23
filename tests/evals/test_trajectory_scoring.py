"""Deterministic scoring for the eight trajectory-auditor checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.analyzers.finding import make_finding
from mergecraft.cli.app import app
from mergecraft.evals.adjudication import AdjudicationRecord
from mergecraft.evals.trajectory_scoring import (
    TRAJECTORY_LABEL_SCHEMA_VERSION,
    TrajectoryCheckLabel,
    TrajectoryLabelCase,
    TrajectoryLabelProvenance,
    TrajectoryLabelSet,
    TrajectorySplit,
    TrajectoryTruth,
    canonical_trajectory_sha256,
    load_trajectory_label_sets,
    score_trajectory_labels,
    validate_label_sets,
)
from mergecraft.evidence.trajectory import ToolCallRecord, TrajectoryRecord
from mergecraft.evidence.trajectory_audit import (
    TRAJECTORY_AUDITOR_VERSION,
    TRAJECTORY_CHECKS,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
RULE_IDS = tuple(check.rule_id for check in TRAJECTORY_CHECKS)


def _labels(
    overrides: dict[str, tuple[TrajectoryTruth, list[str]]] | None = None,
) -> list[TrajectoryCheckLabel]:
    overrides = overrides or {}
    return [
        TrajectoryCheckLabel(
            rule_id=rule_id,
            truth=overrides.get(rule_id, ("negative", []))[0],
            expected_paths=overrides.get(rule_id, ("negative", []))[1],
        )
        for rule_id in RULE_IDS
    ]


def _case(
    case_id: str,
    trajectory: TrajectoryRecord,
    *,
    labels: list[TrajectoryCheckLabel] | None = None,
    provenance: TrajectoryLabelProvenance = "agent-seeded",
    labelled_at: datetime | None = None,
    adjudication: AdjudicationRecord | None = None,
) -> TrajectoryLabelCase:
    return TrajectoryLabelCase(
        case_id=case_id,
        trajectory=trajectory,
        trajectory_sha256=canonical_trajectory_sha256(trajectory),
        labelled_at=labelled_at,
        provenance=provenance,
        adjudication=adjudication,
        labels=labels or _labels(),
    )


def _label_set(
    *cases: TrajectoryLabelCase,
    split: TrajectorySplit = "development",
    adjudicator_login: str | None = None,
) -> TrajectoryLabelSet:
    return TrajectoryLabelSet(
        schema_version=TRAJECTORY_LABEL_SCHEMA_VERSION,
        auditor_version=TRAJECTORY_AUDITOR_VERSION,
        split=split,
        source_commit="a" * 40,
        adjudicator_login=adjudicator_login,
        cases=list(cases),
    )


def test_contract_requires_exactly_one_label_for_every_runtime_check() -> None:
    trajectory = TrajectoryRecord()
    with pytest.raises(ValidationError, match="exactly once"):
        _case("missing", trajectory, labels=_labels()[:-1])

    duplicate = _labels()
    duplicate[-1] = duplicate[0]
    with pytest.raises(ValidationError, match="exactly once"):
        _case("duplicate", trajectory, labels=duplicate)

    payload = _labels()[0].model_dump()
    payload["rule_id"] = "invented-check"
    with pytest.raises(ValidationError, match="unknown trajectory check"):
        TrajectoryCheckLabel.model_validate(payload)


@pytest.mark.parametrize(
    ("truth", "paths"),
    [("positive", []), ("negative", [""]), ("unknown", ["src/a.py"])],
)
def test_label_truth_controls_expected_path_shape(truth: str, paths: list[str]) -> None:
    with pytest.raises(ValidationError, match="expected_paths"):
        TrajectoryCheckLabel.model_validate(
            {
                "rule_id": RULE_IDS[0],
                "truth": truth,
                "expected_paths": paths,
            }
        )


def test_contract_rejects_hash_drift_duplicates_and_missing_evidence_reference() -> None:
    trajectory = TrajectoryRecord()
    case = _case("one", trajectory)
    payload = case.model_dump(mode="python")
    payload["trajectory_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="does not match"):
        TrajectoryLabelCase.model_validate(payload)

    with pytest.raises(ValidationError, match="source_commit"):
        TrajectoryLabelSet(
            schema_version=TRAJECTORY_LABEL_SCHEMA_VERSION,
            auditor_version=TRAJECTORY_AUDITOR_VERSION,
            split="development",
            source_commit="",
            adjudicator_login=None,
            cases=[case],
        )

    with pytest.raises(ValidationError, match="duplicate case_id"):
        _label_set(case, case)


def test_contract_rejects_incompatible_schema_and_auditor_versions() -> None:
    payload = _label_set(_case("versioned", TrajectoryRecord())).model_dump(mode="python")
    payload["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError, match="schema_version"):
        TrajectoryLabelSet.model_validate(payload)

    payload = _label_set(_case("versioned", TrajectoryRecord())).model_dump(mode="python")
    payload["auditor_version"] = "9.9.9"
    with pytest.raises(ValidationError, match="incompatible"):
        TrajectoryLabelSet.model_validate(payload)


def test_independent_splits_require_real_human_identity_and_adjudication() -> None:
    trajectory = TrajectoryRecord()
    seeded = _case("seeded", trajectory)
    with pytest.raises(ValidationError, match="human"):
        _label_set(seeded, split="calibration", adjudicator_login="reviewer")

    adjudication = AdjudicationRecord(
        adjudicated_by="human",
        independence="independent",
        at=NOW,
    )
    human = _case(
        "human",
        trajectory,
        provenance="human",
        labelled_at=NOW,
        adjudication=adjudication,
    )
    independent = _label_set(
        human,
        split="held_out",
        adjudicator_login="reviewer",
    )
    assert independent.cases[0].labelled_at == NOW

    with pytest.raises(ValidationError, match="adjudicator_login"):
        _label_set(human, split="held_out")


def test_cross_split_case_or_trajectory_reuse_is_rejected() -> None:
    first = _case("first", TrajectoryRecord())
    adjudication = AdjudicationRecord(
        adjudicated_by="human",
        independence="independent",
        at=NOW,
    )
    second = _case(
        "second",
        TrajectoryRecord(),
        provenance="human",
        labelled_at=NOW,
        adjudication=adjudication,
    )
    with pytest.raises(ValueError, match="trajectory_sha256"):
        validate_label_sets(
            [
                _label_set(first, split="development"),
                _label_set(second, split="calibration", adjudicator_login="reviewer"),
            ]
        )


def test_duplicate_evidence_is_rejected_even_within_one_split() -> None:
    trajectory = TrajectoryRecord()
    first = _case("first", trajectory)
    second = _case("second", trajectory)
    with pytest.raises(ValidationError, match="duplicate trajectory_sha256"):
        _label_set(first, second)


def test_human_development_row_requires_named_adjudicator() -> None:
    adjudication = AdjudicationRecord(
        adjudicated_by="human",
        independence="independent",
        at=NOW,
    )
    human = _case(
        "human-dev",
        TrajectoryRecord(),
        provenance="human",
        labelled_at=NOW,
        adjudication=adjudication,
    )
    with pytest.raises(ValidationError, match="adjudicator_login"):
        _label_set(human)


def test_scoring_matches_path_multiplicities_and_preserves_disagreements() -> None:
    trajectory = TrajectoryRecord(
        sources=["run-diff"],
        files_read=["src/read.py"],
        files_modified=["src/changed.py"],
        read_coverage=True,
    )
    case = _case(
        "path-mismatch",
        trajectory,
        labels=_labels(
            {
                "changed-unread-file": ("positive", ["src/wrong.py"]),
                "no-post-edit-verification": ("positive", [""]),
            }
        ),
    )

    report = score_trajectory_labels([_label_set(case)])
    by_rule = {row.rule_id: row for row in report.per_check}
    assert by_rule["changed-unread-file"].true_positive == 0
    assert by_rule["changed-unread-file"].false_positive == 1
    assert by_rule["changed-unread-file"].false_negative == 1
    assert by_rule["no-post-edit-verification"].true_positive == 1
    assert report.micro.true_positive == 1
    assert report.micro.false_positive == 1
    assert report.micro.false_negative == 1
    assert report.micro.precision == 0.5
    assert report.micro.recall == 0.5
    assert report.macro.precision == 0.5
    assert report.macro.recall == 0.5
    assert report.macro.precision_checks == 2
    assert report.macro.recall_checks == 2
    assert report.exact_match.eligible_cases == 1
    assert report.exact_match.exact_cases == 0
    assert report.exact_match.rate == 0.0
    assert any(
        row.rule_id == "changed-unread-file" and row.path == "src/changed.py"
        for row in report.disagreements
    )
    assert report.cases[0].predictions[0].path == "src/changed.py"


def test_repeated_expected_path_is_a_real_multiset_false_negative() -> None:
    trajectory = TrajectoryRecord(
        sources=["run-diff"],
        files_read=["src/read.py"],
        files_modified=["src/changed.py"],
        read_coverage=True,
    )
    case = _case(
        "duplicate-path",
        trajectory,
        labels=_labels(
            {
                "changed-unread-file": (
                    "positive",
                    ["src/changed.py", "src/changed.py"],
                ),
                "no-post-edit-verification": ("positive", [""]),
            }
        ),
    )
    report = score_trajectory_labels([_label_set(case)])
    metric = next(row for row in report.per_check if row.rule_id == "changed-unread-file")
    assert (metric.true_positive, metric.false_positive, metric.false_negative) == (1, 0, 1)


def test_surplus_same_path_prediction_is_a_real_multiset_false_positive() -> None:
    calls = [
        ToolCallRecord(
            sequence=sequence,
            tool="custom_read",
            signature="same-failure",
            intent="other",
            ok=False,
            error="connection reset",
        )
        for sequence in range(1, 4)
    ]
    trajectory = TrajectoryRecord(
        sources=["mcp-tool-calls"],
        tool_calls=calls,
        retries=2,
    )
    case = _case(
        "surplus-path",
        trajectory,
        labels=_labels(
            {
                "ignored-tool-error": ("positive", [""]),
                "stale-assumption-after-failure": ("positive", [""]),
                "missing-completion-signal": ("positive", [""]),
            }
        ),
    )
    report = score_trajectory_labels([_label_set(case)])
    metric = next(
        row for row in report.per_check if row.rule_id == "stale-assumption-after-failure"
    )
    assert (metric.true_positive, metric.false_positive, metric.false_negative) == (1, 1, 0)


def test_scoring_emits_prefixed_per_check_trace_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture(_tracer: object, *, case_id: str, metrics: dict[str, object]) -> None:
        captured["case_id"] = case_id
        captured["metrics"] = metrics

    monkeypatch.setattr("mergecraft.tracing.signals.emit_eval_score", capture)
    score_trajectory_labels(
        [_label_set(_case("trace-metrics", TrajectoryRecord()))],
        tracer=object(),  # type: ignore[arg-type] - deliberately opaque tracer test double
    )
    assert captured["case_id"] == "trace-metrics"
    metrics = captured["metrics"]
    assert isinstance(metrics, dict)
    assert "trajectory.changed-unread-file.true_positive" in metrics
    assert all(str(key).startswith("trajectory.") for key in metrics)


def test_unknown_predictions_remain_raw_but_leave_all_denominators_undefined() -> None:
    trajectory = TrajectoryRecord(
        sources=["run-diff"],
        files_read=["src/read.py"],
        files_modified=["src/changed.py"],
        read_coverage=True,
    )
    case = _case(
        "unknown",
        trajectory,
        labels=_labels({rule_id: ("unknown", []) for rule_id in RULE_IDS}),
    )

    report = score_trajectory_labels([_label_set(case)])
    assert report.cases[0].predictions
    assert report.micro.precision is None
    assert report.micro.recall is None
    assert report.macro.precision is None
    assert report.macro.recall is None
    assert report.macro.precision_checks == 0
    assert report.macro.recall_checks == 0
    assert report.exact_match.eligible_cases == 0
    assert report.exact_match.rate is None


def test_human_unknown_labels_remain_ineligible_without_quality_protocol() -> None:
    adjudication = AdjudicationRecord(
        adjudicated_by="human",
        independence="independent",
        at=NOW,
    )
    case = _case(
        "human-unknown",
        TrajectoryRecord(),
        labels=_labels({rule_id: ("unknown", []) for rule_id in RULE_IDS}),
        provenance="human",
        labelled_at=NOW,
        adjudication=adjudication,
    )
    report = score_trajectory_labels(
        [_label_set(case, split="held_out", adjudicator_login="reviewer")]
    )
    assert report.eligibility.independent is True
    assert report.eligibility.quality_eligible is False
    assert report.eligibility.advisory is True
    assert report.eligibility.per_check[RULE_IDS[0]].independent == 0
    assert report.exact_match.eligible_cases == 0


def test_report_keeps_reproducible_input_identity() -> None:
    trajectory = TrajectoryRecord()
    case = _case("identity", trajectory)
    label_set = _label_set(case)
    report = score_trajectory_labels([label_set])

    assert report.inputs[0].source_commit == "a" * 40
    assert report.inputs[0].split == "development"
    assert len(report.inputs[0].label_set_sha256) == 64
    assert report.cases[0].trajectory_sha256 == canonical_trajectory_sha256(trajectory)


def test_unknown_auditor_rule_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = make_finding(
        tool="trajectory",
        rule_id="new-runtime-check",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="runtime added an unlabelled check",
        path="",
        start_line=1,
        end_line=1,
        source="trajectory",
        scope="run",
        introduced_by_pr="false",
    )
    monkeypatch.setattr(
        "mergecraft.evals.trajectory_scoring.audit_trajectory",
        lambda _trajectory: [finding],
    )
    with pytest.raises(ValueError, match="absent from the labelled contract"):
        score_trajectory_labels([_label_set(_case("unknown-rule", TrajectoryRecord()))])


def test_agent_seeded_development_report_is_advisory_and_cli_json_is_null_safe(
    tmp_path: Path,
) -> None:
    case = _case("clean", TrajectoryRecord(), labels=_labels())
    label_set = _label_set(case)
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(
        json.dumps(label_set.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["eval", "trajectory-score", "--labels", str(labels_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["micro"]["precision"] is None
    assert payload["eligibility"]["independent"] is False
    assert payload["eligibility"]["quality_eligible"] is False
    assert payload["eligibility"]["advisory"] is True
    assert payload["eligibility"]["per_check"][RULE_IDS[0]]["negative"] == 1


def test_models_forbid_extra_fields() -> None:
    payload = _label_set(_case("clean", TrajectoryRecord())).model_dump(mode="python")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        TrajectoryLabelSet.model_validate(payload)


def test_committed_development_corpus_covers_every_label_state_and_scores_exactly() -> None:
    label_sets = load_trajectory_label_sets(Path("evals/trajectories/development"))
    report = score_trajectory_labels(label_sets)

    assert report.exact_match.eligible_cases == 9
    assert report.exact_match.exact_cases == 9
    assert report.exact_match.rate == 1.0
    for rule_id in RULE_IDS:
        counts = report.eligibility.per_check[rule_id]
        assert counts.positive >= 1
        assert counts.negative >= 1
        assert counts.unknown >= 1
        assert counts.scored == counts.positive + counts.negative
        assert counts.independent == 0
    assert report.eligibility.quality_eligible is False
