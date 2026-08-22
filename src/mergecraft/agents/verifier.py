"""Read-only verification subagent for review findings (D11, D14).

Two contracts live here.

**The gate (D11, C6)** decides which findings earn a second opinion and
builds the brief the ``mergecraft-verifier`` subagent receives. Analyzer and
CI findings have been routed through it since D11 — but the findings the
reviewing model wrote itself never were, and those are the ones most likely
to be wrong. ``plan_agent_verifications`` closes that gap: it queues
agent-authored ``Critical``/``Major`` findings, skips any whose fingerprint
is already refuted under ``WITHDRAWN_FINDINGS_HEADING``, and caps dispatches
at the repo's ``review.verificationBudget`` (independent of inline placement).

**The judge contract (D14, #45)** treats the verifier as what it is — an LLM
judge, and therefore a *secondary* signal. Its model, provider, judge version
and rubric version are pinned and recorded with every verdict; its rubric is
a list of binary observable outcomes rather than a "quality" score; it never
runs before the deterministic checks it supplements; and on a high-stakes
lane a single judge may not retire a finding on its own.

Exports:
    AgentFinding: One agent-authored finding as the reviewer drafted it.
    HIGH_STAKES_LANES: Lanes where one judge cannot dispose of a finding.
    JudgePin: The pinned identity of the judge that produced a verdict.
    JudgeVerdict: One recorded verdict, pin and deterministic evidence included.
    VERIFIER_RUBRIC: The outcome-based criteria the judge answers.
    VerdictOutcome: What recording a verdict did.
    VerificationDispatch / VerificationPlan: The budgeted dispatch queue.
    judge_pin: Resolve the pinned judge identity for a provider.
    log_judge_verdict: Emit the judge-verdict log line (#45).
    plan_agent_verifications: Queue agent findings for verification (C6).
    record_verifier_verdict: Route a verdict, withdrawing dropped findings.
    record_withdrawn_finding: Append a refutation to the learnings file.
    should_verify: Severity gate shared with the analyzer and CI call sites.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal, cast

from loguru import logger
from pydantic import BaseModel, ConfigDict, model_validator

from mergecraft.analyzers.scope import withdrawn_fingerprints
from mergecraft.mcp.shared import VERIFIER_ALLOWED_TOOL_CLASSES
from mergecraft.policy.schema import SeverityLiteral
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
    "HIGH_STAKES_LANES",
    "VERIFIER_AGENT_NAME",
    "VERIFIER_JUDGE_VERSION",
    "VERIFIER_RUBRIC",
    "VERIFIER_RUBRIC_VERSION",
    "VERIFIER_SEVERITIES",
    "VERIFIER_SYSTEM_PROMPT",
    "AgentFinding",
    "JudgePin",
    "JudgeVerdict",
    "VerdictOutcome",
    "VerificationDispatch",
    "VerificationPlan",
    "judge_pin",
    "log_judge_verdict",
    "pinned_judge_model",
    "plan_agent_verifications",
    "record_verifier_verdict",
    "record_withdrawn_finding",
    "should_verify",
    "verifier_denied_tool_names",
]

# ── judge pin (D14 / #45) ─────────────────────────────────────────────────────

# Bumped when the verifier's system prompt or dispatch brief changes shape, so
# an archived verdict can be read against the contract that produced it.
VERIFIER_JUDGE_VERSION: Final[str] = "1.1.0"

# Bumped whenever VERIFIER_RUBRIC changes. Verdicts carry it so a rubric edit
# never silently reinterprets old judgements.
VERIFIER_RUBRIC_VERSION: Final[str] = "1.0.0"

# Each criterion is a binary, observable outcome about the code — never a
# score for "quality", style, or how much the diff says. A judge that cannot
# answer one of these from the code it read must not confirm the finding.
VERIFIER_RUBRIC: Final[tuple[tuple[str, str], ...]] = (
    ("cited-code-exists", "The cited file, symbol and line range exist at the reviewed commit."),
    ("mechanism-holds", "A concrete input or call sequence makes the described failure happen."),
    ("reachable", "That sequence is reachable from a caller in this repository."),
    ("introduced-here", "Lines this pull request added or modified introduce or amplify it."),
    ("not-already-refuted", "No withdrawn-findings entry already refutes this finding."),
)

# Judges are pinned per provider so a model default drifting under the Action
# cannot silently change what gets published. ``claude`` pins Sonnet — a
# different family from the Opus-class orchestrator, per #45. Providers absent
# here run the judge on the run's own model; the verdict records that the model
# was not pinned rather than pretending otherwise.
PINNED_JUDGE_MODELS: Final[dict[str, str]] = {"claude": "claude-sonnet-5"}

# Lanes where one LLM judge is not enough to retire a finding (D14). A ``drop``
# here is recorded and escalated, never written to the withdrawn section — the
# blast radius is exactly where a wrong retraction costs the most.
HIGH_STAKES_LANES: Final[frozenset[str]] = frozenset({"high"})

# ── verification gate (D11 / C6) ──────────────────────────────────────────────

VERIFIER_SEVERITIES: Final[frozenset[str]] = frozenset({"Critical", "Major"})

VERIFIER_SYSTEM_PROMPT = (
    "You are a read-only verification subagent. Your role is to evaluate one "
    "finding — analyzer-sourced, CI-sourced, or written by the reviewing agent "
    "itself — before it is published in a pull request review.\n\n"
    "You are a SECONDARY signal. Deterministic checks (analyzers, static gates, "
    "tests) have already run and settled every mechanically checkable fact; do "
    "not re-litigate their output, and never overrule a tool result with an "
    "opinion.\n\n"
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
    "- Actively search for reasons the finding may be wrong (falsification-first); "
    "do not confirm from narrative alone.\n\n"
    f"RUBRIC v{VERIFIER_RUBRIC_VERSION} — answer each with yes/no and cite the code "
    "you read. Do not score style, tone, or verbosity:\n"
    + "".join(f"- **{key}** — {text}\n" for key, text in VERIFIER_RUBRIC)
    + "\nAll five yes → confirm. `cited-code-exists`, `mechanism-holds` or "
    "`reachable` no → drop. `introduced-here` no → downgrade (pre-existing, not "
    "this pull request's). `not-already-refuted` no → drop, citing the entry.\n"
)


def verifier_denied_tool_names(
    ctx: ToolContext,
    output_schema: object | None = None,
) -> list[str]:
    """Canonical bare names denied to the verifier (H4 — independent complement)."""
    from mergecraft.agents.gates import _denied_tool_names_for_allowed_classes

    return _denied_tool_names_for_allowed_classes(
        ctx,
        VERIFIER_ALLOWED_TOOL_CLASSES,
        role="verifier",
        output_schema=output_schema,  # type: ignore[arg-type]  # — output_schema is dict[str, Any] | None; callee accepts None-narrowed variant
    )


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
        "Answer every rubric criterion, then return exactly one of confirm / downgrade / drop.",
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
        budget: Maximum dispatches for this run — the repo's
            ``review.verificationBudget`` (default 24). ``0`` means no cap.
            Verification depth is costed separately from ``analyzers.inlineBudget``
            so a placement knob cannot silently decide publishability (RC3, D2).
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
    if budget == 0:
        capped = eligible
        over_budget: list[str] = []
    else:
        capped = eligible[:budget]
        over_budget = [identity for identity, _ in eligible[budget:]]

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
        budget=budget,
        dispatch=dispatch,
        skipped_withdrawn=skipped_withdrawn,
        skipped_over_budget=over_budget,
        skipped_below_severity=skipped_below_severity,
    )


# ── verdicts (D11 / D14) ──────────────────────────────────────────────────────

JudgeVerdictName = Literal["confirm", "downgrade", "drop"]
# One vocabulary, two views of it: the policy schema's ``Literal`` for typing and
# ``FINDING_SEVERITIES`` for the values. Minting a twin here is how the four
# grades come to disagree.
JudgeSeverity = SeverityLiteral
# cast: `FINDING_SEVERITIES` is the same four values typed `tuple[str, ...]`, and
# narrowing it here is what keeps them one vocabulary instead of two.
JUDGE_SEVERITIES: tuple[JudgeSeverity, ...] = cast("tuple[JudgeSeverity, ...]", FINDING_SEVERITIES)
DOWNGRADE_SEVERITY_REQUIRED = (
    "a downgrade verdict must name new_severity — the severity it downgrades to "
    "is the verdict, and defaulting it silently retires findings the approve gate holds"
)


class JudgePin(BaseModel):
    """The pinned identity of the judge that produced a verdict (#45)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    model_pinned: bool
    judge_version: str = VERIFIER_JUDGE_VERSION
    rubric_version: str = VERIFIER_RUBRIC_VERSION


class JudgeVerdict(BaseModel):
    """One verdict, recorded with the pin and the evidence that preceded it."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    verdict: JudgeVerdictName
    reason: str
    pin: JudgePin
    # Names of the deterministic checks that ran before this judge did. Empty
    # is a contract violation, not a default — see ``record_verifier_verdict``.
    deterministic_checks: list[str] = []
    new_severity: JudgeSeverity | None = None
    lane: str | None = None

    @model_validator(mode="after")
    def _require_severity_on_downgrade(self) -> JudgeVerdict:
        """Refuse a ``downgrade`` that names no replacement severity.

        A downgrade with no severity used to fall back to ``Minor`` at the call
        site, so one call retired any Critical the approve gate was holding.
        The severity a downgrade rewrites *to* is the whole content of the
        verdict — absent, there is no verdict to record.
        """
        if self.verdict == "downgrade" and self.new_severity is None:
            raise ValueError(DOWNGRADE_SEVERITY_REQUIRED)
        return self

    @staticmethod
    def parse_severity(raw: object) -> JudgeSeverity | None:
        """Read an untyped ``new_severity`` argument as a judge severity.

        Returns ``None`` for an absent or empty value — the model validator is
        what decides whether that is allowed for this verdict.

        Raises:
            ValueError: when a value is present but not one of the four.
        """
        if raw is None or raw == "":
            return None
        text = str(raw)
        for candidate in JUDGE_SEVERITIES:
            if text == candidate:
                return candidate
        msg = f"new_severity {text!r} is not one of {', '.join(JUDGE_SEVERITIES)}."
        raise ValueError(msg)

    @property
    def downgrade_severity(self) -> JudgeSeverity:
        """The severity this ``downgrade`` rewrites to.

        Raises:
            ValueError: If the verdict carries no ``new_severity`` — the
                constructor already refuses that, so this is the typed accessor
                rather than a second policy.
        """
        if self.new_severity is None:
            raise ValueError(DOWNGRADE_SEVERITY_REQUIRED)
        return self.new_severity


class VerdictOutcome(BaseModel):
    """What recording a verdict actually did."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    verdict: JudgeVerdictName
    recorded_withdrawn: bool
    publishable: bool
    escalated_to_human: bool
    reason: str


def pinned_judge_model(provider: str) -> str | None:
    """Return the pinned judge model for ``provider``, or ``None`` if unpinned."""
    return PINNED_JUDGE_MODELS.get(provider)


def judge_pin(*, provider: str, resolved_model: str | None = None) -> JudgePin:
    """Resolve the judge identity to record with a verdict (#45).

    A provider without a pin still yields a complete pin record — with
    ``model_pinned=False`` and the run's own model — because an unpinned judge
    is a fact worth logging, not a reason to log nothing.
    """
    pinned = pinned_judge_model(provider)
    return JudgePin(
        provider=provider,
        model=pinned or (resolved_model or "unknown"),
        model_pinned=pinned is not None,
    )


def log_judge_verdict(verdict: JudgeVerdict) -> None:
    """Log judge model, provider, judge version and rubric version (#45)."""
    logger.info(
        "judge verdict: {} on {} | provider={} model={} pinned={} "
        "judge_version={} rubric_version={} lane={} deterministic_checks={}",
        verdict.verdict,
        verdict.fingerprint,
        verdict.pin.provider,
        verdict.pin.model,
        verdict.pin.model_pinned,
        verdict.pin.judge_version,
        verdict.pin.rubric_version,
        verdict.lane or "unknown",
        ",".join(verdict.deterministic_checks) or "none",
    )


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
    """Log a verdict and route a ``drop`` into the withdrawn memory (C6, D14).

    Args:
        verdict: The judge's verdict, carrying its pin and the deterministic
            checks that preceded it.
        learnings_path: The run's learnings file, where refutations accumulate.

    Returns:
        A ``VerdictOutcome`` saying whether the finding may still be published
        and whether the refutation was durably recorded.

    Raises:
        ValueError: If no deterministic check ran before the judge (D14) — an
            LLM judge is a secondary signal, so a verdict with nothing to be
            secondary to is refused rather than quietly accepted.
    """
    if not verdict.deterministic_checks:
        msg = (
            "judge verdict rejected: no deterministic check ran before it. LLM judges "
            "are secondary evaluators — run the repo's analyzers or static gates first "
            "(D14, #45)."
        )
        raise ValueError(msg)

    log_judge_verdict(verdict)

    if verdict.verdict != "drop":
        return VerdictOutcome(
            fingerprint=verdict.fingerprint,
            verdict=verdict.verdict,
            recorded_withdrawn=False,
            publishable=True,
            escalated_to_human=False,
            reason=verdict.reason,
        )

    if (verdict.lane or "") in HIGH_STAKES_LANES:
        logger.warning(
            "judge drop on high-stakes lane {} not auto-withdrawn — finding {} needs a "
            "second judge or human review (D14)",
            verdict.lane,
            verdict.fingerprint,
        )
        return VerdictOutcome(
            fingerprint=verdict.fingerprint,
            verdict=verdict.verdict,
            recorded_withdrawn=False,
            publishable=True,
            escalated_to_human=True,
            reason=(
                f"drop withheld on high-stakes lane `{verdict.lane}` — one judge cannot "
                f"retire a finding here; escalate to a second judge or a human. "
                f"Judge reason: {verdict.reason}"
            ),
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
        escalated_to_human=False,
        reason=verdict.reason,
    )


def withdrawn_fingerprint_for_reason(reason: str) -> str:
    """Stable fingerprint input for a withdrawn-finding bullet."""
    return finding_fingerprint(path="", body=reason)
