"""Merge Evidence Packet — the versioned, structured artifact emitted by every run (#47).

The packet composes the existing ``Finding`` model (D3) and is built from the
sources enumerated in the W0.5 mechanical-evidence inventory — analyzer
findings, deterministic checks, CI check outcomes, and agent metadata. It is
**not** a second finding model and contains **no** hand-written JSON Schema:
the schema is derived from the Pydantic models here, mirroring the precedent
in ``mergecraft.analyzers.finding.findings_output_schema`` (D3, D7).

W1 shipped the schema, the assembly, and the emitter. W2 (#41) splits the
recorded ``self_assessment`` from the computed ``decision`` verdict — the
agent's ``approved`` boolean is now carried as a dedicated ``SelfAssessment``
row alongside the ``Decision`` so the two signals are independently
inspectable and the verdict is never a function of the agent's prose alone.
W12 (#44) wires the Failure Memory and Eval Bank into the ``evals`` section:
a list of :class:`mergecraft.evals.store.EvalMetadata` rows (lightweight
summaries; the full case lives under ``evals/cases/``).

Batches B / C extend the nullable-until-later sections (blast radius,
trajectory). W9 (#46) fills the thermostat's action vocabulary on the
``decision`` row.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.fields import FieldInfo

from mergecraft.analyzers.finding import Finding
from mergecraft.classify import BlastRadiusClassification  # noqa: TC001
from mergecraft.evals.store import EvalMetadata
from mergecraft.evidence.trajectory import TrajectoryRecord

# D7 — the packet is versioned from day one. Any field-level change (additive
# or otherwise) that is not accompanied by a bump of this literal must fail
# ``test_packet_schema_version_is_pinned`` at the gate. Bumps are mandatory,
# not optional.
#
# Version history:
# - 1.0.0 — W1 initial schema (#47)
# - 1.1.0 — W2 (#41) adds the ``self_assessment`` section as a sibling of
#   ``decision``. Additive (minor bump); the verdict function reads the
#   ``self_assessment`` field but the wire shape is backwards-compatible.
# - 1.2.0 — W5 (#42) replaces the untyped ``blast_radius`` placeholder with
#   ``BlastRadiusClassification``. The section remains optional, but populated
#   packets now carry a validated lane, reason, next action, and lane policy.
# - 1.3.0 — W12 (#44) promotes the ``evals`` section from ``dict[str, Any]``
#   to ``list[EvalMetadata]``. Additive (minor bump); a packet that
#   previously set ``evals`` to ``None`` continues to validate, and a
#   packet that previously set it to a dict is no longer wire-compatible
#   — no live consumer reads the legacy dict shape today, so the bump is
#   safe.
# - 1.4.0 — W7 (#43) fills the ``trajectory`` section. The shape is still
#   optional; the previous version permitted a dict of any shape, this
#   version asserts the typed ``TrajectoryRecord`` schema. The on-the-wire
#   JSON is unchanged because ``TrajectoryRecord`` was the implicit shape
#   the Batch C code already serialised; the field type is what moves.
# - 1.5.0 — W9 (#46) extends the ``decision`` row with a typed
#   ``action`` field (closed action vocabulary) and a ``decided_by_action``
#   attribution. The optional ``numeric_score`` field is intentionally
#   **absent** — a numeric score must never appear without findings and a
#   decision beside it (#46 "not a dashboard" criterion).
# - 1.6.0 — production-readiness W10 (#20) adds requested/executed model,
#   provider, and fallback index/occurrence fields on ``AgentMetadata`` so
#   every packet proves which model actually ran (not opt-in tracing only).
# - 1.7.0 — S5 (#145) adds the ``mode_prompt_versions`` section: one row per
#   mode that ran, carrying the mode name and its prompt version. Additive
#   (minor bump) — a packet that previously omitted the field still
#   validates, and the section's ``None`` default keeps it forward-
#   compatible with consumers that do not yet read it.
PACKET_SCHEMA_VERSION = "1.7.0"


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
    packet needs to attribute findings and reproduce a run. W10 (#20) adds
    requested/executed/provider/fallback fields so operators can pin the
    reviewer model and prove which slug actually ran — always present on
    emitted packets, not only via opt-in tracing.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    model: str
    # Additive defaults keep pre-1.6.0 constructors / fixtures valid while
    # ``build_packet`` / ``emit_run_packet`` always populate them.
    requested_model: str = ""
    executed_model: str = ""
    provider: str = ""
    fallback_index: int = 0
    fallback_occurred: bool = False


class DeterministicCheck(BaseModel):
    """One decomposable mechanical check that ran (or was skipped) for the PR."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    command: str


