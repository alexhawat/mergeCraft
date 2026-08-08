"""Self-assessment is recorded separately and never sufficient (#41 — WA-T.5, WA-T.6)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.evidence.support import import_module, sample_finding_dict

pytestmark = pytest.mark.xfail(reason="green after W1/W2", strict=False)


def test_self_assessment_is_recorded_separately_from_evidence() -> None:
    """The packet has distinct fields for self-assessment and evidence verdict (D5, #41).

    Neither field is derived from the other — both are present on the same
    packet, with independent types and values.
    """
    packet_mod = import_module("mergecraft.evidence.packet")
    fields = packet_mod.MergeEvidencePacket.model_fields
    assert "self_assessment" in fields, "packet must carry an explicit self_assessment field"
    assert "decision" in fields, "packet must carry a distinct evidence decision field"

    # The two fields must be independently populated — building a packet with
    # one set and not the other must not collapse them.
    payload = _packet_with_self_assessment(approved=True, no_findings=True)
    packet = packet_mod.MergeEvidencePacket(**payload)
    assert packet.self_assessment is not None
    assert packet.self_assessment.approved is True
    assert packet.decision is not None


def test_self_assessment_field_carries_approved_and_sha() -> None:
    """The self-assessment field records the agent's boolean plus the commit it approved."""
    packet_mod = import_module("mergecraft.evidence.packet")
    fields = packet_mod.MergeEvidencePacket.model_fields
    self_assessment_field = fields["self_assessment"]
    annotation = getattr(self_assessment_field, "annotation", None)
    annotation_str = str(annotation)
    # The nested type must carry the boolean and the commit sha.
    assert "approved" in annotation_str or _is_optional_bool(annotation)
    assert "sha" in annotation_str or "commit" in annotation_str


def _is_optional_bool(annotation: object) -> bool:
    """Best-effort: True if the annotation ultimately holds a bool."""
    args = getattr(annotation, "__args__", ())
    return any("bool" in str(arg) for arg in args) or "bool" in str(annotation)


def test_self_assessment_alone_blocks_auto_merge() -> None:
    """#41 acceptance criterion: a packet whose only positive signal is the agent's
    self-assessment cannot reach ``auto_merge``.

    Concretely, when the packet carries an approving self-assessment and **no**
    other positive evidence (no findings, no deterministic checks passing, no
    CI check runs passing), the decision function must return a verdict that
    is not ``auto_merge``.
    """
    packet_mod = import_module("mergecraft.evidence.packet")
    gates_mod = import_module("mergecraft.agents.gates")

    payload = _packet_with_self_assessment(approved=True, no_findings=True)
    packet = packet_mod.MergeEvidencePacket(**payload)

    # The decision function lives in ``mergecraft.agents.gates`` — the
    # security plan's Batch D lands ``decide_approval`` there (D5). The
    # outcome is pinned: it must not be ``auto_merge`` for a
    # self-assessment-only run.
    decision = gates_mod.decide_approval(packet, run_succeeded=True, tier="trusted")
    verdict = getattr(decision, "verdict", None) or getattr(decision, "value", None)
    assert verdict != "auto_merge", (
        "self-assessment-only run reached auto_merge; #41 acceptance criterion violated"
    )


def test_decide_approval_does_not_treat_self_assessment_as_evidence() -> None:
    """The decision function must read the ``decision`` field, not the self-assessment.

    This is the cross-field contract: even when the agent's self-assessment
    says approved=True, an explicit decision of ``block`` must be honoured.
    """
    packet_mod = import_module("mergecraft.evidence.packet")
    gates_mod = import_module("mergecraft.agents.gates")

    payload = _packet_with_self_assessment(approved=True, no_findings=True)
    payload["decision"] = {  # type: ignore[index]
        "verdict": "block",
        "reason": "explicit override — evidence verdict is authoritative",
        "decided_by": "mergecraft.agents.gates.decide_approval",
    }
    packet = packet_mod.MergeEvidencePacket(**payload)

    decision = gates_mod.decide_approval(packet, run_succeeded=True, tier="trusted")
    verdict = getattr(decision, "verdict", None) or getattr(decision, "value", None)
    assert verdict == "block", (
        "decision function honoured self_assessment over the explicit decision field"
    )


def _packet_with_self_assessment(
    *,
    approved: bool,
    no_findings: bool,
) -> dict[str, Any]:
    """Build a packet that exercises only the self-assessment signal."""
    from tests.evidence.support import sample_minimal_packet_dict

    payload = sample_minimal_packet_dict()
    payload["self_assessment"] = {
        "approved": approved,
        "sha": "0123456789abcdef0123456789abcdef01234567",
    }
    if no_findings:
        payload["findings"] = []
    else:
        payload["findings"] = [sample_finding_dict()]
    return payload
