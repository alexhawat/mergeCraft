"""Tests for the typed ``EvalMetadata`` on ``MergeEvidencePacket`` (#44, W12.2).

These tests pin:

- ``MergeEvidencePacket.evals`` is now a list of ``EvalMetadata``,
  not a free-form dict.
- The Pydantic schema rejects unknown fields (``extra="forbid"``).
- Replays on the bank produce metadata that round-trips through
  ``EvalMetadata.model_validate``.
- ``PACKET_SCHEMA_VERSION`` is bumped past the last W11 value.
- The packet's JSON Schema reflects the new evals shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from mergecraft.evals.eval_metadata import EvalMetadata, build_eval_metadata
from mergecraft.evals.store import (
    Case,
    CaseStatus,
    add_case,
    replay_case,
)
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    MergeEvidencePacket,
    packet_output_schema,
)
from mergecraft.utils.learnings import LearningProvenance

# ── fixtures ───────────────────────────────────────────────────────────


def _provenance() -> LearningProvenance:
    return LearningProvenance(
        run_id="synthetic",
        pr_number=1,
        source_field="eval_bank",
        author_login="synthetic",
        author_association="OWNER",
        trust_tier="trusted",
        timestamp=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
    )


def _case(**overrides: object) -> Case:
    defaults: dict[str, object] = {
        "id": "synthetic-001",
        "title": "missed a fabricated deletion",
        "category": "missed_finding",
        "submitted_at": datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        "run_id": "synthetic",
        "pr_number": 1,
        "failure_mode": "missed_finding",
        "expected_finding": "src/mergecraft/foo.py:42-60: 'delete' on unborn file",
        "expected_decision": "block",
        "replay_command": "mergecraft eval replay synthetic-001",
        "provenance": _provenance(),
        "body": "# synthetic-001\n\ndescription\n",
    }
    defaults.update(overrides)
    return Case(**defaults)  # type: ignore[arg-type]


def _agent() -> AgentMetadata:
    return AgentMetadata(id="mergecraft", version="0.1.0", model="synthetic")


# ── PACKET_SCHEMA_VERSION pinning ──────────────────────────────────────


def test_packet_schema_version_is_minor_bump_above_w11() -> None:
    """The protocol bump is a minor bump past the W11 ``1.1.0``."""
    assert PACKET_SCHEMA_VERSION > "1.1.0"
    parts = PACKET_SCHEMA_VERSION.split(".")
    assert len(parts) == 3


# ── EvalMetadata shape ────────────────────────────────────────────────


def test_eval_metadata_rejects_unknown_fields() -> None:
    """``EvalMetadata`` is strict: unknown fields raise ``ValidationError``."""
    base = {
        "case_id": "synthetic-001",
        "run_id": "synthetic",
        "title": "missed a fabricated deletion",
        "category": "missed_finding",
        "failure_mode": "missed_finding",
        "expected_finding": "src/mergecraft/foo.py:42-60: 'delete' on unborn file",
        "expected_decision": "block",
        "replay_decision": "blocked",
        "replay_at": datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        "status": "blocked",
    }
    EvalMetadata(**base)  # baseline round-trip
    with pytest.raises(ValidationError):
        EvalMetadata(**{**base, "rogue_field": "nope"})


def test_eval_metadata_round_trips_through_model_dump() -> None:
    """The metadata round-trips through ``model_dump`` and ``model_validate``."""
    meta = EvalMetadata(
        case_id="synthetic-001",
        run_id="synthetic",
        title="missed a fabricated deletion",
        category="missed_finding",
        failure_mode="missed_finding",
        expected_finding="src/mergecraft/foo.py:42-60: 'delete' on unborn file",
        expected_decision="block",
        replay_decision="blocked",
        replay_at=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        status="blocked",
    )
    payload = meta.model_dump(mode="json")
    parsed = EvalMetadata.model_validate(payload)
    assert parsed == meta


def test_eval_metadata_rejects_decision_typed_literal_mismatch() -> None:
    """``replay_decision`` / ``status`` are locked to ``CaseStatus`` literals."""
    with pytest.raises(ValidationError):
        EvalMetadata(
            case_id="synthetic-001",
            run_id="synthetic",
            title="t",
            category="missed_finding",
            failure_mode="missed_finding",
            expected_finding="f",
            expected_decision="block",
            replay_decision="block",  # type: ignore[arg-type]
            replay_at=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
            status="blocked",
        )


# ── build_eval_metadata ──────────────────────────────────────────────


def test_build_eval_metadata_returns_blocked_when_no_current_decision(
    tmp_path: Path,
) -> None:
    """``build_eval_metadata`` propagates the case's read-only fields verbatim."""
    case = _case()
    add_case(tmp_path, case)
    diff = replay_case(case, current_decision=None)
    # `replay_diff.current_decision` is ``None`` when the replay engine
    # is unavailable; the caller maps that to ``blocked`` in the
    # packet-side metadata (per the bank contract).
    replay_decision: CaseStatus = "blocked"
    meta = build_eval_metadata(case, replay_decision=replay_decision, run_id=case.run_id)
    assert meta.case_id == case.id
    assert meta.run_id == case.run_id
    assert meta.title == case.title
    assert meta.category == case.category
    assert meta.failure_mode == case.failure_mode
    assert meta.expected_finding == case.expected_finding
    assert meta.expected_decision == case.expected_decision
    assert meta.replay_decision == replay_decision
    assert meta.status == replay_decision
    # Sanity: the embedded diff is what the helper *would* have been
    # called with, had the caller wired current_decision.
    assert diff.status == "blocked"


