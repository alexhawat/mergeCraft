"""W8 / W9 — verifier evidence states and audit surface (#354).

Library pins for standardized states, packet completeness, freshness,
contradiction, replay, and the D14 rule that this issue adds no second
approval path. CLI pins live in ``tests/cli/test_evidence_cmd.py``.
"""

from __future__ import annotations

from typing import Any

from mergecraft.analyzers.finding import make_finding
from tests.support.cc_batch import (
    PACKET_EVIDENCE_KINDS,
    VERIFIER_STATES,
    decide_approval_defining_files,
    load_module,
    require_callable,
)
from tests.support.dead_package_wiring import SRC_ROOT, production_invoked_names


def _make_finding(*, severity: str = "Major", fingerprint: str = "fp-major") -> Any:
    return make_finding(
        tool="agent",
        rule_id="agent:1",
        category="Functional Correctness",
        severity=severity,
        confidence="likely",
        message="missing timeout on retry",
        path="src/app.py",
        start_line=10,
        end_line=10,
        source="agent",
        fingerprint=fingerprint,
    )


def test_decide_approval_remains_the_only_approval_path() -> None:
    """D14 / #354 out of scope — no second ``decide_approval()`` (current state)."""
    invoked = production_invoked_names()
    assert "decide_approval" in invoked
    assert decide_approval_defining_files() == ["agents/gates.py"]
    gates = (SRC_ROOT / "agents" / "gates.py").read_text(encoding="utf-8")
    assert "def decide_approval(" in gates
    assert "def decide_evidence_approval(" not in gates
    assert "def decide_verifier_approval(" not in gates


def test_verifier_states_are_the_six_named_outcomes() -> None:
    """#354 — proven … inconclusive replace confirm/downgrade/drop as the audit vocab."""
    module = load_module("mergecraft.evidence.audit")
    states = getattr(module, "VERIFIER_STATES", None)
    assert states is not None
    assert frozenset(states) == VERIFIER_STATES


def test_medium_high_critical_findings_require_an_evidence_packet() -> None:
    """#354 — Major and Critical findings must carry an evidence packet."""
    module = load_module("mergecraft.evidence.audit")
    require_packet = require_callable(module, "require_packet_for_severity")
    for severity in ("Major", "Critical"):
        assert (
            require_packet(_make_finding(severity=severity, fingerprint=f"fp-{severity}")) is True
        )
    assert require_packet(_make_finding(severity="Trivial", fingerprint="fp-triv")) is False


def test_evidence_packet_supports_the_named_kinds() -> None:
    """#354 — packets name the listed evidence kinds."""
    module = load_module("mergecraft.evidence.audit")
    kinds = getattr(module, "PACKET_EVIDENCE_KINDS", None)
    assert kinds is not None
    assert frozenset(kinds) >= PACKET_EVIDENCE_KINDS


def test_unverified_findings_do_not_block_unless_policy_permits() -> None:
    """#354 — unverified must not block by default."""
    module = load_module("mergecraft.evidence.audit")
    unverified_blocks = require_callable(module, "unverified_blocks")
    finding = _make_finding()
    assert unverified_blocks(finding, policy={"allow_unverified_blockers": False}) is False
    assert unverified_blocks(finding, policy={"allow_unverified_blockers": True}) is True


def test_falsification_first_rubric_is_wired() -> None:
    """#354 — verifier rubric actively searches for reasons the finding may be wrong."""
    module = load_module("mergecraft.evidence.audit")
    rubric = getattr(module, "FALSIFICATION_RUBRIC", None)
    if rubric is None:
        rubric = require_callable(module, "falsification_rubric")()
    text = str(rubric).casefold()
    assert "wrong" in text or "falsif" in text
    assert "confirm" not in text or "search" in text or "falsif" in text


def test_evidence_freshness_provenance_hash_and_completeness_scoring() -> None:
    """#354 — freshness, provenance hashing, and completeness scoring exist."""
    module = load_module("mergecraft.evidence.audit")
    packet = {"kinds": sorted(PACKET_EVIDENCE_KINDS), "captured_at": "2026-08-20T00:00:00Z"}
    assert require_callable(module, "freshness_ok")(packet) in {True, False}
    digest = require_callable(module, "provenance_hash")(packet)
    assert isinstance(digest, str)
    assert len(digest) >= 16
    score = require_callable(module, "completeness_score")(packet)
    assert 0.0 <= float(score) <= 1.0


def test_contradiction_detection_between_tools_and_llm() -> None:
    """#354 — deterministic tools vs LLM conclusions are compared."""
    module = load_module("mergecraft.evidence.audit")
    detect = require_callable(module, "detect_contradictions")
    hits = detect(
        tool_conclusions=[{"fingerprint": "fp-major", "status": "clean"}],
        llm_conclusions=[{"fingerprint": "fp-major", "status": "defect"}],
    )
    assert hits


def test_verification_replay_is_deterministic() -> None:
    """#354 — verification replay yields a stable outcome."""
    module = load_module("mergecraft.evidence.audit")
    replay = require_callable(module, "replay_verification")
    packet = {"finding_id": "fp-major", "kinds": ["analyzer_findings"]}
    first = replay(packet)
    second = replay(packet)
    assert first == second


def test_policy_evidence_requirements_cover_severity_path_change_type_and_rule() -> None:
    """#354 — policy can require evidence by severity, path, change type, and rule."""
    module = load_module("mergecraft.evidence.audit")
    evaluate = require_callable(module, "evaluate_evidence_requirements")
    outcome = evaluate(
        finding=_make_finding(),
        policy={
            "severity": ["Major", "Critical"],
            "path": "src/**",
            "change_type": "code",
            "rule": "agent:1",
        },
        packet=None,
    )
    assert getattr(outcome, "status", outcome) in {"inconclusive", "missing", "unsatisfied"}


def test_verifier_failure_cannot_silently_promote_a_finding() -> None:
    """#354 — a failed/crashed verifier must not promote unverified → proven."""
    module = load_module("mergecraft.evidence.audit")
    apply_outcome = require_callable(module, "apply_verifier_outcome")
    result = apply_outcome(
        finding=_make_finding(),
        prior_state="unverified",
        verifier_error="judge timed out",
    )
    state = getattr(result, "state", result)
    assert str(state) in {"unverified", "inconclusive", "disproven"}
    assert str(state) != "proven"
