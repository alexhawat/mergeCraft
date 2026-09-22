"""Record shadow targets and publish the recorded corpus (#737, M4).

Module: mergecraft.evidence.shadow_compare
Depends: mergecraft.evidence.{packet,shadow}, loguru

The wave that added a second shadow target (#737) does **not** rebuild the
recorder in :mod:`mergecraft.evidence.shadow` — a second target is a second
:class:`~mergecraft.evidence.shadow.ShadowTarget` value recorded through the
existing ``record_shadow_prediction`` writer. This module is that comparison:

* :func:`compare_shadow_targets` records one row per (target, change) through
  the existing recorder and returns the disagreement rows, so a table can group
  by target as well as by lane and rule.
* :data:`LIVE_TARGET` / :data:`SECOND_TARGET` are the two concrete pinned
  configs: the live target is the incumbent model, the second target is a
  different pinned model id *and* prompt version.
* The ``__main__`` entry point is the optional, **keyless** CI job. It is a
  corpus report: it publishes rows a run already recorded. It does not call a
  model, and it does not compare a pinned target that has no row. An unmarked
  second-target row is dropped, and a second target that ran on only some
  changes is not given a synthesized result for the rest.
  Structural replay only, never live detection, and never a required PR check.

Two properties are load-bearing:

**Fail closed on the job, silent on the live path.** ``compare_shadow_targets``
propagates a recording failure — missing data is not agreement, and the job
that compares targets is the one place that fails closed (R-D5). The live
``emit_run_packet`` path keeps swallowing recorder errors so a PR never fails on
a shadow breadcrumb.

**Uncalibrated by construction.** Replaying recorded predictions says nothing
about which target is "correct"; scoring against a human outcome needs
adjudicated labels that do not exist yet (R-D7). No rate here is a calibration
claim, and none is published as one.

|Exports:
    Classes:
        ShadowComparisonRow — one recorded prediction in the comparison corpus.
        ShadowPrediction — the shape the recorder already accepts.
    Functions:
        compare_shadow_targets — record and compare two pinned targets.
        load_comparison_corpus — read the committed comparison corpus.
        render_disagreement_table — render the table for a step summary.
        main — the keyless CI entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, AgentMetadata, MergeEvidencePacket
from mergecraft.evidence.shadow import (
    LIVE_TARGET,
    SECOND_TARGET,
    ShadowRecord,
    ShadowTarget,
    disagreement_report,
    load_shadow_records,
    record_pinned_targets,
    record_shadow_prediction,
)
from mergecraft.utils.step_summary import append_step_summary

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.tracing.tracer import NullTracer, Tracer

PINNED_TARGETS: tuple[ShadowTarget, ...] = (LIVE_TARGET, SECOND_TARGET)
"""The two pinned configs the comparison job diffs."""

_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_PATH: Path = _REPO_ROOT / "evals" / "shadow" / "comparison-corpus.jsonl"
"""Committed corpus of recorded predictions replayed by the keyless job."""


@dataclass(frozen=True, slots=True)
class ShadowPrediction:
    """A recorded prediction in the shape ``record_shadow_prediction`` accepts."""

    outcome: str
    diagnostic: str
    lane: str = "review"
    metadata: dict[str, Any] = field(default_factory=dict)


class ShadowComparisonRow(BaseModel):
    """One recorded ``(change, target)`` prediction in the comparison corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    change_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    diagnostic: str = Field(min_length=1)
    lane: str = Field(default="review", min_length=1)
    actual_outcome: str | None = None
    executed: bool = False
    """True when a run produced this row. The live target's recorded review
    is kept without it; any other target is dropped unless this is set."""


def _shadow_placeholder_packet(*, change_id: str, model: str) -> MergeEvidencePacket:
    """A minimal packet so the recorder keeps its existing signature.

    The prediction path never reads the packet, and the gate-action fallback
    only needs a well-formed packet (no findings, no blast radius) — the same
    shape the recorder's own unit tests use.
    """
    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id=change_id,
        agent=AgentMetadata(id="shadow-compare", version="0.0.0", model=model),
        files_changed=[],
        findings=[],
        deterministic_checks=[],
        self_assessment=None,
        decision=None,
        blast_radius=None,
        trajectory=None,
        evals=None,
    )


