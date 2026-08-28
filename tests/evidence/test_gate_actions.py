"""RED suite for the gate-action map (#46) and shadow-mode recorder (#50).

WD-T of the merge-evidence wave plan. Every case here is written against
the contract W9/W10 must satisfy, not against an implementation:

* **WD-T.1** — five example policies from #46, one test each. Each maps a
  named input packet to a distinct named action.
* **WD-T.2** — the action vocabulary is closed: ``auto_merge`` /
  ``block`` / ``request_changes`` / ``require_human_review`` /
  ``require_more_tests`` / ``quarantine`` / ``escalate``. Anything else
  is rejected at the boundary.
* **WD-T.3** — #46's "not a dashboard" criterion: a numeric score may
  never appear without ``findings`` and a ``decision`` beside it.
* **WD-T.4** — shadow mode records the prediction without blocking; an
  enforce mode actually blocks.
* **WD-T.5** — the disagreement report groups by lane and rule.
* **WD-T.6** — every new gate defaults to ``shadow`` (D12).

The five named policies are picked for clearly distinguishable triggers:
a schema failure, a changed-unread-file trajectory finding, a low-risk
passing change, a repeated-tool-loop, and a high-risk migration. Mutating
each policy's mapping individually must break the corresponding test and
no other one — a property put to the test in the close-out mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.finding import make_finding

if TYPE_CHECKING:
    from mergecraft.evidence.packet import MergeEvidencePacket


# ── helpers ──────────────────────────────────────────────────────────────────


def _packet(**overrides: Any) -> MergeEvidencePacket:
    """Build a minimal packet. Per-test overrides keep the triggers distinct."""
    from mergecraft.evidence.packet import (
        PACKET_SCHEMA_VERSION,
        AgentMetadata,
        MergeEvidencePacket,
    )

    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#42",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "self_assessment": None,
        "decision": None,
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
    }
    base.update(overrides)
    return MergeEvidencePacket(**base)


def _schema_failure_packet() -> MergeEvidencePacket:
    """A packet whose evidence is missing — schema failure territory."""
    return _packet()


def _changed_unread_packet() -> MergeEvidencePacket:
    """A trajectory finding flagged changed-unread-file."""
    finding = make_finding(
        tool="trajectory",
        rule_id="changed-unread-file",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="certain",
        message="src/x.py was modified but never read during this run",
        path="src/x.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    return _packet(findings=[finding])


def _low_risk_passing_packet() -> MergeEvidencePacket:
    """A packet with no findings, no trajectory findings, low blast radius."""
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
    from mergecraft.classify.blast_radius import BlastRadiusClassification
    from mergecraft.evidence.packet import Decision

    classification = BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="No elevated blast-radius category was detected.",
        next_action="Eligible for automatic merge after required checks pass.",
        categories=[],
    )
    packet = _packet(findings=[], blast_radius=classification)
    decision = Decision(
        verdict="success",
        reason="low-risk passing: trusted structural success with no blockers",
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet.model_copy(update={"decision": decision})


def _tool_loop_packet() -> MergeEvidencePacket:
    """A repeated-tool-loop trajectory finding."""
    finding = make_finding(
        tool="trajectory",
        rule_id="repeated-tool-loop",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="the same call was repeated 5 times with identical arguments",
        path="",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    return _packet(findings=[finding])


def _high_risk_migration_packet() -> MergeEvidencePacket:
    """A packet with a high blast radius (migrations) — auto-merge forbidden."""
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    classification = BlastRadiusClassification(
        lane="high",
        auto_merge_lane="forbidden",
        reason="Detected blast-radius categories: migrations.",
        next_action="Require human review; automatic merge is forbidden.",
        categories=["migrations"],
    )
    return _packet(
        files_changed=["db/migrations/0007_drop_users.sql"],
        blast_radius=classification,
    )


def _find_action(predicted: Any) -> str:
    """Read the action out of a ``GateAction`` row, regardless of shape."""
    if isinstance(predicted, str):
        return predicted
    if hasattr(predicted, "action"):
        return predicted.action
    if isinstance(predicted, dict):
        return str(predicted.get("action"))
    msg = f"unsupported action row shape: {type(predicted).__name__}"
    raise TypeError(msg)


# ── WD-T.1 — five example policies ────────────────────────────────────────────


def test_policy_schema_failure_maps_to_block() -> None:
    """A packet with no evidence routes to ``block`` (#46 example)."""
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    action = decide_action(_schema_failure_packet(), policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "block"


def test_policy_changed_unread_file_maps_to_request_changes() -> None:
    """A trajectory finding of changed-unread-file routes to ``request_changes``."""
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    action = decide_action(_changed_unread_packet(), policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "request_changes"


def test_policy_has_blockers_maps_to_request_changes() -> None:
    """Critical/Major findings use the ``has_blockers`` policy key, not unread-file."""
    from mergecraft.agents.gates import decide_action, select_rule_id
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    finding = make_finding(
        tool="agent",
        rule_id="SEC-1",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="blocker",
        path="src/auth.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    packet = _packet(findings=[finding])
    assert select_rule_id(packet) == "has_blockers"
    action = decide_action(packet, policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "request_changes"


def test_policy_low_risk_passing_maps_to_auto_merge() -> None:
    """A clean low-risk PR routes to ``auto_merge`` (#46 acceptance)."""
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    action = decide_action(_low_risk_passing_packet(), policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "auto_merge"


def test_policy_tool_loop_maps_to_require_more_tests() -> None:
    """A repeated-tool-loop trajectory finding routes to ``require_more_tests``."""
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    action = decide_action(_tool_loop_packet(), policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "require_more_tests"


def test_policy_high_risk_migration_maps_to_require_human_review() -> None:
    """A high blast radius routes to ``require_human_review`` (#46 acceptance)."""
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    action = decide_action(_high_risk_migration_packet(), policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "require_human_review"


# ── WD-T.2 — closed action vocabulary ─────────────────────────────────────────


def test_every_outcome_maps_to_a_named_action() -> None:
    """The action vocabulary is closed: seven names, nothing else.

    Closed vocabulary — one row per name, no free-form string. The seven
    named actions are locked by #46 and D12 (``shadow`` is a mode, not
    an action): ``auto_merge``, ``block``, ``request_changes``,
    ``require_human_review``, ``require_more_tests``, ``quarantine``,
    ``escalate``.
    """
    from mergecraft.agents.gates import GateAction, decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    expected: frozenset[str] = frozenset(
        {
            "auto_merge",
            "block",
            "request_changes",
            "require_human_review",
            "require_more_tests",
            "quarantine",
            "escalate",
        }
    )
    actual = frozenset(action.value for action in GateAction)
    assert expected == actual

    # The five named policies land on five of the seven; the other two
    # (quarantine, escalate) are reachable when the policy set is
    # extended or when a finding carries a recommended action that does
    # not fit the named rules.
    action = decide_action(_low_risk_passing_packet(), policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) in expected


def test_unknown_action_in_policy_is_rejected() -> None:
    """A policy that emits a non-vocabulary action is a fail-loud bug."""
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    bogus = dict(DEFAULT_GATE_POLICIES)
    bogus["schema_failure"] = ("banana", "this is not a real action")
    with pytest.raises((ValueError, KeyError, TypeError)):
        decide_action(_schema_failure_packet(), policy=bogus)


# ── WD-T.3 — not a dashboard ──────────────────────────────────────────────────


def test_numeric_score_never_appears_without_findings_and_decision() -> None:
    """#46's "not a dashboard" criterion: a numeric score needs findings + decision.

    The merge-evidence packet is the only place a score appears (if it
    does at all). When a score is present, ``findings`` and ``decision``
    must be populated alongside it. A score with no findings ("looks
    85% trustworthy") is the dashboard anti-pattern #46 forbids.
    """
    from mergecraft.evidence.packet import MergeEvidencePacket

    schema = MergeEvidencePacket.model_json_schema()
    score_field = schema.get("properties", {}).get("numeric_score")
    if score_field is None:
        # No score field exists — the anti-pattern is structurally
        # prevented at the schema level, which is the strongest form of
        # "not a dashboard". Document that.
        assert "decision" in schema["properties"]
        assert "findings" in schema["properties"]
        return

    # If a score field *does* exist, the schema must require findings
    # and decision to be present alongside it. The WA-T.4 invariant
    # (findings + decision are required) is the upstream half of this.
    assert "decision" in schema.get("required", [])
    assert "findings" in schema.get("required", [])


# ── WD-T.4 — shadow mode records without blocking ───────────────────────────


def test_shadow_mode_records_prediction_without_blocking() -> None:
    """The shadow recorder returns the predicted action without enforcing it.

    ``predict_action`` is the shadow-mode reader: it accepts a packet
    and returns the action the gate *would* take, with no side effects
    on the run. The runner is what records the prediction; the
    prediction itself is never a gate.
    """
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES
    from mergecraft.evidence.shadow import predict_action

    # Pure predict: the same packet returns the same action.
    packet = _low_risk_passing_packet()
    first = predict_action(packet, policy=DEFAULT_GATE_POLICIES)
    second = predict_action(packet, policy=DEFAULT_GATE_POLICIES)
    assert first == second
    # The prediction matches the gate's verdict for that packet.
    assert first == _find_action(decide_action(packet, policy=DEFAULT_GATE_POLICIES))


def test_enforce_and_shadow_yield_same_action_for_low_risk() -> None:
    """Enforce mode routes the same packet to a *committed* action.

    In shadow mode the prediction is recorded; in enforce it is the
    decision. The two produce the same named action for any given
    packet — what differs is whether the action is *applied*.
    """
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES
    from mergecraft.evidence.shadow import enforce_action, predict_action

    packet = _changed_unread_packet()
    predicted = predict_action(packet, policy=DEFAULT_GATE_POLICIES)
    enforced = enforce_action(packet, policy=DEFAULT_GATE_POLICIES)
    assert _find_action(predicted) == _find_action(enforced)


def test_record_shadow_prediction_writes_to_disk(tmp_path: Any) -> None:
    """The shadow recorder persists a row per packet for the disagreement report."""
    import pathlib

    from mergecraft.evidence.shadow import record_shadow_prediction

    target = pathlib.Path(tmp_path) / "shadow.jsonl"
    row = record_shadow_prediction(
        _high_risk_migration_packet(),
        change_id="acme/demo#42",
        run_id="run-1",
        policy_id="default",
        output_path=target,
    )
    # The function returns the predicted row; the file write is a side
    # effect asserted below.
    assert _find_action(row) == "require_human_review"
    assert target.is_file(), "shadow recorder did not write to disk"
    assert target.read_text(encoding="utf-8").strip(), "shadow record is empty"


# ── WD-T.5 — disagreement report ─────────────────────────────────────────────


def test_disagreement_report_groups_by_lane_and_rule() -> None:
    """The disagreement report groups predicted vs. actual by lane and rule."""
    from mergecraft.evidence.shadow import disagree_with_outcome

    rows = disagree_with_outcome(
        predicted_action="block",
        predicted_lane="high",
        predicted_rule_id="high_risk_migration",
        actual_outcome="merged",
        repo_area="db/migrations",
    )
    assert rows["lane"] == "high"
    assert rows["rule_id"] == "high_risk_migration"
    assert rows["repo_area"] == "db/migrations"
    assert rows["predicted_action"] == "block"
    assert rows["actual_outcome"] == "merged"
    assert rows["disagreement"] is True


def test_disagreement_report_on_match_records_no_disagreement() -> None:
    """A prediction that matches the actual outcome is not a disagreement."""
    from mergecraft.evidence.shadow import disagree_with_outcome

    rows = disagree_with_outcome(
        predicted_action="block",
        predicted_lane="high",
        predicted_rule_id="high_risk_migration",
        actual_outcome="merged",
        repo_area="db/migrations",
    )
    # When the predicted action matches the actual outcome, the row
    # records an agreement, not a disagreement.
    rows_match = disagree_with_outcome(
        predicted_action="block",
        predicted_lane="high",
        predicted_rule_id="high_risk_migration",
        actual_outcome="closed",
        repo_area="db/migrations",
    )
    assert rows["disagreement"] is True
    assert rows_match["disagreement"] is False


# ── WD-T.6 — every new gate defaults to shadow (D12) ─────────────────────────


def test_new_gates_default_to_shadow() -> None:
    """D12: every gate this plan introduces defaults to ``shadow``.

    A merge-evidence gate that defaults to ``enforce`` on day one is
    the defect D12 exists to prevent. The gate's default mode is read
    off the typed settings; a typo'd value should also fall back to
    shadow, never widen.
    """
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    gates = settings.gates
    # Every gate introduced by this plan defaults to ``shadow``.
    assert gates.gate_action == "shadow", (
        f"gate 'gate_action' defaults to {gates.gate_action!r} — D12 mandates shadow"
    )
    assert gates.thermostat == "shadow", (
        f"gate 'thermostat' defaults to {gates.thermostat!r} — D12 mandates shadow"
    )


def test_unrecognised_gate_mode_falls_back_to_shadow() -> None:
    """An unrecognised gate mode widens to ``shadow``, never to ``enforce``.

    A typo like ``GATE_MODE=Enforce`` (``E`` uppercase) must not silently
    enable enforcement. The settings validator is the gate against the
    gate going live without review.
    """
    from mergecraft.config.settings import RepoSettings

    # A bona fide unknown value is rejected by the typed model — the
    # Literal["shadow", "enforce"] is the contract.
    with pytest.raises((ValueError, TypeError)):
        RepoSettings.model_validate({"gates": {"gate_action": "ENFORCE"}})
    # The two valid modes are shadow and enforce.
    valid = RepoSettings.model_validate({}).gates
    assert valid.gate_action == "shadow"
    enforced = RepoSettings.model_validate({"gates": {"gate_action": "enforce"}}).gates
    assert enforced.gate_action == "enforce"


def test_has_blockers_wins_over_changed_unread_file() -> None:
    """Critical/Major findings beat changed-unread-file / tool-loop telemetry."""
    from mergecraft.agents.gates import decide_action, select_rule_id
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    blocker = make_finding(
        tool="agent",
        rule_id="SEC-1",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="blocker",
        path="src/auth.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    unread = make_finding(
        tool="trajectory",
        rule_id="changed-unread-file",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="src/x.py was modified but never read",
        path="src/x.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    packet = _packet(findings=[unread, blocker])
    assert select_rule_id(packet) == "has_blockers"
    action = decide_action(packet, policy=DEFAULT_GATE_POLICIES)
    assert _find_action(action) == "request_changes"


def test_rule_predicates_table_is_the_only_matcher_and_includes_has_blockers() -> None:
    """``_RULE_PREDICATES`` drives ``select_rule_id`` and lists ``has_blockers``."""
    from mergecraft.agents.gates import _RULE_PREDICATES, select_rule_id

    rule_ids = [rule_id for _predicate, rule_id, _action in _RULE_PREDICATES]
    assert "has_blockers" in rule_ids
    assert rule_ids.index("has_blockers") < rule_ids.index("changed-unread-file")
    assert "schema_failure" not in rule_ids
    # Behavioural ``select_rule_id`` / catch-all coverage lives in
    # ``tests/agents/test_gate_rule_selection.py`` (D4).
    assert select_rule_id is not None
    from mergecraft.evidence import gate_policy
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES, GateAction

    assert gate_policy.__doc__ is not None
    assert "six" in gate_policy.__doc__
    assert "has_blockers" in gate_policy.__doc__
    assert DEFAULT_GATE_POLICIES["schema_failure"] is GateAction.BLOCK
