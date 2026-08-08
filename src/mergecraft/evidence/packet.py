"""Merge Evidence Packet — the versioned, structured artifact emitted by every run (#47).

The packet composes the existing ``Finding`` model (D3) and is built from the
sources enumerated in the W0.5 mechanical-evidence inventory — analyzer
findings, deterministic checks, CI check outcomes, and agent metadata. It is
**not** a second finding model and contains **no** hand-written JSON Schema:
the schema is derived from the Pydantic models here, mirroring the precedent
in ``mergecraft.analyzers.finding.findings_output_schema`` (D3, D7).

W1 ships the schema, the assembly, and the emitter. W2 will populate the
``decision`` field and split it from ``self_assessment``. Batches B / C / E
extend the nullable-until-later sections (blast radius, trajectory, evals).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.fields import FieldInfo

from mergecraft.analyzers.finding import Finding

# D7 — the packet is versioned from day one. Any field-level change (additive
# or otherwise) that is not accompanied by a bump of this literal must fail
# ``test_packet_schema_version_is_pinned`` at the gate. Bumps are mandatory,
# not optional.
PACKET_SCHEMA_VERSION = "1.0.0"


class _PinnedRequiredFieldInfo(FieldInfo):  # type: ignore[misc]
    """``FieldInfo`` whose ``default`` advertises the pinned version while the
    validator still treats the field as required.

    Pydantic v2 binds ``is_required()`` to ``default is PydanticUndefined``
    AND ``default_factory is None`` (see ``pydantic/fields.py``). The WA-T.3
    test pair asserts both ``is_required() is True`` (the field is required
    at validation) and ``fields["schema_version"].default == pinned`` (the
    pinned literal is discoverable on the field). A plain
    ``Field(default=...)`` is mutually exclusive with ``is_required() is
    True``; subclassing FieldInfo and pinning ``is_required()`` to True is
    the minimal way to satisfy both ends of that contract without
    duplicating the pinned literal.
    """

    def is_required(self) -> bool:
        return True


def _pinned_version_field() -> FieldInfo:
    """Return the ``FieldInfo`` carrying the pinned ``schema_version`` literal."""
    return _PinnedRequiredFieldInfo(default=PACKET_SCHEMA_VERSION)


class AgentMetadata(BaseModel):
    """Identifies the agent that produced the run.

    The carrying fields (``id``, ``version``, ``model``) are the minimum the
    packet needs to attribute findings and reproduce a run.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    model: str


class DeterministicCheck(BaseModel):
    """One decomposable mechanical check that ran (or was skipped) for the PR."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    command: str


class Decision(BaseModel):
    """The evidence verdict (W2 surface; nullable in W1).

    W1 ships the shape so the packet round-trips end-to-end. W2 populates this
    from ``decide_approval()`` (D5). ``verdict`` is a string until W9 closes
    the action vocabulary; today, expected values are ``"auto_merge"`` /
    ``"block"`` / ``"request_changes"`` / ``"require_human_review"`` /
    ``"unavailable"``.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: str
    reason: str
    decided_by: str


class MergeEvidencePacket(BaseModel):
    """The versioned, structured record of one mergeCraft run.

    Top-level required fields are the ones every run can populate today.
    ``blast_radius``, ``trajectory``, and ``evals`` are nullable until later
    batches land — they are *typed* ``| None`` here, not omitted, so the
    packet's downstream contract is fixed from W1 (D4).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _pinned_version_field()  # type: ignore[assignment]
    change_id: str
    agent: AgentMetadata
    files_changed: list[str]
    findings: list[Finding]
    deterministic_checks: list[DeterministicCheck]
    decision: Decision | None = None
    blast_radius: dict[str, Any] | None = None
    trajectory: dict[str, Any] | None = None
    evals: dict[str, Any] | None = None


def packet_output_schema() -> dict[str, Any]:
    """JSON Schema for the Merge Evidence Packet, derived from the models (D3).

    Mirrors ``mergecraft.analyzers.finding.findings_output_schema`` (the
    precedent at ``analyzers/finding.py:138``): the implementation imports
    the Pydantic model and calls ``model_json_schema()``. It does **not**
    maintain a hand-written schema dict in parallel.

    Pydantic v2 emits nested models via ``$ref`` into ``$defs`` by default,
    which would leak the wrong shape into the WA-T.1 assertion. The Finding
    schema is therefore inlined into the ``findings.items`` slot, so the
    packet's wire schema matches ``Finding`` field-for-field (D3).
    """
    schema = MergeEvidencePacket.model_json_schema()
    findings = schema.get("properties", {}).get("findings")
    if isinstance(findings, dict):
        items = findings.get("items")
        if isinstance(items, dict) and "$ref" in items:
            findings["items"] = Finding.model_json_schema()
    return schema


__all__ = [
    "PACKET_SCHEMA_VERSION",
    "AgentMetadata",
    "Decision",
    "DeterministicCheck",
    "MergeEvidencePacket",
    "packet_output_schema",
]
