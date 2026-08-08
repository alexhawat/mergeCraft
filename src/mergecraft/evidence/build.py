"""Pure packet assembly for the Merge Evidence Packet (W1.3 — D3, D7).

The :func:`build_packet` function composes a :class:`MergeEvidencePacket`
from the sources enumerated in the W0.5 mechanical-evidence inventory —
analyzer findings, deterministic checks, CI check outcomes, and agent
metadata — without performing any I/O. The emitter at
:mod:`mergecraft.evidence.emit` is the thin I/O shell that writes the
result to a run-local path and stamps it as a CI artifact (convention 5).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from mergecraft.analyzers.finding import Finding
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    Decision,
    DeterministicCheck,
    MergeEvidencePacket,
)


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


def _agent_metadata(
    *,
    agent_id: str,
    agent_version: str,
    model: str,
) -> AgentMetadata:
    return AgentMetadata(
        id=agent_id,
        version=agent_version,
        model=model,
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
    decision: Decision | None = None,
    ci_check_runs: dict[str, Any] | None = None,
    ci_intelligence: dict[str, Any] | None = None,
    self_assessment: dict[str, Any] | None = None,
    usage_entries: Any = None,
) -> MergeEvidencePacket:
    """Assemble a :class:`MergeEvidencePacket` from structured sources.

    Parameters match the W0.5 inventory: analyzer findings, deterministic
    checks, CI check outcomes, CI-intelligence annotations, and agent
    metadata. The function is **pure** — it performs no I/O and never
    reads ``os.environ``. The emitter writes the result to disk.

    Nullable-until-later sections (``blast_radius``, ``trajectory``,
    ``evals``) are intentionally left as ``None`` here; Batches B / C / E
    extend the packet with their own ``build_packet`` overlays.
    """
    coerced_findings = _coerce_findings(findings)
    coerced_checks = _coerce_deterministic_checks(deterministic_checks)

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

    packet = MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id=change_id,
        agent=_agent_metadata(
            agent_id=agent_id,
            agent_version=agent_version,
            model=model,
        ),
        files_changed=list(files_changed),
        findings=coerced_findings,
        deterministic_checks=coerced_checks,
        decision=decision,
    )

    # Attachment of unbounded-dict inputs is deferred to W2 / Batch C. The
    # packet shape is frozen at W1; W2 attaches ``self_assessment`` and
    # Batch C attaches ``trajectory`` as sibling fields rather than
    # nested dicts, so updating the model is a strict version bump (D7).
    _ = (self_assessment,)
    return packet


__all__ = ["build_packet"]
