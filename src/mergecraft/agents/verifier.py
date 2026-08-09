"""Read-only verification subagent for review findings (D11, C6).

The gate decides which findings earn a second opinion and builds the brief the
``mergecraft-verifier`` subagent receives. Analyzer and CI findings have been
routed through it since D11 — but the findings the reviewing model wrote itself
never were, and those are the ones most likely to be wrong: ``should_verify()``
was always severity-only, and the source condition lived in its two call sites
(``analyzers/review_gate.py``, ``ci/verification.py``), both of which only ever
fed it tool output.

``plan_agent_verifications`` closes that gap on the same terms as the analyzer
path: it queues agent-authored ``Critical``/``Major`` findings, skips any whose
fingerprint is already refuted under ``WITHDRAWN_FINDINGS_HEADING``, and caps
dispatches at the run's inline budget so verification cannot cost more than
publication. ``record_verifier_verdict`` routes a ``drop`` back into that same
withdrawn memory, so a refuted finding stays refuted.

Exports:
    AgentFinding: One agent-authored finding as the reviewer drafted it.
    JudgeVerdict: One verifier verdict about a finding.
    VerdictOutcome: What recording a verdict did.
    VerificationDispatch / VerificationPlan: The budgeted dispatch queue.
    build_verifier_brief: Compose one dispatch prompt.
    plan_agent_verifications: Queue agent findings for verification (C6).
    record_verifier_verdict: Route a verdict, withdrawing dropped findings.
    record_withdrawn_finding: Append a refutation to the learnings file.
    should_verify: Severity gate shared with the analyzer and CI call sites.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.analyzers.scope import withdrawn_fingerprints
from mergecraft.review_taxonomy import (
    FINDING_SEVERITIES,
    WITHDRAWN_FINDINGS_HEADING,
    finding_fingerprint,
)
from mergecraft.types import VERIFIER_AGENT_NAME

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext

__all__ = [
    "VERIFIER_AGENT_NAME",
    "VERIFIER_SEVERITIES",
    "VERIFIER_SYSTEM_PROMPT",
    "AgentFinding",
    "JudgeVerdict",
    "VerdictOutcome",
    "VerificationDispatch",
    "VerificationPlan",
    "build_verifier_brief",
    "plan_agent_verifications",
    "record_verifier_verdict",
    "record_withdrawn_finding",
    "should_verify",
    "verifier_denied_tool_names",
]

VERIFIER_SEVERITIES: Final[frozenset[str]] = frozenset({"Critical", "Major"})

VERIFIER_SYSTEM_PROMPT = (
    "You are a read-only verification subagent. Your role is to evaluate one "
    "finding — analyzer-sourced, CI-sourced, or written by the reviewing agent "
    "itself — before it is published in a pull request review.\n\n"
    "HARD CONSTRAINTS (non-negotiable):\n"
    "- Read-only tools only. Do NOT write or edit files, commit, push, or call any "
    "state-changing MCP tool.\n"
    "- Do NOT spawn further subagents.\n"
    "- Read the cited file and surrounding context; trace reachability; check config; "
    "confirm the pull request plausibly introduced the issue.\n"
    "- Return exactly one of: **confirm** (with a one-paragraph explanation), "
    "**downgrade** (with new severity and reason), or **drop** (with a reason the "
    "orchestrator can record as a withdrawn finding).\n"
    "- Treat the finding as a hypothesis until you have read the code.\n"
)


def verifier_denied_tool_names(
    ctx: ToolContext,
    output_schema: object | None = None,
) -> list[str]:
    """Canonical bare names of every state-mutating MCP tool for the verifier."""
    return subagent_denied_tool_names(ctx, output_schema)  # type: ignore[arg-type]


def should_verify(finding: Finding) -> bool:
    """Only Critical and Major analyzer findings reach verification (D11)."""
    return finding.severity in VERIFIER_SEVERITIES


class AgentFinding(BaseModel):
    """One agent-authored finding as the reviewing agent drafted it.

    This is the wire shape the reviewer hands to ``verify_agent_findings``
    before it publishes anything, so it mirrors an inline comment rather than
    a normalized ``Finding``: the agent has a path, a body and a grade at this
    point, not a tool or a rule id.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    body: str
    severity: str
    line: int | None = None
    fingerprint: str = ""

    def identity(self) -> str:
        """Return this finding's fingerprint, deriving one when absent.

        Derivation matches ``budget._overflow_fingerprint`` and
        ``mcp/review.stamp_finding_fingerprint`` — ``path`` plus the comment
        body — so the identity used to skip an already-withdrawn finding is
        the same identity a drop verdict writes and a later run reads back.
        """
        supplied = self.fingerprint.strip()
        return supplied or finding_fingerprint(path=self.path, body=self.body)


