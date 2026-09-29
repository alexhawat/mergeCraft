"""The trajectory scorer reads an approved protocol and compares a frozen baseline.

Today ``quality_eligible`` is hard-coded ``False`` and no code reads an approved
protocol, so plan 012's bounded CI comparison is unshipped. This suite pins:

* a ``TrajectoryProtocol`` model and loader for the file
  ``evals/trajectories/protocol-v1.json`` — per-check sample minimums plus a
  tolerance;
* ``quality_eligible`` is true **only** when the protocol is present, the labels
  are independent, and every check meets its pre-registered minimum; false and
  naming the failing check when one is below its minimum;
* a comparison that checks a candidate report against a frozen baseline within
  the tolerance and fails naming the check when outside it;
* with no approved protocol the gate is advisory and exits 0.

The CLI surface is ``mergecraft eval trajectory-gate --protocol … --baseline …
--candidate …``. It runs in the existing eval CI job (no new required check).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.evals import trajectory_scoring as scoring
from mergecraft.evals.adjudication import AdjudicationRecord
from mergecraft.evals.trajectory_scoring import (
    TRAJECTORY_LABEL_SCHEMA_VERSION,
    TrajectoryCheckLabel,
    TrajectoryLabelCase,
    TrajectoryLabelSet,
    canonical_trajectory_sha256,
    score_trajectory_labels,
)
from mergecraft.evidence.trajectory import TrajectoryRecord
from mergecraft.evidence.trajectory_audit import TRAJECTORY_AUDITOR_VERSION, TRAJECTORY_CHECKS

if TYPE_CHECKING:
    from collections.abc import Sequence

runner = CliRunner()
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
RULE_IDS = tuple(check.rule_id for check in TRAJECTORY_CHECKS)


def _labels(
    overrides: dict[str, tuple[str, list[str]]] | None = None,
) -> list[TrajectoryCheckLabel]:
    overrides = overrides or {}
    return [
        TrajectoryCheckLabel(
            rule_id=rule_id,
            truth=overrides.get(rule_id, ("negative", []))[0],  # type: ignore[arg-type]
            expected_paths=overrides.get(rule_id, ("negative", []))[1],
        )
        for rule_id in RULE_IDS
    ]


def _independent_case(
    case_id: str,
    *,
    labels: list[TrajectoryCheckLabel] | None = None,
    trajectory: TrajectoryRecord | None = None,
) -> TrajectoryLabelCase:
    record = trajectory or TrajectoryRecord()
    return TrajectoryLabelCase(
        case_id=case_id,
        trajectory=record,
        trajectory_sha256=canonical_trajectory_sha256(record),
        labelled_at=NOW,
        provenance="human",
        adjudication=AdjudicationRecord(
            adjudicated_by="human",
            independence="independent",
            at=NOW,
        ),
        labels=labels or _labels(),
    )


def _independent_label_set(*cases: TrajectoryLabelCase) -> TrajectoryLabelSet:
    return TrajectoryLabelSet(
        schema_version=TRAJECTORY_LABEL_SCHEMA_VERSION,
        auditor_version=TRAJECTORY_AUDITOR_VERSION,
        split="held_out",
        source_commit="a" * 40,
        adjudicator_login="reviewer",
        cases=list(cases),
    )


def _protocol_payload(
    *, minimums: dict[str, int] | None = None, tolerance: float = 0.05
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "sample_minimums": minimums or {rule_id: 1 for rule_id in RULE_IDS},
        "tolerance": tolerance,
    }


def _write_protocol(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "protocol-v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _score(labels: Sequence[TrajectoryLabelSet], protocol: Any | None) -> Any:
    return scoring.score_trajectory_labels(labels, protocol=protocol)


# ── the loader ───────────────────────────────────────────────────────────────


def test_loader_reads_the_protocol_file(tmp_path: Path) -> None:
    path = _write_protocol(tmp_path, _protocol_payload(tolerance=0.25))

    protocol = scoring.load_trajectory_protocol(path)

    assert protocol.schema_version == "1.0.0"
    assert protocol.tolerance == 0.25
    assert set(protocol.sample_minimums) == set(RULE_IDS)


def test_loader_rejects_an_unknown_schema_version(tmp_path: Path) -> None:
    payload = _protocol_payload()
    payload["schema_version"] = "2.0.0"
    path = _write_protocol(tmp_path, payload)

    with pytest.raises((ValidationError, ValueError), match="schema_version"):
        scoring.load_trajectory_protocol(path)


# ── quality eligibility ──────────────────────────────────────────────────────


def test_without_a_protocol_the_report_is_advisory() -> None:
    report = _score([_independent_label_set(_independent_case("one"))], None)

    assert report.eligibility.independent is True
    assert report.eligibility.quality_eligible is False
    assert report.eligibility.advisory is True
    assert "protocol" in report.eligibility.reason.lower()


def test_a_protocol_with_every_minimum_met_is_quality_eligible(tmp_path: Path) -> None:
    protocol = scoring.load_trajectory_protocol(_write_protocol(tmp_path, _protocol_payload()))

    report = _score([_independent_label_set(_independent_case("one"))], protocol)

    assert report.eligibility.quality_eligible is True
    assert report.eligibility.advisory is False


def test_a_check_below_its_minimum_is_named(tmp_path: Path) -> None:
    minimums = {rule_id: 1 for rule_id in RULE_IDS}
    lagging = RULE_IDS[0]
    minimums[lagging] = 5
    protocol = scoring.load_trajectory_protocol(
        _write_protocol(tmp_path, _protocol_payload(minimums=minimums))
    )

    report = _score([_independent_label_set(_independent_case("one"))], protocol)

    assert report.eligibility.quality_eligible is False
    assert report.eligibility.advisory is True
    assert lagging in report.eligibility.reason


def test_non_independent_labels_are_not_quality_eligible_even_with_a_protocol(
    tmp_path: Path,
) -> None:
    protocol = scoring.load_trajectory_protocol(_write_protocol(tmp_path, _protocol_payload()))
    seeded = TrajectoryLabelCase(
        case_id="seeded",
        trajectory=TrajectoryRecord(),
        trajectory_sha256=canonical_trajectory_sha256(TrajectoryRecord()),
        labels=_labels(),
    )
    label_set = TrajectoryLabelSet(
        schema_version=TRAJECTORY_LABEL_SCHEMA_VERSION,
        auditor_version=TRAJECTORY_AUDITOR_VERSION,
        split="development",
        source_commit="a" * 40,
        adjudicator_login=None,
        cases=[seeded],
    )

    report = _score([label_set], protocol)

    assert report.eligibility.independent is False
    assert report.eligibility.quality_eligible is False


# ── comparison against a frozen baseline ─────────────────────────────────────


def _report_with_rule_delta(*, rule_id: str, false_positive_delta: int) -> tuple[Any, Any]:
    """Return ``(baseline, candidate)`` reports differing only in one check's counts."""
    baseline = score_trajectory_labels([_independent_label_set(_independent_case("one"))])
    rows = list(baseline.per_check)
    for index, row in enumerate(rows):
        if row.rule_id != rule_id:
            continue
        rows[index] = row.model_copy(
            update={"false_positive": row.false_positive + false_positive_delta}
        )
    candidate = baseline.model_copy(update={"per_check": rows})
    return baseline, candidate


