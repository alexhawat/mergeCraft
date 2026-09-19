"""Parallel Jev judge: evidence-check + prose claim battery (D11, G10-G12).

Runs beside the existing LLM verifier, never instead of it. Findings this
module emits are ``scope="run"`` and attesting — they never block a merge
(D6). Judge-vs-judge disagreement is a signal, not a gate (J4.5).

Exports:
    JEV_JUDGE_VERSION: Judge-contract version recorded on ``JevJudgePin``.
    JEV_RUBRIC_VERSION: Rubric version recorded on ``JevJudgePin``.
    JevJudgePin: Registered pin carrying ``jev-1.13.0`` (D11).
    EvidenceJudgeResult: One ``evidence/v1`` outcome.
    ClaimJudgeResult: Aggregated ``claim/v1`` outcome.
    ParallelJudgeResult: Combined parallel-judge run.
    JudgeDisagreement: Signal-only verifier/Jev disagreement.
    judge_finding_evidence: Citation-check one finding.
    judge_prose_claims: Claim battery over extracted prose.
    run_parallel_judge: Evidence + claims beside ``should_verify``.
    record_parallel_judge: Persist the parallel result through the shadow recorder.
    record_judge_disagreement: Record disagreement as a signal.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Final, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from mergecraft.agents.verifier import JudgePin, pinned_judge_model
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.jev.claims import extract_claims
from mergecraft.jev.policy import bucket_confidence
from mergecraft.jev.questions import claim_pack, evidence_pack
from mergecraft.jev.types import (
    CLAIM_PACK_ID,
    EVIDENCE_PACK_ID,
    PINNED_MODEL,
    ChoiceAnswer,
    JevError,
    NoulAnswer,
    SystemOneResponse,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.jev.client import AsyncJevClient

JEV_JUDGE_VERSION: Final[str] = "1.0.0"
JEV_RUBRIC_VERSION: Final[str] = "1.0.0"
_JEV_PROVIDER: Final[str] = "jev"
_ACT_FLOOR: Final[float] = 0.5
_TOOL: Final[str] = "jev-judge"
_CATEGORY: Final[str] = "Maintainability & Code Quality"


class JevJudgePin(JudgePin):
    """Pinned Jev judge identity. Parallel to the LLM verifier (D11, G11)."""

    provider: str = _JEV_PROVIDER
    model: str = PINNED_MODEL
    model_pinned: bool = True
    judge_version: str = JEV_JUDGE_VERSION
    rubric_version: str = JEV_RUBRIC_VERSION


class EvidenceJudgeResult(BaseModel):
    """One ``evidence/v1`` battery. Attesting, never blocking (D6)."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str = EVIDENCE_PACK_ID
    relation: str
    falsifiable: float = 0.0
    located: float = 0.0
    scope: Literal["run"] = "run"
    blocking: bool = False
    skipped: bool = False
    reason: str | None = None
    pin: JevJudgePin = Field(default_factory=JevJudgePin)
    findings: list[Finding] = Field(default_factory=list)