class VerificationDispatch(BaseModel):
    """One agent finding queued for the ``mergecraft-verifier`` subagent."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    finding: AgentFinding
    cited_file: str | None
    brief: str


class VerificationPlan(BaseModel):
    """What the reviewer should dispatch, and what was skipped and why."""

    model_config = ConfigDict(extra="forbid")

    budget: int
    dispatch: list[VerificationDispatch]
    skipped_withdrawn: list[str]
    skipped_over_budget: list[str]
    skipped_below_severity: list[str]


def _severity_rank(severity: str) -> int:
    try:
        return FINDING_SEVERITIES.index(severity)
    except ValueError:
        return len(FINDING_SEVERITIES)


def _withdrawn_section(learnings_text: str) -> str:
    """Return the withdrawn-findings section verbatim, or an empty string."""
    if WITHDRAWN_FINDINGS_HEADING not in learnings_text:
        return ""
    section = learnings_text.split(WITHDRAWN_FINDINGS_HEADING, 1)[1]
    next_heading = re.search(r"\n## ", section)
    if next_heading:
        section = section[: next_heading.start()]
    return f"{WITHDRAWN_FINDINGS_HEADING}\n{section}".rstrip()


def build_verifier_brief(
    finding: AgentFinding,
    *,
    cited_file: str | None,
    withdrawn_section: str,
) -> str:
    """Compose the dispatch prompt for one agent-authored finding (C6)."""
    anchor = f"{finding.path}:{finding.line}" if finding.line else finding.path
    parts = [
        f"Verify one finding the reviewing agent wrote about `{anchor}` and graded "
        f"**{finding.severity}**. It is a hypothesis until you have read the code.",
        "",
        "### Finding",
        "",
        finding.body.strip(),
        "",
        "### Cited file",
        "",
        cited_file or f"`{finding.path}` — not present in the checkout; that alone is a **drop**.",
        "",
        f"### {WITHDRAWN_FINDINGS_HEADING.removeprefix('## ')}",
        "",
        withdrawn_section or "No findings have been withdrawn on this repository yet.",
        "",
        "Cite the code you read, then return exactly one of confirm / downgrade / drop.",
    ]
    return "\n".join(parts)


def plan_agent_verifications(
    findings: Sequence[AgentFinding],
    *,
    budget: int,
    learnings_text: str = "",
    repo_root: Path | None = None,
) -> VerificationPlan:
    """Queue agent-authored Critical/Major findings for verification (C6).

    Three filters run in order, and the order matters: severity first (a
    ``Minor`` finding never earns a dispatch), then the withdrawn memory (a
    finding the author already refuted must not be re-verified, let alone
    re-raised), then the budget — so the cap is spent on the worst findings
    that are still live rather than on ones already known to be dead.

    Args:
        findings: The agent's drafted findings, pre-publication.
        budget: Maximum dispatches for this run — the repo's ``inlineBudget``.
            Verification cannot cost more than publication; there is no second
            knob.
        learnings_text: The learnings file contents, read for its
            ``WITHDRAWN_FINDINGS_HEADING`` section.
        repo_root: Checkout root, used to resolve each finding's cited file.

    Returns:
        A ``VerificationPlan`` naming what to dispatch and what was skipped.
    """
    withdrawn = withdrawn_fingerprints(learnings_text)
    section = _withdrawn_section(learnings_text)

    eligible: list[tuple[str, AgentFinding]] = []
    skipped_withdrawn: list[str] = []
    skipped_below_severity: list[str] = []
    for finding in findings:
        identity = finding.identity()
        if finding.severity not in VERIFIER_SEVERITIES:
            skipped_below_severity.append(identity)
            continue
        if identity in withdrawn:
            skipped_withdrawn.append(identity)
            continue
        eligible.append((identity, finding))

    eligible.sort(key=lambda item: (_severity_rank(item[1].severity), item[1].path, item[0]))
    capped = eligible[: max(budget, 0)]
    over_budget = [identity for identity, _ in eligible[max(budget, 0) :]]

    dispatch: list[VerificationDispatch] = []
    for identity, finding in capped:
        cited: str | None = None
        if repo_root is not None and finding.path:
            candidate = repo_root / finding.path
            if candidate.is_file():
                cited = str(candidate)
        dispatch.append(
            VerificationDispatch(
                fingerprint=identity,
                finding=finding,
                cited_file=cited,
                brief=build_verifier_brief(finding, cited_file=cited, withdrawn_section=section),
            )
        )

    return VerificationPlan(
        budget=max(budget, 0),
        dispatch=dispatch,
        skipped_withdrawn=skipped_withdrawn,
        skipped_over_budget=over_budget,
        skipped_below_severity=skipped_below_severity,
    )


# ── verdicts (D11) ────────────────────────────────────────────────────────────

JudgeVerdictName = Literal["confirm", "downgrade", "drop"]


class JudgeVerdict(BaseModel):
    """One verifier verdict about a finding."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    verdict: JudgeVerdictName
    reason: str
    new_severity: str | None = None


