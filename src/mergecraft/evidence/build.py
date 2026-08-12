"""Pure packet assembly for the Merge Evidence Packet (W1.3 — D3, D7).

The :func:`build_packet` function composes a :class:`MergeEvidencePacket`
from the sources enumerated in the W0.5 mechanical-evidence inventory —
analyzer findings, deterministic checks, CI check outcomes, and agent
metadata — without performing any I/O. The emitter at
:mod:`mergecraft.evidence.emit` is the thin I/O shell that writes the
result to a run-local path and stamps it as a CI artifact (convention 5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.finding import Finding
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    Decision,
    DeterministicCheck,
    MergeEvidencePacket,
    SelfAssessment,
)
from mergecraft.evidence.trajectory import TrajectoryRecord

if TYPE_CHECKING:
    from mergecraft.classify import BlastRadiusClassification


def _coerce_findings(raw: list[dict[str, Any]] | list[Finding] | None) -> list[Finding]:
    """Validate analyzer findings into the existing ``Finding`` model (D3).

    Accepts either already-typed ``Finding`` objects or the dicts that
    ``AnalyzerRunState.findings`` produces (``analyzers/pipeline.py``).
    Unknown taxonomy violations raise ``FindingValidationError`` — the
    packet does not silently swallow bad data.
    """
    if not raw:
        return []
    coerced: list[Finding] = []
    for item in raw:
        if isinstance(item, Finding):
            coerced.append(item)
            continue
        coerced.append(Finding.model_validate(item))
    return coerced


def _coerce_deterministic_checks(
    raw: list[dict[str, Any]] | list[DeterministicCheck] | None,
) -> list[DeterministicCheck]:
    """Validate raw check dicts into :class:`DeterministicCheck` rows."""
    if not raw:
        return []
    rows: list[DeterministicCheck] = []
    for item in raw:
        if isinstance(item, DeterministicCheck):
            rows.append(item)
            continue
        rows.append(DeterministicCheck.model_validate(item))
    return rows


def _coerce_self_assessment(
    raw: dict[str, Any] | SelfAssessment | None,
) -> SelfAssessment | None:
    """Validate the recorded self-assessment into the ``SelfAssessment`` model (#41, W2.1).

    Accepts either an already-typed ``SelfAssessment`` or a dict that mirrors
    the ``ApprovalRecord`` shape the legacy ``mcp/review.py`` tool emits
    (``would_approve`` -> ``approved``, ``sha`` passed through). Unknown
    fields are rejected — ``extra="forbid"`` is the packet-level honesty rule
    (W2.4).
    """
    if raw is None:
        return None
    if isinstance(raw, SelfAssessment):
        return raw
    if isinstance(raw, dict):
        # ``ApprovalRecord`` uses ``would_approve``; the packet uses
        # ``approved``. Translate so the legacy path can be passed in
        # without rewriting the call site.
        if "approved" not in raw and "would_approve" in raw:
            translated = {**raw, "approved": raw["would_approve"]}
            translated.pop("would_approve", None)
            raw = translated
        return SelfAssessment.model_validate(raw)
    msg = f"self_assessment must be a dict or SelfAssessment, got {type(raw).__name__}"
    raise TypeError(msg)


def _coerce_trajectory(raw: TrajectoryRecord | dict[str, Any] | None) -> TrajectoryRecord | None:
    """Validate the trajectory section into the typed ``TrajectoryRecord`` (#43, W9).

    Batch C (#43) shipped ``TrajectoryRecord`` as the typed shape the
    packet now carries. ``build_packet`` accepts both an already-typed
    record (the I/O shell's call site) and the dict form a unit test or
    legacy caller hands in. Validation is fail-loud — a malformed
    trajectory record is its own evidence defect and must not be silently
    coerced into a record of garbage.
    """
    if raw is None:
        return None
    if isinstance(raw, TrajectoryRecord):
        return raw
    if isinstance(raw, dict):
        return TrajectoryRecord.model_validate(raw)
    msg = f"trajectory must be a dict or TrajectoryRecord, got {type(raw).__name__}"
    raise TypeError(msg)


def _agent_metadata(
    *,
    agent_id: str,
    agent_version: str,
    model: str,
    requested_model: str | None = None,
    executed_model: str | None = None,
    provider: str | None = None,
    fallback_index: int = 0,
    fallback_occurred: bool = False,
) -> AgentMetadata:
    executed = executed_model or model
    requested = requested_model or executed
    return AgentMetadata(
        id=agent_id,
        version=agent_version,
        model=model,
        requested_model=requested,
        executed_model=executed,
        provider=provider or "",
        fallback_index=fallback_index,
        fallback_occurred=fallback_occurred,
    )


def build_packet(
    *,
    change_id: str,
    agent_id: str,
    agent_version: str,
    model: str,
    files_changed: list[str],
    findings: list[dict[str, Any]] | list[Finding] | None,
    deterministic_checks: list[dict[str, Any]] | list[DeterministicCheck] | None,
    self_assessment: dict[str, Any] | SelfAssessment | None = None,
    decision: Decision | None = None,
    blast_radius: BlastRadiusClassification | None = None,
    trajectory: TrajectoryRecord | dict[str, Any] | None = None,
    ci_check_runs: dict[str, Any] | None = None,
    ci_intelligence: dict[str, Any] | None = None,
    usage_entries: Any = None,
    requested_model: str | None = None,
    executed_model: str | None = None,
    provider: str | None = None,
    fallback_index: int = 0,
    fallback_occurred: bool = False,
) -> MergeEvidencePacket:
    """Assemble a :class:`MergeEvidencePacket` from structured sources.

    Parameters match the W0.5 inventory: analyzer findings, deterministic
    checks, CI check outcomes, CI-intelligence annotations, and agent
    metadata. The function is **pure** — it performs no I/O and never
    reads ``os.environ``. The emitter writes the result to disk.

    W2 (#41) attaches the agent's recorded self-assessment as its own
    sibling field (``self_assessment``), distinct from the structural
    evidence verdict (``decision``). The two are independently populated:
    ``self_assessment`` carries the agent's ``approved`` boolean + the
    reviewed ``sha``; ``decision`` carries the structural verdict. The
    verdict function refuses ``auto_merge`` when the recorded self-
    assessment is the only positive signal — see
    :func:`mergecraft.agents.gates.decide_approval` and ``tests/evidence/
    test_self_assessment.py``.

    W10 (#20) records ``requested_model`` / ``executed_model`` / ``provider``
    / ``fallback_index`` / ``fallback_occurred`` on ``agent`` unconditionally.

    ``blast_radius`` and ``evals``) remain optional. Batch B populates
    ``blast_radius`` with a typed ``BlastRadiusClassification``; Batches C / E
    extend their sections.
    """
    coerced_findings = _coerce_findings(findings)
    coerced_checks = _coerce_deterministic_checks(deterministic_checks)
    coerced_self_assessment = _coerce_self_assessment(self_assessment)

    if ci_check_runs is not None:
        logger.debug(
            "build_packet received ci_check_runs with {} suites",
            len(ci_check_runs.get("check_suites") or []),
        )
    if ci_intelligence is not None:
        logger.debug(
            "build_packet received ci_intelligence with {} clusters",
            len(ci_intelligence.get("clusters") or []),
        )
    if usage_entries is not None:
        logger.debug(
            "build_packet received {} usage_entries (Batch C consumer)",
            len(usage_entries) if hasattr(usage_entries, "__len__") else 0,
        )
    if coerced_self_assessment is not None:
        logger.debug(
            "build_packet received self_assessment approved={} sha={}",
            coerced_self_assessment.approved,
            (coerced_self_assessment.sha or "")[:7] or "(none)",
        )

    packet = MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id=change_id,
        agent=_agent_metadata(
            agent_id=agent_id,
            agent_version=agent_version,
            model=model,
            requested_model=requested_model,
            executed_model=executed_model,
            provider=provider,
            fallback_index=fallback_index,
            fallback_occurred=fallback_occurred,
        ),
        files_changed=list(files_changed),
        findings=coerced_findings,
        deterministic_checks=coerced_checks,
        self_assessment=coerced_self_assessment,
        decision=decision,
        blast_radius=blast_radius,
        trajectory=_coerce_trajectory(trajectory),
    )

    # ``trajectory`` now lands as a sibling field (Batch C, #43). The rest --
    # usage_entries / ci_check_runs / ci_intelligence -- remain deferred to W9+
    # and are logged at debug level above rather than attached here.
    _ = (ci_check_runs, ci_intelligence, usage_entries)
    return packet


__all__ = ["build_packet"]