def compare_shadow_targets(
    packets: Sequence[MergeEvidencePacket],
    *,
    targets: Sequence[ShadowTarget],
    output_path: Path,
    predictions: Mapping[str, Mapping[str, Any]] | None = None,
    outcomes: Mapping[str, str] | None = None,
    tracer: Tracer | NullTracer | None = None,
) -> list[dict[str, object]]:
    """Record one row per (target, change) and return the disagreement rows (#737).

    Each ``(target, change)`` pair is recorded through the **existing**
    ``record_shadow_prediction`` writer, stamped with the target identity, so a
    second target never grows a second JSONL writer. ``predictions`` maps
    ``target_id`` → ``change_id`` → prediction. When a target has a prediction
    map, a change missing from that map is skipped: the gate-action fallback
    would otherwise publish a synthesized result as that target's output.
    Omitting ``predictions`` entirely keeps the gate-action path. ``outcomes``
    maps ``change_id`` → the human final outcome.

    A recording failure **propagates**. This is the one shadow path that fails
    closed (R-D5): a job that could not record must not render missing data as
    agreement. The live emit path keeps its own swallow.
    """
    records: list[ShadowRecord] = []
    resolved_outcomes = dict(outcomes or {})
    resolved_predictions = predictions or {}
    for target in targets:
        covered = target.target_id in resolved_predictions
        target_predictions = resolved_predictions.get(target.target_id) or {}
        for packet in packets:
            change_id = packet.change_id
            if covered and change_id not in target_predictions:
                continue
            record = record_shadow_prediction(
                packet,
                change_id=change_id,
                run_id=f"shadow-compare:{target.target_id}",
                policy_id=target.target_id,
                output_path=output_path,
                target=target,
                prediction=target_predictions.get(change_id),
                actual_outcome=resolved_outcomes.get(change_id),
                tracer=tracer,
            )
            records.append(record)
    return disagreement_report(records, outcomes=resolved_outcomes)


def load_comparison_corpus(path: Path) -> list[ShadowComparisonRow]:
    """Read the JSONL comparison corpus into validated rows.

    A malformed line raises rather than being skipped: the job fails closed, so
    a corpus that cannot be read is a job error, never an empty (agreeing)
    table.
    """
    rows: list[ShadowComparisonRow] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"{path}:{number}: not valid JSON — {exc}"
            raise ValueError(msg) from exc
        rows.append(ShadowComparisonRow.model_validate(payload))
    return rows


def _predictions_from_rows(
    rows: Sequence[ShadowComparisonRow],
) -> tuple[dict[str, dict[str, ShadowPrediction]], dict[str, str]]:
    """Split corpus rows into ``predictions`` and ``outcomes`` for the comparer."""
    predictions: dict[str, dict[str, ShadowPrediction]] = {}
    outcomes: dict[str, str] = {}
    for row in rows:
        if row.target_id != LIVE_TARGET.target_id and not row.executed:
            continue
        predictions.setdefault(row.target_id, {})[row.change_id] = ShadowPrediction(
            outcome=row.outcome,
            diagnostic=row.diagnostic,
            lane=row.lane,
        )
        if row.actual_outcome is not None:
            outcomes[row.change_id] = row.actual_outcome
    return predictions, outcomes


def _packets_from_rows(
    rows: Sequence[ShadowComparisonRow],
    *,
    targets: Sequence[ShadowTarget],
) -> list[MergeEvidencePacket]:
    """Build one minimal packet per change, in first-seen order."""
    model_by_target = {target.target_id: target.model for target in targets}
    fallback_model = targets[0].model if targets else "unknown"
    seen: dict[str, MergeEvidencePacket] = {}
    for row in rows:
        if row.change_id in seen:
            continue
        seen[row.change_id] = _shadow_placeholder_packet(
            change_id=row.change_id,
            model=model_by_target.get(row.target_id, fallback_model),
        )
    return list(seen.values())


def _cell(value: object) -> str:
    """Render one table cell, mapping ``None`` to an explicit dash."""
    if value is None:
        return "—"
    return str(value)


def render_disagreement_table(rows: Sequence[Mapping[str, object]]) -> str:
    """Render the disagreement rows as a markdown table for a step summary.

    Every row carries its target identity, so the table distinguishes the two
    pinned configs by target, then by lane and rule. The caption states the one
    thing the table cannot say: it is a structural replay of recorded
    predictions, not a calibrated comparison (R-D7).
    """
    lines = [
        "### Shadow target comparison (structural replay)",
        "",
        "The live row is the default gate. The second row is prompt 2.0.0, "
        "which blocks a high-risk migration the live gate sends to a human. "
        "This job does not run a model. No threshold here is calibrated and "
        "no rate is a detection-quality claim.",
        "",
        "| Target | Model | Prompt | Lane | Rule | Predicted | Actual | Disagreement |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(row.get("target_id")),
                    _cell(row.get("target_model")),
                    _cell(row.get("target_prompt_version")),
                    _cell(row.get("lane")),
                    _cell(row.get("rule_id")),
                    _cell(row.get("predicted_action")),
                    _cell(row.get("actual_outcome")),
                    _cell(row.get("disagreement")),
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _default_output_path() -> Path:
    """Resolve the JSONL destination: ``RUNNER_TEMP`` in CI, else the temp dir."""
    runner_temp = os.environ.get("RUNNER_TEMP")
    base = Path(runner_temp) if runner_temp else Path(tempfile.gettempdir())
    return base / "mergecraft" / "shadow-compare.jsonl"


def _runtime_packets() -> list[MergeEvidencePacket]:
    """Packets the advisory job records, one per committed corpus change.

    ``#101`` is a high-risk migration, so prompt 2.0.0 blocks where the live
    gate asks for a human. ``#102`` is a low-risk pass, where the two policies
    agree.
    """
    from mergecraft.classify.blast_radius import BlastRadiusClassification
    from mergecraft.evidence.packet import Decision

    high = BlastRadiusClassification(
        lane="high",
        auto_merge_lane="forbidden",
        reason="migration files changed",
        next_action="Require human review; automatic merge is forbidden.",
        categories=["migrations"],
    )
    low = BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="generated files only",
        next_action="Eligible for automatic merge after required checks pass.",
        categories=["generated_files"],
    )
    trusted = Decision(
        verdict="success",
        reason="structural approval",
        decided_by="mergecraft.agents.gates.decide_approval",
        mode="shadow",
    )
    shadow = Decision(
        verdict="neutral",
        reason="shadow-mode decision",
        decided_by="mergecraft.agents.gates.decide_approval",
        mode="shadow",
    )
    return [
        _runtime_packet(change_id="acme/demo#101", blast_radius=high, decision=shadow),
        _runtime_packet(change_id="acme/demo#102", blast_radius=low, decision=trusted),
    ]