# ── MergeEvidencePacket.evals typing ─────────────────────────────────


def test_packet_evals_accepts_typed_list() -> None:
    """The packet's ``evals`` field accepts a list of ``EvalMetadata``."""
    meta = EvalMetadata(
        case_id="synthetic-001",
        run_id="synthetic",
        title="missed a fabricated deletion",
        category="missed_finding",
        failure_mode="missed_finding",
        expected_finding="src/mergecraft/foo.py:42-60: 'delete' on unborn file",
        expected_decision="block",
        replay_decision="blocked",
        replay_at=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        status="blocked",
    )
    packet = MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="synthetic-001",
        agent=_agent(),
        files_changed=["src/mergecraft/foo.py"],
        findings=[],
        deterministic_checks=[],
        evals=[meta],
    )
    assert packet.evals is not None
    assert packet.evals[0].case_id == "synthetic-001"


def test_packet_evals_field_default_is_none() -> None:
    """The ``evals`` field defaults to ``None`` for runs that did not replay."""
    packet = MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="synthetic-001",
        agent=_agent(),
        files_changed=[],
        findings=[],
        deterministic_checks=[],
    )
    assert packet.evals is None


def test_packet_output_schema_includes_evals_shape() -> None:
    """The output JSON Schema exposes ``EvalMetadata``'s fields under ``evals``."""
    schema = packet_output_schema()
    evals = schema["properties"]["evals"]
    # Pydantic v2 emits ``Optional[list[T]]`` as an ``anyOf`` with an
    # array branch and a null branch. We want the array branch.
    array_branch = next(branch for branch in evals["anyOf"] if branch.get("type") == "array")
    items = array_branch["items"]
    # Either the schema is inlined (``EvalMetadata.model_json_schema()``)
    # or it carries ``$ref`` into ``$defs/EvalMetadata``. Both are
    # acceptable; the operator-visible contract is the field list.
    if "$ref" in items:
        # Resolve the ref against the parent schema's ``$defs``.
        ref_name = items["$ref"].rsplit("/", 1)[-1]
        items = schema["$defs"][ref_name]
    item_props = items["properties"]
    for required in (
        "case_id",
        "run_id",
        "title",
        "category",
        "expected_decision",
        "replay_decision",
        "replay_at",
        "status",
    ):
        assert required in item_props, f"missing {required}"


__all__ = []
