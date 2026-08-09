"""Subagent mutates deny + native FS denies (ported from subagentToolGates / nativeFsDenies)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from loguru import logger

from mergecraft.mcp.server import build_orchestrator_tools

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import JsonSchema
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


def subagent_denied_tool_names(
    ctx: ToolContext,
    output_schema: JsonSchema | None = None,
) -> list[str]:
    """Canonical bare names of every state-mutating MCP tool for this run."""
    names = [t.name for t in build_orchestrator_tools(ctx, output_schema) if t.mutates]
    if not names:
        msg = (
            "subagent deny list derived empty — no MCP tool is marked mutates=True. "
            "refusing to start with the subagent gate effectively disabled."
        )
        raise RuntimeError(msg)
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


def decide_approval(
    findings: list[Finding],
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> Conclusion:
    """Pure structural approval conclusion (D12, D13, D14).

    The approval gate's wire-shape (``success`` / ``failure`` / ``neutral``) is a
    pure function of the typed finding list, the run's completion state, and the
    trust tier. Narrative (``ApprovalRecord.would_approve``, ``result.output``,
    any model prose) is never an input — the agent's ``approved`` boolean is
    recorded separately (W8.3) and consumed by the trajectory/evidence work in
    the merge-evidence plan (#41) after the fact.

    The decision is monotone in blockers:

    - Any ``Critical`` or ``Major`` finding ⇒ ``"failure"`` regardless of run
      state or tier. The narrative cannot outvote a blocker.
    - ``run_succeeded=False`` ⇒ ``"neutral"``. A crashed / timed-out run must
      not propagate a permissive outcome; the hardened enforce step blocks on
      ``neutral`` (W8.4 / D13).
    - ``tier="untrusted"`` ⇒ never ``"success"``. The gate is inert for fork PRs
      and ``pull_request_target`` regardless of ``prApproveEnabled`` and the
      agent's ``approved=True`` (D14). With no blockers the conclusion is
      ``"neutral"``; with a blocker the prior rule wins and yields ``"failure"``.
    - Otherwise (``tier="trusted"`` + ``run_succeeded=True`` + no blockers):
      ``"success"`` when the finding list contains at least one finding
      (attested structural evidence the review ran), ``"neutral"`` when the
      list is empty (the run completed without findings to attest to).

    The function is pure: no I/O, no logging, no module state. The merge-evidence
    plan's W2 (D12) and W9 (#46) call this function without re-shaping; the
    signature is the contract.
    """
    if _has_blocker(findings):
        return "failure"
    if not run_succeeded:
        return "neutral"
    if tier == "untrusted":
        return "neutral"
    if not findings:
        return "neutral"
    return "success"


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


__all__ = [
    "BLOCKING_SEVERITIES",
    "approval_decision_inputs",
    "build_claude_native_fs_denies",
    "build_opencode_native_fs_permission",
    "decide_approval",
    "decision_summary_lines",
    "log_decision",
    "subagent_denied_tool_names",
]