def _runtime_packet(
    *,
    change_id: str,
    blast_radius: Any,
    decision: Any,
) -> MergeEvidencePacket:
    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id=change_id,
        agent=AgentMetadata(id="shadow-compare", version="0.0.0", model=SECOND_TARGET.model),
        files_changed=[],
        findings=[],
        deterministic_checks=[],
        self_assessment=None,
        decision=decision,
        blast_radius=blast_radius,
        trajectory=None,
        evals=None,
    )


def record_runtime_shadow(output_path: Path) -> None:
    """Write both pinned targets to ``output_path`` for the publish step."""
    if output_path.exists():
        output_path.unlink()
    for packet in _runtime_packets():
        change_id = packet.change_id
        if change_id is None:
            msg = "runtime packet has no change_id"
            raise ValueError(msg)
        record_pinned_targets(
            packet,
            change_id=change_id,
            run_id="shadow-compare",
            output_path=output_path,
        )


def publish_runtime_shadow(path: Path) -> list[dict[str, object]]:
    """Publish the JSONL a record step wrote. Missing rows are not agreement."""
    if not path.is_file():
        msg = f"runtime shadow log is missing: {path}"
        raise ValueError(msg)
    records = load_shadow_records(path)
    if any(record.target_id is None for record in records):
        msg = "runtime shadow log has a row with no target"
        raise ValueError(msg)
    targets = {record.target_id for record in records if record.target_id is not None}
    if targets != {LIVE_TARGET.target_id, SECOND_TARGET.target_id}:
        msg = f"runtime shadow log targets are {sorted(targets)}, not both pinned targets"
        raise ValueError(msg)
    return disagreement_report(records)


def main(argv: list[str] | None = None) -> int:
    """Record both pinned targets, or publish a runtime shadow log (keyless).

    ``record`` writes the log. ``publish`` (the default) reads ``--from-run``
    when given, otherwise replays ``--corpus``. A failure returns 1. This
    entry point does not run a model.
    """
    parser = argparse.ArgumentParser(
        prog="python -m mergecraft.evidence.shadow_compare",
        description=(
            "Record both pinned shadow targets, then publish that runtime log. "
            "Does not run a model (keyless; advisory)."
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="publish",
        choices=("record", "publish"),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help=f"Recorded-prediction corpus (default: {DEFAULT_CORPUS_PATH}).",
    )
    parser.add_argument(
        "--from-run",
        type=Path,
        default=None,
        help="Runtime shadow JSONL written by the record step.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL destination for the record step (default: RUNNER_TEMP).",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "record":
            record_runtime_shadow(args.output or _default_output_path())
            return 0
        if args.from_run is not None:
            report = publish_runtime_shadow(args.from_run)
        else:
            rows = load_comparison_corpus(args.corpus)
            predictions, outcomes = _predictions_from_rows(rows)
            targets = tuple(target for target in PINNED_TARGETS if target.target_id in predictions)
            if not targets:
                msg = "corpus has no executed target predictions"
                raise ValueError(msg)
            packets = _packets_from_rows(rows, targets=targets)
            report = compare_shadow_targets(
                packets,
                targets=targets,
                output_path=args.output or _default_output_path(),
                predictions=predictions,
                outcomes=outcomes,
            )
    except Exception as exc:  # missing data is not agreement
        logger.error("shadow comparison failed closed: {}", exc)
        return 1

    table = render_disagreement_table(report)
    logger.info("{}", table)
    append_step_summary(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CORPUS_PATH",
    "LIVE_TARGET",
    "PINNED_TARGETS",
    "SECOND_TARGET",
    "ShadowComparisonRow",
    "ShadowPrediction",
    "compare_shadow_targets",
    "load_comparison_corpus",
    "main",
    "render_disagreement_table",
]