class Decision(BaseModel):
    """The evidence verdict (W2 surface; nullable in W1).

    W1 ships the shape so the packet round-trips end-to-end. W2 populates this
    from ``decide_approval()`` (D5). W9 (#46) fills ``action`` with the
    closed action vocabulary: ``auto_merge`` / ``block`` / ``request_changes``
    / ``require_human_review`` / ``require_more_tests`` / ``quarantine`` /
    ``escalate``. ``action`` is the structural successor to the legacy
    ``verdict`` string — every outcome now maps to a *named* action, never
    to a number.

    The Decision row is the *authoritative* verdict: when ``decide_approval()``
    is asked to consume a packet, an explicit ``Decision.verdict`` wins over
    every other signal — including the agent's recorded self-assessment. That
    is the #41 hard rule: the agent's prose cannot outvote the structural
    evidence verdict.

    ``action`` is a sibling of ``verdict`` and never derived from it. A
    packet produced before W9 carries a ``Decision`` without ``action``; the
    typed schema accepts both, and a downstream reader can read whichever
    field is populated. ``mode`` is the mode (``shadow`` / ``enforce``) the
    decision was rendered in. ``shadow`` records the prediction; ``enforce``
    applies the action as a gate.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: str
    reason: str
    decided_by: str
    action: str | None = None
    decided_by_action: str | None = None
    mode: str | None = None


class SelfAssessment(BaseModel):
    """The agent's recorded self-assessment — what it *said* (#41).

    Distinct from the evidence verdict. The agent calls
    ``create_pull_request_review(approved=...)`` during the run; that boolean
    is captured here as the agent's own statement about the PR, with the
    reviewed commit SHA so the recording is traceable.

    This row is **advisory**. It is never the sole positive input to a
    decision — when the ``Decision`` field on the same packet is absent and
    the only positive signal is ``self_assessment.approved == True``, the
    decision function refuses ``auto_merge``. The verdict is computed from
    structural evidence (typed findings, deterministic checks, run state,
    trust tier), not from this row.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool
    sha: str | None = None


class ModePromptVersion(BaseModel):
    """Identifies the prompt body that produced a run for one mode (#145).

    A run can carry multiple modes — built-ins, custom, future revisions —
    each with its own content identity. Without this row an archived verdict
    cannot be attributed to the prompt body that produced it, which is the
    same problem ``JudgePin`` solves for the verifier (see
    ``mergecraft.agents.verifier.JudgePin``).
    """

    model_config = ConfigDict(extra="forbid")

    mode_name: str
    prompt_version: str


class MergeEvidencePacket(BaseModel):
    """The versioned, structured record of one mergeCraft run.

    Top-level required fields are the ones every run can populate today.
    ``blast_radius`` and ``trajectory`` remain nullable until later
    batches land — they are *typed* ``| None`` here, not omitted, so the
    packet's downstream contract is fixed from W1 (D4). The ``evals``
    section is typed ``list[EvalMetadata] | None`` from W12 (#44): each
    row is a lightweight summary of a replay run attached to this
    packet's verdict; the full case continues to live under
    ``evals/cases/<case_id>.md``. ``mode_prompt_versions`` carries the
    S5 (#145) prompt-version rows so an archived verdict can be read
    against the prompt that produced it.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _pinned_version_field()  # type: ignore[assignment]
    change_id: str
    agent: AgentMetadata
    files_changed: list[str]
    findings: list[Finding]
    deterministic_checks: list[DeterministicCheck]
    self_assessment: SelfAssessment | None = None
    decision: Decision | None = None
    blast_radius: BlastRadiusClassification | None = None
    trajectory: TrajectoryRecord | None = None
    evals: list[EvalMetadata] | None = None
    mode_prompt_versions: list[ModePromptVersion] | None = None


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
    return schema


__all__ = [
    "PACKET_SCHEMA_VERSION",
    "AgentMetadata",
    "Decision",
    "DeterministicCheck",
    "MergeEvidencePacket",
    "ModePromptVersion",
    "SelfAssessment",
    "packet_output_schema",
]
