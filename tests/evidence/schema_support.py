"""Expanded model schemas for packet contract assertions."""

from __future__ import annotations

from typing import Any

from mergecraft.analyzers.finding import Finding
from mergecraft.evals.eval_metadata import EvalMetadata
from mergecraft.evidence.packet import (
    CoverageSection,
    MergeEvidencePacket,
    RunHealth,
    RunMetrics,
    TrajectoryRecord,
)


def packet_output_schema() -> dict[str, Any]:
    """JSON Schema for the Merge Evidence Packet, derived from the models (D3).

    Mirrors ``mergecraft.analyzers.finding.findings_output_schema`` (the
    precedent at ``analyzers/finding.py:138``): the implementation imports
    the Pydantic model and calls ``model_json_schema()``. It does **not**
    maintain a hand-written schema dict in parallel.

    Pydantic v2 emits nested models via ``$ref`` into ``$defs`` by default,
    which would leak the wrong shape into the WA-T.1 assertion. The Finding
    schema is therefore inlined into the ``findings.items`` slot, so the
    packet's wire schema matches ``Finding`` field-for-field (D3). The
    ``evals`` section inlines ``EvalMetadata`` for the same reason.
    """
    schema = MergeEvidencePacket.model_json_schema()
    findings = schema.get("properties", {}).get("findings")
    if isinstance(findings, dict):
        items = findings.get("items")
        if isinstance(items, dict) and "$ref" in items:
            findings["items"] = Finding.model_json_schema()
    evals = schema.get("properties", {}).get("evals")
    if isinstance(evals, dict):
        items = evals.get("items")
        if isinstance(items, dict) and "$ref" in items:
            evals["items"] = EvalMetadata.model_json_schema()
    trajectory = schema.get("properties", {}).get("trajectory")
    if isinstance(trajectory, dict) and "$ref" in trajectory:
        trajectory.clear()
        trajectory.update(TrajectoryRecord.model_json_schema())
    coverage = schema.get("properties", {}).get("coverage")
    if isinstance(coverage, dict):
        ref = coverage.get("$ref") or next(
            (
                opt.get("$ref")
                for opt in coverage.get("anyOf", [])
                if isinstance(opt, dict) and "$ref" in opt
            ),
            None,
        )
        if ref:
            coverage.clear()
            coverage.update(CoverageSection.model_json_schema())
    run_health = schema.get("properties", {}).get("run_health")
    if isinstance(run_health, dict) and "$ref" in run_health:
        run_health.clear()
        run_health.update(RunHealth.model_json_schema())
    run_metrics = schema.get("properties", {}).get("run_metrics")
    if isinstance(run_metrics, dict) and "$ref" in run_metrics:
        run_metrics.clear()
        run_metrics.update(RunMetrics.model_json_schema())
    return schema