class VerdictOutcome(BaseModel):
    """What recording a verdict actually did."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    verdict: JudgeVerdictName
    recorded_withdrawn: bool
    publishable: bool
    reason: str


def record_withdrawn_finding(
    *,
    learnings_path: Path,
    reason: str,
    fingerprint: str,
) -> None:
    """Append a withdrawn-finding reason under ``WITHDRAWN_FINDINGS_HEADING`` (D11)."""
    text = learnings_path.read_text(encoding="utf-8") if learnings_path.is_file() else ""
    marker = f"<!-- mergecraft-finding:v1:{fingerprint} -->"
    bullet = f"- {reason.strip()} {marker}".strip()
    if WITHDRAWN_FINDINGS_HEADING in text:
        updated = text.rstrip() + f"\n{bullet}\n"
    else:
        heading = f"{WITHDRAWN_FINDINGS_HEADING}\n\n"
        updated = (
            text.rstrip() + f"\n\n{heading}{bullet}\n" if text.strip() else f"{heading}{bullet}\n"
        )
    learnings_path.parent.mkdir(parents=True, exist_ok=True)
    learnings_path.write_text(updated, encoding="utf-8")


def record_verifier_verdict(
    verdict: JudgeVerdict,
    *,
    learnings_path: Path,
) -> VerdictOutcome:
    """Route a verdict, writing a ``drop`` into the withdrawn memory (C6).

    Args:
        verdict: The verifier's verdict about one finding.
        learnings_path: The run's learnings file, where refutations accumulate.

    Returns:
        A ``VerdictOutcome`` saying whether the finding may still be published
        and whether the refutation was durably recorded.
    """
    logger.info("verifier verdict: {} on {}", verdict.verdict, verdict.fingerprint)

    if verdict.verdict != "drop":
        return VerdictOutcome(
            fingerprint=verdict.fingerprint,
            verdict=verdict.verdict,
            recorded_withdrawn=False,
            publishable=True,
            reason=verdict.reason,
        )

    record_withdrawn_finding(
        learnings_path=learnings_path,
        reason=verdict.reason,
        fingerprint=verdict.fingerprint,
    )
    return VerdictOutcome(
        fingerprint=verdict.fingerprint,
        verdict=verdict.verdict,
        recorded_withdrawn=True,
        publishable=False,
        reason=verdict.reason,
    )


def withdrawn_fingerprint_for_reason(reason: str) -> str:
    """Stable fingerprint input for a withdrawn-finding bullet."""
    return finding_fingerprint(path="", body=reason)
