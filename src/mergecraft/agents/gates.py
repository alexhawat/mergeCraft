"""Subagent mutates deny + native FS denies + structural approval gate (ported from
subagentToolGates / nativeFsDenies and extended by the security-trust-boundary plan
Batch D and the merge-evidence plan Batch A - W2, Batches C - W7/W8, Batch D - W9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Union, overload

from loguru import logger

from mergecraft.evidence.gate_policy import (
    DEFAULT_GATE_POLICIES,
    NAMED_GATE_POLICY_ROWS,
    GateAction,
)
from mergecraft.evidence.gate_policy import GateActionPolicy as GateActionPolicy
from mergecraft.evidence.packet import Decision as PacketDecision
from mergecraft.evidence.packet import MergeEvidencePacket
from mergecraft.mcp.server import build_orchestrator_tools
from mergecraft.mcp.shared import (
    REVIEWER_ALLOWED_TOOL_CLASSES,
    JsonSchema,
    ToolClass,
    admits_readonly_role,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.mcp.context import ToolContext
    from mergecraft.utils.status_checks import Conclusion

# OpenCode Wildcard dialect write denies for the entire .git tree
GIT_NATIVE_WRITE_DENY_OPENCODE: dict[str, str] = {
    ".git": "deny",
    ".git/*": "deny",
    "*/.git": "deny",
    "*/.git/*": "deny",
}

GIT_NATIVE_READ_DENY_OPENCODE: dict[str, str] = {
    ".git/config": "deny",
}

CLAUDE_READ_TOOLS = ("Read", "Grep", "Glob")

GIT_NATIVE_WRITE_DENY_CLAUDE: list[str] = [
    "Edit(.git)",
    "Edit(.git/**)",
    "Edit(**/.git)",
    "Edit(**/.git/**)",
]

GIT_NATIVE_READ_DENY_CLAUDE: list[str] = [f"{tool}(.git/config)" for tool in CLAUDE_READ_TOOLS]


# Severities that block the approval gate. Anything below (Minor, Trivial) is
# advisory only — the gate treats the run as approved. Centralized here so the
# merge-evidence plan's W2 (D12) and the analyzer plan's blocker taxonomy share
# one source of truth.
BLOCKING_SEVERITIES: Final[frozenset[str]] = frozenset({"Critical", "Major"})

# Only rows attributed to the structural approval gate may be honoured when a
# packet already carries an explicit ``decision`` (D9 / LR-1).
TRUSTED_PACKET_DECIDED_BY: Final[str] = "mergecraft.agents.gates.decide_approval"

# Terminal-protocol tools are orchestrator-only even when ``mutates=False``.
TERMINAL_PROTOCOL_DENIED_TOOL_NAMES: Final[frozenset[str]] = frozenset({"submit_review_verdict"})


def _denied_tool_names_for_allowed_classes(
    ctx: ToolContext,
    allowed: frozenset[ToolClass],
    *,
    role: str,
    output_schema: JsonSchema | None = None,
) -> list[str]:
    registered = build_orchestrator_tools(ctx, output_schema)
    names = [spec.name for spec in registered if not admits_readonly_role(spec, allowed)]
    if not names:
        msg = (
            f"{role} deny list derived empty — no MCP tool is outside the role's "
            "allowed read-only surface. refusing to start with the gate effectively disabled."
        )
        raise RuntimeError(msg)
    return names


def subagent_denied_tool_names(
    ctx: ToolContext,
    output_schema: JsonSchema | None = None,
) -> list[str]:
    """Canonical bare names denied to reviewer-like subagents.

    Derivation is the complement of ``admits_readonly_role`` (class filter
    intersected with ``mutates``). ``TERMINAL_PROTOCOL_DENIED_TOOL_NAMES`` is
    unioned so a ``mutates=False`` terminal tool cannot drop off the deny list
    if it is misclassified.
    """
    names = _denied_tool_names_for_allowed_classes(
        ctx,
        REVIEWER_ALLOWED_TOOL_CLASSES,
        role="subagent",
        output_schema=output_schema,
    )
    for terminal_name in TERMINAL_PROTOCOL_DENIED_TOOL_NAMES:
        if terminal_name not in names:
            names.append(terminal_name)
    return names


def build_claude_native_fs_denies(
    extra_secret_paths: list[str] | None = None,
) -> list[str]:
    denies = [*GIT_NATIVE_WRITE_DENY_CLAUDE, *GIT_NATIVE_READ_DENY_CLAUDE]
    for path in extra_secret_paths or []:
        denies.append(f"Read({path})")
        denies.append(f"Edit({path})")
    return denies


def build_opencode_native_fs_permission() -> dict[str, object]:
    return {
        "edit": {"*": "allow", **GIT_NATIVE_WRITE_DENY_OPENCODE},
        "read": {"*": "allow", **GIT_NATIVE_READ_DENY_OPENCODE},
    }


def _has_blocker(findings: list[Finding]) -> bool:
    """True iff any finding carries a severity the gate treats as blocking."""
    return any(f.severity in BLOCKING_SEVERITIES for f in findings)


def _packet_has_blockers(packet: MergeEvidencePacket) -> bool:
    """True iff ``packet`` carries any blocking finding."""
    return _has_blocker(packet.findings)


_REQUIRED_STATIC_CHECK_SATISFIED: Final[frozenset[str]] = frozenset({"passed", "not_applicable"})
"""Statuses that satisfy a required static check (AG0-G4a / MCB-16)."""


def _required_static_check_row_satisfied(status: str | None) -> bool:
    """True when a ``run_static_checks`` row explicitly satisfies the gate."""
    return status in _REQUIRED_STATIC_CHECK_SATISFIED


def has_failed_required_static_check(static_checks: list[dict[str, str]]) -> bool:
    """True when any required static check row is not explicitly satisfied.

    The terminal-verdict validator consults this for ``approve`` submissions.
    AG0-G4 (a): only ``passed`` and ``not_applicable`` satisfy a required check.
    Every other status — ``failed``, ``unavailable``, ``error``, ``timeout``,
    or unknown — blocks approval.
    """
    return any(not _required_static_check_row_satisfied(row.get("status")) for row in static_checks)


@overload
def decide_approval(
    findings: list[Finding],
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> Conclusion: ...


@overload
def decide_approval(
    findings: MergeEvidencePacket,
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> PacketDecision: ...


def decide_approval(
    findings: Union[list[Finding], MergeEvidencePacket],  # noqa: UP007
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> Union[Conclusion, PacketDecision]:  # noqa: UP007
    """Pure structural approval verdict - finding list or merge-evidence packet (D5, D12-D14, #41).

    The approval gate's wire-shape is a pure function of typed findings, the run's
    completion state, and the trust tier. Narrative (``ApprovalRecord.would_approve``,
    ``result.output``, any model prose) is never an input — the agent's
    ``approved`` boolean is recorded separately as ``SelfAssessment`` on the
    packet (W2.1 / #41) and consulted by the trajectory / merge-evidence work,
    not by this gate.

    Two overloads (D5):

    - **Legacy / security-plan Batch D call sites** (positional ``list[Finding]``):
      returns a ``Conclusion`` literal (``"success"`` / ``"failure"`` /
      ``"neutral"``). ``report_status_checks`` consumes this for the
      ``mergecraft-approval`` check-run.
    - **Merge-evidence packet call sites** (positional ``MergeEvidencePacket``):
      returns a :class:`mergecraft.evidence.packet.Decision` row with
      ``verdict`` / ``reason`` / ``decided_by``. The packet's existing
      ``self_assessment`` row is **advisory only**; if the packet carries an
      explicit ``Decision``, that row is honoured only when ``decided_by`` is
      the trusted decider and the verdict is consistent with typed findings
      (D9 / LR-1 — forged or permissive rows are refused). Otherwise the same
      monotone blocker logic runs against ``packet.findings`` and the result is
      wrapped in a :class:`Decision`.

    The decision is monotone in blockers:

    - Any ``Critical`` or ``Major`` finding ⇒ ``"failure"`` regardless of run
      state or tier. The narrative cannot outvote a blocker.
    - ``run_succeeded=False`` ⇒ ``"neutral"``. A crashed / timed-out run must
      not propagate a permissive outcome; the hardened enforce step blocks on
      ``neutral`` (W8.4 / D13). D3/W5.2 — every ``RunOutcome`` value except
      ``passed`` (``failed``, ``inconclusive``, ``infra_error``,
      ``timed_out``, ``configuration_error``) maps to ``run_succeeded=False``
      here via ``mergecraft.run_outcome.run_succeeded_for_outcome``; this
      function's monotone-in-blockers contract is unchanged; a caller with a
      typed ``RunOutcome`` simply derives the boolean before calling in.
    - ``tier="untrusted"`` ⇒ never ``"success"``. The gate is inert for fork PRs
      and ``pull_request_target`` regardless of ``prApproveEnabled`` and the
      agent's ``approved=True`` (D14). With no blockers the conclusion is
      ``"neutral"``; with a blocker the prior rule wins and yields ``"failure"``.
    - Otherwise (``tier="trusted"`` + ``run_succeeded=True`` + no blockers):
      ``"success"`` when the finding list contains at least one finding
      (attested structural evidence the review ran), ``"neutral"`` when the
      list is empty (the run completed without findings to attest to).

    #41 hard rule, enforced here: when the recorded self-assessment is the only
    positive signal, the verdict is **not** ``auto_merge``. With no findings,
    no passing deterministic checks, ``run_succeeded=True``, and ``tier="trusted"``
    the legacy path yields ``"neutral"``; the packet overload maps that to a
    ``Decision`` whose ``verdict`` is ``"neutral"``. A caller that needs the
    W9 closed-action vocabulary can then derive ``auto_merge`` only after
    further positive evidence (blast-radius lane, trajectory clean, …).

    The function is pure: no I/O, no logging, no module state. The merge-evidence
    plan's W2 (#41) and W9 (#46) call this function without re-shaping; the
    signature is the contract.
    """
    if isinstance(findings, MergeEvidencePacket):
        return _decide_approval_from_packet(findings, run_succeeded=run_succeeded, tier=tier)
    return _decide_approval_from_findings(findings, run_succeeded=run_succeeded, tier=tier)


def _decide_approval_from_findings(
    findings: list[Finding],
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> Conclusion:
    """Legacy structural approval conclusion — typed findings input (D12, D13, D14)."""
    if _has_blocker(findings):
        return "failure"
    if not run_succeeded:
        return "neutral"
    if tier == "untrusted":
        return "neutral"
    if not findings:
        return "neutral"
    return "success"


def _decide_approval_from_packet(
    packet: MergeEvidencePacket,
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> PacketDecision:
    """Packet-aware structural approval decision (#41, W2.2, W2.3).

    Returns a :class:`mergecraft.evidence.packet.Decision` row. When the packet
    carries an explicit ``decision`` row, that row is returned verbatim — the
    structural verdict is authoritative over the agent's recorded
    ``self_assessment``. When the packet does not carry an explicit verdict,
    the legacy blocker logic runs against ``packet.findings`` and the
    ``Conclusion`` literal is wrapped in a ``Decision`` with a stable
    ``decided_by`` and a reason that names the signal the verdict came from.

    The function is pure: no I/O, no logging, no module state.
    """
    # #41 hard rule — if the packet already carries an explicit decision
    # (set by an upstream layer, e.g. a W9 thermostat overlay), honour it
    # only when the row is trusted and consistent with the typed findings.
    # ``MergeEvidencePacket`` validates from dicts; this guard keeps a forged
    # row from becoming a permissive gate input (D9 / LR-1).
    if packet.decision is not None:
        if packet.decision.decided_by != TRUSTED_PACKET_DECIDED_BY:
            msg = (
                f"packet decision refused: decided_by {packet.decision.decided_by!r} "
                f"is not the trusted decider {TRUSTED_PACKET_DECIDED_BY!r}"
            )
            raise ValueError(msg)
        if packet.decision.verdict == "success" and _has_blocker(packet.findings):
            msg = "packet decision refused: blocker finding present; success verdict cannot stand"
            raise ValueError(msg)
        return packet.decision

    conclusion = _decide_approval_from_findings(
        packet.findings, run_succeeded=run_succeeded, tier=tier
    )
    return PacketDecision(
        verdict=conclusion,
        reason=_packet_decision_reason(conclusion, packet),
        decided_by="mergecraft.agents.gates.decide_approval",
    )


def _packet_decision_reason(
    conclusion: Conclusion,
    packet: MergeEvidencePacket,
) -> str:
    """Render a short, evidence-attributed reason for a packet verdict (#41).

    Keeps the reason deterministic and grounded in what the packet actually
    carries, never in the agent's prose. The string is short — the full
    evidence lives in the packet itself and downstream consumers should
    read it from there.
    """
    if packet.self_assessment is not None and packet.self_assessment.approved:
        # The agent said approved; the structural verdict is whatever the
        # evidence proved. Surface both so a human reader can see the
        # disagreement explicitly.
        return (
            f"{conclusion}: structural evidence — agent's self_assessment.approved=true "
            "is advisory only and did not override the verdict"
        )
    if not packet.findings:
        return f"{conclusion}: no typed findings to attest to the review"
    return f"{conclusion}: derived from typed findings and run state"


def approval_decision_inputs(
    findings: list[Finding],
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> dict[str, object]:
    """Return the decision inputs so the check-run summary is reconstructible (#75 proposal item 4).

    Lightweight, dict-only payload — the full evidence packet lives in
    ``src/mergecraft/evidence/packet.py`` (merge-evidence plan's W1). This
    helper exists so the check-run summary lists severities / count / run state /
    tier alongside the conclusion, and a downstream consumer can reproduce the
    ``decide_approval`` decision from the stored summary without re-running the
    analysis path.
    """
    severities = sorted({f.severity for f in findings})
    return {
        "findings_count": len(findings),
        "severities": severities,
        "has_blocker": _has_blocker(findings),
        "run_succeeded": run_succeeded,
        "tier": tier,
    }


def decision_summary_lines(inputs: dict[str, object]) -> list[str]:
    """Render ``approval_decision_inputs`` as human-readable check-run summary lines (W8.6)."""
    findings_count_raw = inputs.get("findings_count", 0)
    findings_count = int(findings_count_raw) if isinstance(findings_count_raw, (int, float)) else 0
    severities_raw = inputs.get("severities") or []
    severities = [str(item) for item in severities_raw] if isinstance(severities_raw, list) else []
    tier_raw = inputs.get("tier", "trusted")
    tier = str(tier_raw) if tier_raw is not None else "trusted"
    run_succeeded = bool(inputs.get("run_succeeded"))
    has_blocker = bool(inputs.get("has_blocker"))
    severities_text = ", ".join(severities) if severities else "(none)"
    return [
        f"- Findings: {findings_count} (severities: {severities_text})",
        f"- Run succeeded: {run_succeeded}",
        f"- Trust tier: {tier}",
        f"- Has blocker: {has_blocker}",
    ]


def log_decision(
    findings: list[Finding],
    *,
    run_succeeded: bool,
    tier: TrustTier,
    conclusion: Conclusion,
) -> None:
    """Log the structural approval decision at info level. Kept separate from
    ``decide_approval`` so the pure function stays side-effect-free."""
    inputs = approval_decision_inputs(findings, run_succeeded=run_succeeded, tier=tier)
    logger.info(
        "approval decision: {} (findings={}, severities={}, run_succeeded={}, tier={})",
        conclusion,
        inputs["findings_count"],
        inputs["severities"],
        run_succeeded,
        tier,
    )


# ── gate-action map (W9.1, #46) ──────────────────────────────────────────────
#
# The thermostat replaces "verdict was typed, now what?" with a closed
# action vocabulary. ``decide_action`` consumes a packet — never re-derives
# evidence — and returns a named action from the seven-value vocabulary.
# It is pure: no I/O, no logging, no module state. The function is the
# single decision point for #46; the run_packet I/O shell is the only
# caller that *applies* the action (enforce mode), and the shadow
# recorder is the only caller that *records* it (shadow mode).


def _has_changed_unread_file(packet: MergeEvidencePacket) -> bool:
    """A trajectory finding flagged a file modified but never read."""
    return any(finding.rule_id == "changed-unread-file" for finding in packet.findings)


def _has_tool_loop(packet: MergeEvidencePacket) -> bool:
    """A trajectory finding flagged a repeated call loop."""
    return any(finding.rule_id == "repeated-tool-loop" for finding in packet.findings)


def _is_high_risk_migration(packet: MergeEvidencePacket) -> bool:
    """A packet whose blast radius lane is ``high`` and is migration-driven."""
    lane = packet.blast_radius.lane if packet.blast_radius else None
    categories = list(packet.blast_radius.categories) if packet.blast_radius else []
    # The plan's example policy is "high-risk migration" — a high-blast
    # radius *with* a migration category. A high-blast radius that is
    # only auth/security/payment would not be a "migration" per the
    # example text, even though it is still "forbidden" by the lane.
    return lane == "high" and "migrations" in categories


def _is_low_risk_passing(packet: MergeEvidencePacket) -> bool:
    """True only for a clean low-risk PR with an explicit positive verdict.

    Requires empty findings, a ``blast_radius.lane`` of ``low``, and a trusted
    ``Decision`` row whose ``verdict`` is ``success``. A missing decision,
    ``neutral``, or ``failure`` verdict never satisfies this predicate — the
    structural approval gate must have attested success before ``auto_merge``
    is eligible (D7 / MCB-15).
    """
    if packet.findings:
        return False
    if not packet.blast_radius:
        return False
    if packet.blast_radius.lane != "low":
        return False
    # The structural verdict must be an explicit positive signal — a missing
    # row, ``neutral``, or ``failure`` must never satisfy ``auto_merge``
    # (D7 / MCB-15). ``run_succeeded`` is not a separate field on the packet;
    # a trusted ``decide_approval`` row only reaches ``success`` when the run
    # completed and the trust tier allows it.
    decision = packet.decision
    if decision is None:
        return False
    return decision.verdict == "success"


# Ordered ``(predicate, rule_id, action)`` rows; first match wins.
# Keys and actions come from ``NAMED_GATE_POLICY_ROWS`` so
# ``DEFAULT_GATE_POLICIES`` cannot drift from this table.
# Catch-all ``schema_failure`` is not listed (see ``select_rule_id``).
# Tests pin ``has_blockers`` before ``changed-unread-file`` / ``tool_loop``.
_PREDICATE_BY_RULE: Final[dict[str, Callable[[MergeEvidencePacket], bool]]] = {
    "high_risk_migration": _is_high_risk_migration,
    "low_risk_passing": _is_low_risk_passing,
    "has_blockers": _packet_has_blockers,
    "changed-unread-file": _has_changed_unread_file,
    "tool_loop": _has_tool_loop,
}
_RULE_PREDICATES: Final[
    tuple[tuple[Callable[[MergeEvidencePacket], bool], str, GateAction], ...]
] = tuple(
    (_PREDICATE_BY_RULE[rule_id], rule_id, action) for rule_id, action in NAMED_GATE_POLICY_ROWS
)


def select_rule_id(packet: MergeEvidencePacket) -> str:
    """Pick the rule key the policy engine should consult for ``packet``.

    Pure: returns the rule id that matches the most specific signal on
    the packet. ``"schema_failure"`` is the catch-all — it matches a
    packet whose evidence is structurally absent.
    """
    for predicate, rule_id, _action in _RULE_PREDICATES:
        if predicate(packet):
            return rule_id
    # Catch-all only — do not also list ``schema_failure`` in the table;
    # that entry never changed the outcome.
    return "schema_failure"


def _validate_policy(policy: GateActionPolicy) -> None:
    """Reject policies whose values are outside the closed action vocabulary.

    A mis-spelled override (``"BANHAMMER"``) must not silently widen the
    gate. The validator runs once per ``decide_action`` call; the cost
    is small and the safety is the whole point of the closed vocabulary.
    """
    for rule_id, action in policy.items():
        if not isinstance(action, GateAction):
            msg = (
                f"gate policy {rule_id!r} maps to {action!r}, which is outside the closed "
                f"action vocabulary {sorted(a.value for a in GateAction)}"
            )
            raise ValueError(msg)


def decide_action(
    packet: MergeEvidencePacket,
    *,
    policy: GateActionPolicy | None = None,
    mode: str = "shadow",
) -> GateAction:
    """Map a packet to one named action from the closed vocabulary (#46, W9.1).

    Pure. The function consumes the packet's evidence — never re-derives
    it — and returns a :class:`GateAction` from the seven-value
    vocabulary. The first step is consulting the policy map; the second
    is selecting the rule key the packet matches. Both are deterministic.

    The six named policies ``DEFAULT_GATE_POLICIES`` ships are
    ``schema_failure``, ``changed-unread-file``, ``has_blockers``,
    ``low_risk_passing``, ``tool_loop``, and ``high_risk_migration``:
    a schema failure blocks, a changed-unread-file asks for changes,
    blockers request changes, a low-risk passing change merges, a
    tool-loop asks for more tests, and a high-risk migration asks for
    human review. Repositories override the mapping at the call site:
    the override is merged on top of the defaults and any value
    outside the closed vocabulary is rejected.

    ``mode`` is not consulted by this function — it is recorded on
    the resulting ``Decision`` row by the I/O shell. The gate's
    behaviour is the same in both modes; the *application* of the
    decision is what ``shadow`` / ``enforce`` controls.
    """
    chosen = policy if policy is not None else DEFAULT_GATE_POLICIES
    _validate_policy(chosen)
    rule_id = select_rule_id(packet)
    action = chosen.get(rule_id)
    if action is None:
        # Surface the gap explicitly rather than fall back to a default
        # — a policy that omits a rule the runner may reach is a policy
        # bug, not a runtime decision.
        msg = f"gate policy is missing the rule {rule_id!r} for this packet"
        raise KeyError(msg)
    # ``mode`` is consulted for shape only; the function's behaviour is
    # the same in both modes. The unused-variable guard here keeps the
    # typed signature honest.
    if mode not in {"shadow", "enforce"}:
        msg = f"unknown gate mode {mode!r} (expected 'shadow' or 'enforce')"
        raise ValueError(msg)
    return action


__all__ = [
    "BLOCKING_SEVERITIES",
    "GateAction",
    "approval_decision_inputs",
    "build_claude_native_fs_denies",
    "build_opencode_native_fs_permission",
    "decide_action",
    "decide_approval",
    "decision_summary_lines",
    "has_failed_required_static_check",
    "log_decision",
    "select_rule_id",
    "subagent_denied_tool_names",
]