def test_comparison_passes_within_tolerance(tmp_path: Path) -> None:
    protocol = scoring.load_trajectory_protocol(
        _write_protocol(tmp_path, _protocol_payload(tolerance=1.0))
    )
    baseline, candidate = _report_with_rule_delta(rule_id=RULE_IDS[0], false_positive_delta=1)

    result = scoring.compare_trajectory_report(candidate, baseline, protocol=protocol)

    assert result.passed is True
    assert result.failures == []


def test_comparison_fails_naming_the_check(tmp_path: Path) -> None:
    protocol = scoring.load_trajectory_protocol(
        _write_protocol(tmp_path, _protocol_payload(tolerance=0.0))
    )
    baseline, candidate = _report_with_rule_delta(rule_id=RULE_IDS[0], false_positive_delta=3)

    result = scoring.compare_trajectory_report(candidate, baseline, protocol=protocol)

    assert result.passed is False
    assert RULE_IDS[0] in result.failures


# ── the CLI gate ─────────────────────────────────────────────────────────────


def _write_reports(tmp_path: Path) -> tuple[Path, Path]:
    baseline, candidate = _report_with_rule_delta(rule_id=RULE_IDS[0], false_positive_delta=3)
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(baseline.model_dump_json(), encoding="utf-8")
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    return baseline_path, candidate_path


def test_gate_is_advisory_and_exits_zero_without_a_protocol(tmp_path: Path) -> None:
    baseline_path, candidate_path = _write_reports(tmp_path)

    result = runner.invoke(
        app,
        [
            "eval",
            "trajectory-gate",
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = result.output.lower()
    assert "no approved protocol" in output
    assert "advisory" in output


def test_gate_passes_within_tolerance(tmp_path: Path) -> None:
    protocol_path = _write_protocol(tmp_path, _protocol_payload(tolerance=1.0))
    baseline_path, candidate_path = _write_reports(tmp_path)

    result = runner.invoke(
        app,
        [
            "eval",
            "trajectory-gate",
            "--protocol",
            str(protocol_path),
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
        ],
    )

    assert result.exit_code == 0, result.output


def test_gate_fails_outside_tolerance_naming_the_check(tmp_path: Path) -> None:
    protocol_path = _write_protocol(tmp_path, _protocol_payload(tolerance=0.0))
    baseline_path, candidate_path = _write_reports(tmp_path)

    result = runner.invoke(
        app,
        [
            "eval",
            "trajectory-gate",
            "--protocol",
            str(protocol_path),
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
        ],
    )

    assert result.exit_code != 0
    assert RULE_IDS[0] in result.output