class ClaimJudgeResult(BaseModel):
    """Aggregated ``claim/v1`` battery. Attesting, never blocking (D6)."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str = CLAIM_PACK_ID
    backed_by_row: float = 0.0
    blocking_language: float = 0.0
    contradicts_verdict: float = 0.0
    scope: Literal["run"] = "run"
    blocking: bool = False
    skipped: bool = False
    reason: str | None = None
    pin: JevJudgePin = Field(default_factory=JevJudgePin)
    findings: list[Finding] = Field(default_factory=list)


class ParallelJudgeResult(BaseModel):
    """Evidence + claim batteries run beside the verifier, never instead."""

    model_config = ConfigDict(extra="forbid")

    replaces_verifier: bool = False
    mode: Literal["parallel"] = "parallel"
    evidence: list[EvidenceJudgeResult] = Field(default_factory=list)
    claims: ClaimJudgeResult | None = None
    pin: JevJudgePin = Field(default_factory=JevJudgePin)
    findings: list[Finding] = Field(default_factory=list)


class JudgeDisagreement(BaseModel):
    """Verifier vs Jev disagreement — a signal for plan 25, never a gate."""

    model_config = ConfigDict(extra="forbid")

    signal: bool = True
    gate: bool = False
    fingerprint: str
    jev_verdict: str
    verifier_verdict: str


def _registered_pin() -> JevJudgePin:
    pinned = pinned_judge_model(_JEV_PROVIDER) or PINNED_MODEL
    return JevJudgePin(model=pinned, model_pinned=pinned == PINNED_MODEL)


async def judge_finding_evidence(
    finding: Finding,
    *,
    cited_section: str,
    client: AsyncJevClient,
) -> EvidenceJudgeResult:
    """Run ``evidence/v1`` over one finding (T12 citation-check).

    Args:
        finding: Review finding whose claim is checked against cited code.
        cited_section: Code the finding quoted as evidence.
        client: Pinned Jev client (recorded transport in CI).

    Returns:
        EvidenceJudgeResult: Relation plus attesting ``scope="run"`` findings,
        or a skip result when the client does not dispatch (D4).
    """
    pack = evidence_pack()
    pin = _registered_pin()
    result = await client.call(
        state={
            "claim": finding.message,
            "section": cited_section,
            "path": finding.path,
            "start_line": finding.start_line,
            "end_line": finding.end_line,
        },
        pack_id=pack.pack_id,
        unit_id=finding.fingerprint or finding.path or "finding",
        questions=pack.as_system_one(),
    )
    if result.skipped or result.response is None:
        return EvidenceJudgeResult(
            pack_id=pack.pack_id,
            relation="",
            skipped=True,
            reason=result.reason,
            pin=pin,
        )
    response = result.response
    relation = _choice(response, "relation")
    falsifiable = _noul(response, "falsifiable")
    located = _noul(response, "located")
    attestations: list[Finding] = []
    if relation in {"says_nothing", "contradicts"}:
        attestations.append(
            _attest(
                rule_id="jev-evidence-unsupported",
                message=(f"Finding is not supported by the cited code (relation={relation})"),
                path=finding.path,
                confidence=_choice_confidence(response, "relation"),
            )
        )
    return EvidenceJudgeResult(
        pack_id=pack.pack_id,
        relation=relation,
        falsifiable=falsifiable,
        located=located,
        scope="run",
        blocking=False,
        pin=pin,
        findings=attestations,
    )


async def judge_prose_claims(
    review_body: str,
    *,
    findings: Sequence[Finding],
    client: AsyncJevClient,
) -> ClaimJudgeResult:
    """Run ``claim/v1`` once per extracted prose claim (D12, plan 21 D6 1/3/4).

    Args:
        review_body: Rendered review Markdown.
        findings: Structured findings rows (may be empty).
        client: Pinned Jev client (recorded transport in CI).

    Returns:
        ClaimJudgeResult: Aggregated nouls plus attesting run findings,
        or a skip result when the client does not dispatch (D4).
    """
    pack = claim_pack()
    pin = _registered_pin()
    claims = extract_claims(review_body)
    table = _render_findings_table(findings)
    verdict = _stated_terminal_verdict(review_body)
    backed: list[float] = []
    blocking: list[float] = []
    contradicts: list[float] = []
    attestations: list[Finding] = []

    for claim in claims:
        result = await client.call(
            state={
                "claim": claim.text,
                "findings_table": table,
                "terminal_verdict": verdict,
            },
            pack_id=pack.pack_id,
            unit_id=_claim_unit_id(claim.text),
            questions=pack.as_system_one(),
        )
        if result.skipped or result.response is None:
            return ClaimJudgeResult(
                pack_id=pack.pack_id,
                skipped=True,
                reason=result.reason,
                pin=pin,
            )
        response = result.response
        backed_by_row = _noul(response, "backed_by_row")
        blocking_language = _noul(response, "blocking_language")
        contradicts_verdict = _noul(response, "contradicts_verdict")
        backed.append(backed_by_row)
        blocking.append(blocking_language)
        contradicts.append(contradicts_verdict)
        if blocking_language >= _ACT_FLOOR and backed_by_row < _ACT_FLOOR:
            attestations.append(
                _attest(
                    rule_id="jev-claim-unbacked-blocker",
                    message="Blocking prose is not backed by a findings-table row",
                    path="",
                    confidence=blocking_language,
                )
            )
        if contradicts_verdict >= _ACT_FLOOR:
            attestations.append(
                _attest(
                    rule_id="jev-claim-verdict-mismatch",
                    message="Prose claim is inconsistent with the stated terminal verdict",
                    path="",
                    confidence=contradicts_verdict,
                )
            )

    if len(_named_terminal_verdicts(review_body)) > 1 and not any(
        item.rule_id == "jev-claim-verdict-mismatch" for item in attestations
    ):
        attestations.append(
            _attest(
                rule_id="jev-claim-verdict-mismatch",
                message="Review body names more than one terminal verdict",
                path="",
                confidence=1.0,
            )
        )

    return ClaimJudgeResult(
        pack_id=pack.pack_id,
        backed_by_row=min(backed) if backed else 0.0,
        blocking_language=max(blocking) if blocking else 0.0,
        contradicts_verdict=max(contradicts) if contradicts else 0.0,
        scope="run",
        blocking=False,
        pin=pin,
        findings=attestations,
    )


async def run_parallel_judge(
    *,
    findings: Sequence[Finding],
    review_body: str,
    client: AsyncJevClient,
) -> ParallelJudgeResult:
    """Run the Jev judge beside the verifier. Never replaces ``should_verify``.

    Args:
        findings: Findings the verifier still sees.
        review_body: Rendered review Markdown.
        client: Pinned Jev client (recorded transport in CI).

    Returns:
        ParallelJudgeResult: ``replaces_verifier`` is always ``False``.
    """
    pin = _registered_pin()
    evidence_results: list[EvidenceJudgeResult] = []
    for finding in findings:
        cited = finding.evidence[0] if finding.evidence else ""
        evidence_results.append(
            await judge_finding_evidence(finding, cited_section=cited, client=client)
        )
    claims = await judge_prose_claims(review_body, findings=findings, client=client)
    attestations = [row for item in evidence_results for row in item.findings]
    attestations.extend(claims.findings)
    result = ParallelJudgeResult(
        replaces_verifier=False,
        mode="parallel",
        evidence=evidence_results,
        claims=claims,
        pin=pin,
        findings=attestations,
    )
    _emit_faithfulness_alerts(result, findings_total=len(findings))
    return result


def record_parallel_judge(
    packet: MergeEvidencePacket | None,
    result: ParallelJudgeResult,
    *,
    output_path: Path | None,
    run_id: str,
    change_id: str,
) -> Any:
    """Persist one parallel-judge result through the existing shadow recorder (D6).

    Args:
        packet: Merge-evidence packet (source of truth; not mutated).
        result: ``run_parallel_judge`` outcome.
        output_path: JSONL shadow log. ``None`` records the call without a write.
        run_id: Run identifier.
        change_id: Change identifier.

    Returns:
        ShadowRecord | None: The row that was appended, or ``None`` when not persisted.
    """
    from mergecraft.evidence.shadow import record_shadow_prediction
    from mergecraft.jev.types import JevPrediction

    if packet is None or output_path is None:
        return None
    prediction = JevPrediction(
        action="require_human_review",
        skip_reviewer=False,
        suppressed=False,
        enforced=False,
        choice="parallel",
        confidence=0.0,
        severity="Minor",
        severity_score=0.0,
        unit_id="parallel-judge",
        pack_id=EVIDENCE_PACK_ID,
        outcome="require_human_review",
        diagnostic="jev-judge",
        metadata={
            "model": result.pin.model,
            "pack_id": EVIDENCE_PACK_ID,
            "judge_version": result.pin.judge_version,
            "rubric_version": result.pin.rubric_version,
            "replaces_verifier": result.replaces_verifier,
            "result": result.model_dump(mode="json"),
        },
    )
    logger.info(
        "jev judge persist pin={} evidence={} claims={} enforced=false",
        result.pin.model,
        len(result.evidence),
        0 if result.claims is None else 1,
    )
    return record_shadow_prediction(
        packet,
        change_id=change_id,
        run_id=run_id,
        policy_id="jev-judge",
        output_path=output_path,
        prediction=prediction,
        metadata={
            "model": result.pin.model,
            "pack_id": EVIDENCE_PACK_ID,
            "judge_version": result.pin.judge_version,
            "rubric_version": result.pin.rubric_version,
        },
    )


def record_judge_disagreement(
    *,
    jev_verdict: str,
    verifier_verdict: str,
    fingerprint: str,
) -> JudgeDisagreement:
    """Record verifier/Jev disagreement as a signal, never a gate (J4.5).

    Args:
        jev_verdict: Jev's verdict token.
        verifier_verdict: LLM verifier verdict token.
        fingerprint: Finding fingerprint the two judges scored.

    Returns:
        JudgeDisagreement: ``signal`` is True and ``gate`` is False.
    """
    record = JudgeDisagreement(
        signal=True,
        gate=False,
        fingerprint=fingerprint,
        jev_verdict=jev_verdict,
        verifier_verdict=verifier_verdict,
    )
    logger.info(
        "jev judge disagreement signal fingerprint={} jev={} verifier={} gate=false",
        fingerprint,
        jev_verdict,
        verifier_verdict,
    )
    return record


def _choice(response: SystemOneResponse, name: str) -> str:
    answer = response.answers.get(name)
    if isinstance(answer, ChoiceAnswer):
        return answer.choice
    return ""


def _choice_confidence(response: SystemOneResponse, name: str) -> float:
    answer = response.answers.get(name)
    if isinstance(answer, ChoiceAnswer):
        return float(answer.confidence)
    return 0.0


def _noul(response: SystemOneResponse, name: str) -> float:
    answer = response.answers.get(name)
    if isinstance(answer, NoulAnswer):
        return float(answer.noul)
    return 0.0


def _attest(*, rule_id: str, message: str, path: str, confidence: float) -> Finding:
    try:
        ordinal = bucket_confidence(confidence)
    except JevError:
        ordinal = "possible"
    return make_finding(
        tool=_TOOL,
        rule_id=rule_id,
        category=_CATEGORY,
        severity="Minor",
        confidence=ordinal,
        message=message,
        path=path,
        start_line=1,
        end_line=1,
        source="classifier",
        scope="run",
        introduced_by_pr="false",
    )


def _render_findings_table(findings: Sequence[Finding]) -> str:
    if not findings:
        return "none"
    lines = ["| Severity | Path | Message |", "| --- | --- | --- |"]
    for item in findings:
        lines.append(f"| {item.severity} | {item.path} | {item.message} |")
    return "\n".join(lines)


_REQUEST_VERDICT_TOKENS: Final[tuple[str, ...]] = (
    "request_changes",
    "must not merge",
    "must block",
)
_APPROVE_VERDICT_TOKENS: Final[tuple[str, ...]] = ("approve",)


def _named_terminal_verdicts(review_body: str) -> frozenset[str]:
    lowered = review_body.casefold()
    found: set[str] = set()
    if any(token in lowered for token in _REQUEST_VERDICT_TOKENS):
        found.add("request_changes")
    if any(token in lowered for token in _APPROVE_VERDICT_TOKENS):
        found.add("approve")
    return frozenset(found)


def _stated_terminal_verdict(review_body: str) -> str:
    named = _named_terminal_verdicts(review_body)
    if named == {"request_changes"}:
        return "request_changes"
    if named == {"approve"}:
        return "approve"
    if len(named) > 1:
        return "conflicted"
    return "unspecified"


def _claim_unit_id(text: str) -> str:
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"claim:{digest}"


def _emit_faithfulness_alerts(result: ParallelJudgeResult, *, findings_total: int) -> None:
    """Collect J4 signals and emit Logfire attrs. Tracing must not fail the judge."""
    try:
        from mergecraft.evals.faithfulness import (
            collect_faithfulness_signals,
            emit_faithfulness_alerts,
        )
        from mergecraft.tracing import Tracer, current_tracer

        signals = collect_faithfulness_signals(result, findings_total=findings_total)
        live = current_tracer()
        emit_faithfulness_alerts(signals, tracer=live if isinstance(live, Tracer) else None)
    except Exception as exc:
        logger.warning("faithfulness alert emit failed: {}", exc)


__all__ = [
    "JEV_JUDGE_VERSION",
    "JEV_RUBRIC_VERSION",
    "ClaimJudgeResult",
    "EvidenceJudgeResult",
    "JevJudgePin",
    "JudgeDisagreement",
    "ParallelJudgeResult",
    "judge_finding_evidence",
    "judge_prose_claims",
    "record_judge_disagreement",
    "record_parallel_judge",
    "run_parallel_judge",
]
