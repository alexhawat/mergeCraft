"""Declared decision nodes for hybrid orchestration (AP7).

Each decision node is a typed single structured-output call — not a full agent
loop. The model answers; the pipeline routes on the closed answer type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from mergecraft.agents.registry import Registry
    from mergecraft.agents.verifier import AgentFinding

_DISPOSITION_VERDICTS = frozenset({"keep", "withdraw", "escalate", "needs_verification"})
_TRIVIALITY_OUTCOMES = frozenset({"trivial", "not_trivial"})


class DecisionNodeKind(StrEnum):
    triviality_gate = "triviality_gate"
    lens_selection = "lens_selection"
    finding_disposition = "finding_disposition"


class DecisionSchemaError(ValueError):
    """Raised when structured decision output is outside the closed schema."""


class TrivialityAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["trivial", "not_trivial"]
    reason: str


class LensSelectionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lens_ids: tuple[str, ...]


class FindingDispositionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["keep", "withdraw", "escalate", "needs_verification"]


DecisionAnswer = TrivialityAnswer | LensSelectionAnswer | FindingDispositionAnswer


class StructuredDecisionClient(Protocol):
    """Minimal structured-output client for a single decision-node call."""

    def complete_structured(
        self,
        *,
        schema_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]: ...


def decision_schema_id(kind: DecisionNodeKind) -> str:
    return f"mergecraft.decision.{kind.value}"


def _validate_triviality_payload(payload: dict[str, Any]) -> TrivialityAnswer:
    try:
        answer = TrivialityAnswer.model_validate(payload)
    except ValidationError as exc:
        msg = f"triviality_gate answer outside schema: {exc}"
        raise DecisionSchemaError(msg) from exc
    if answer.outcome not in _TRIVIALITY_OUTCOMES:
        msg = f"triviality_gate outcome {answer.outcome!r} outside schema"
        raise DecisionSchemaError(msg)
    return answer


def _validate_lens_payload(
    payload: dict[str, Any], registry: Registry | None
) -> LensSelectionAnswer:
    try:
        raw_ids = payload.get("lens_ids", payload.get("lens_ids", ()))
        if isinstance(raw_ids, list):
            payload = {**payload, "lens_ids": tuple(str(item) for item in raw_ids)}
        answer = LensSelectionAnswer.model_validate(payload)
    except ValidationError as exc:
        msg = f"lens_selection answer outside schema: {exc}"
        raise DecisionSchemaError(msg) from exc
    if registry is not None:
        from mergecraft.agents.registry import resolve_agent_ref

        for lens_id in answer.lens_ids:
            resolve_agent_ref(registry, lens_id)
    return answer


def _validate_disposition_payload(payload: dict[str, Any]) -> FindingDispositionAnswer:
    try:
        answer = FindingDispositionAnswer.model_validate(payload)
    except ValidationError as exc:
        msg = f"finding_disposition answer outside schema: {exc}"
        raise DecisionSchemaError(msg) from exc
    if answer.verdict not in _DISPOSITION_VERDICTS:
        msg = f"finding_disposition verdict {answer.verdict!r} outside schema"
        raise DecisionSchemaError(msg)
    return answer


def run_decision_node(
    kind: DecisionNodeKind,
    *,
    client: StructuredDecisionClient,
    diff_text: str = "",
    registry: Registry | None = None,
    classifier_signals: dict[str, Any] | None = None,
    findings: list[AgentFinding] | None = None,
) -> DecisionAnswer:
    """Run one decision node as a single structured-output call."""
    context: dict[str, Any] = {
        "diff_text": diff_text,
        "classifier_signals": classifier_signals or {},
    }
    if findings is not None:
        context["findings"] = [finding.model_dump() for finding in findings]

    schema_id = decision_schema_id(kind)
    payload = client.complete_structured(schema_id=schema_id, context=context)

    if kind is DecisionNodeKind.triviality_gate:
        return _validate_triviality_payload(payload)
    if kind is DecisionNodeKind.lens_selection:
        return _validate_lens_payload(payload, registry)
    return _validate_disposition_payload(payload)


@dataclass(frozen=True)
class DecisionEvalCase:
    kind: DecisionNodeKind
    inputs: dict[str, Any]
    expected_answer: DecisionAnswer


@dataclass(frozen=True)
class DecisionEvalResult:
    kind: DecisionNodeKind
    passed: bool


def decision_eval_cases() -> tuple[DecisionEvalCase, ...]:
    """One self-contained eval fixture per decision kind (file 4 integration)."""
    from mergecraft.agents.verifier import AgentFinding

    return (
        DecisionEvalCase(
            kind=DecisionNodeKind.triviality_gate,
            inputs={
                "diff_text": "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n-# Title\n+# Titl",
            },
            expected_answer=TrivialityAnswer(outcome="trivial", reason="doc typo"),
        ),
        DecisionEvalCase(
            kind=DecisionNodeKind.lens_selection,
            inputs={
                "diff_text": "diff --git a/src/billing/x.py b/src/billing/x.py\n",
                "classifier_signals": {
                    "changed_paths": ["src/billing/x.py"],
                    "languages": ["python"],
                    "risk_band": "high",
                },
            },
            expected_answer=LensSelectionAnswer(lens_ids=("reviewer", "verifier")),
        ),
        DecisionEvalCase(
            kind=DecisionNodeKind.finding_disposition,
            inputs={
                "findings": [
                    AgentFinding(
                        path="src/x.py",
                        body="example finding",
                        severity="Major",
                        line=1,
                    )
                ],
            },
            expected_answer=FindingDispositionAnswer(verdict="needs_verification"),
        ),
    )


def evaluate_decision_case(
    case: DecisionEvalCase,
    *,
    answer: DecisionAnswer,
) -> DecisionEvalResult:
    """Score one decision in isolation for eval replay."""
    if case.kind is DecisionNodeKind.triviality_gate:
        expected = case.expected_answer
        assert isinstance(expected, TrivialityAnswer)
        assert isinstance(answer, TrivialityAnswer)
        passed = answer.outcome == expected.outcome
    elif case.kind is DecisionNodeKind.lens_selection:
        expected = case.expected_answer
        assert isinstance(expected, LensSelectionAnswer)
        assert isinstance(answer, LensSelectionAnswer)
        passed = answer.lens_ids == expected.lens_ids
    else:
        expected = case.expected_answer
        assert isinstance(expected, FindingDispositionAnswer)
        assert isinstance(answer, FindingDispositionAnswer)
        passed = answer.verdict == expected.verdict
    return DecisionEvalResult(kind=case.kind, passed=passed)


__all__ = [
    "DecisionAnswer",
    "DecisionEvalCase",
    "DecisionEvalResult",
    "DecisionNodeKind",
    "DecisionSchemaError",
    "FindingDispositionAnswer",
    "LensSelectionAnswer",
    "StructuredDecisionClient",
    "TrivialityAnswer",
    "decision_eval_cases",
    "decision_schema_id",
    "evaluate_decision_case",
    "run_decision_node",
]
