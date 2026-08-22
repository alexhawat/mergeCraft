"""Declarative review pipeline schema and closed predicate vocabulary (AP6 / D8, D9)."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_RISK_BANDS: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
_RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_SEVERITIES: frozenset[str] = frozenset({"Minor", "Major", "Critical"})
_SEVERITY_ORDER: dict[str, int] = {"Minor": 0, "Major": 1, "Critical": 2}

_FORBIDDEN_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "eval(",
        "__import__",
        "exec(",
        "os.system",
        "subprocess",
        "import ",
    }
)

_ALLOWED_PREDICATE_RE = re.compile(
    r"^(changed_paths matches '([^']*)'"
    r"|risk_band >= (low|medium|high|critical)"
    r"|languages includes ([a-zA-Z0-9_.+-]+)"
    r"|analyzer_findings\.severity >= (Minor|Major|Critical)"
    r"|decision\.([a-z_]+) is (trivial|not_trivial))$"
)


class PipelineValidationError(ValueError):
    """Raised when a pipeline file or predicate fails structural validation."""


class PipelineStepKind(StrEnum):
    agent = "agent"
    terminal = "terminal"
    fan_out = "fan_out"
    decision = "decision"


OnErrorPolicy = Literal["continue", "fail"]
PipelineSource = Literal["repo", "operator"]


class PipelineStep(BaseModel):
    """One step in a linear review pipeline (D8)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: PipelineStepKind
    agent: str | None = None
    agents: tuple[str, ...] = Field(default_factory=tuple)
    decision: str | None = None
    when: str | None = None
    on_error: OnErrorPolicy = "fail"
    budget: int | None = None
    timeout: int | None = Field(default=None, alias="timeoutS")

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("on_error", mode="before")
    @classmethod
    def _normalize_on_error(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower()
        return value


class PipelineDefinition(BaseModel):
    """Parsed pipeline file — a ordered step list, not a DAG (D8)."""

    model_config = ConfigDict(extra="forbid")

    steps: tuple[PipelineStep, ...]
    source: PipelineSource = "repo"

    def step_ids(self) -> list[str]:
        return [step.id for step in self.steps]


def validate_predicate(expression: str) -> None:
    """Validate a ``when`` predicate against the closed vocabulary (convention 7)."""
    expr = expression.strip()
    lowered = expr.lower()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in lowered:
            msg = f"forbidden executable predicate fragment in expression: {forbidden!r}"
            raise PipelineValidationError(msg)

    if not _ALLOWED_PREDICATE_RE.match(expr):
        msg = (
            f"predicate outside closed vocabulary: {expression!r} "
            "(allowed: changed_paths matches, risk_band >=, languages includes, "
            "analyzer_findings.severity >=)"
        )
        raise PipelineValidationError(msg)


def risk_at_or_above(risk: str, threshold: str) -> bool:
    """Return whether ``risk`` is at or above ``threshold`` in the shared band order."""
    actual = str(risk).casefold()
    return _RISK_ORDER.get(actual, 0) >= _RISK_ORDER.get(str(threshold).casefold(), 0)


def _path_matches(pattern: str, path: str) -> bool:
    pure = PurePath(path)
    if pure.match(pattern):
        return True
    # ``**/*.ext`` also matches root-level files (``README.md`` has no parent segment).
    if pattern.startswith("**/"):
        return pure.match(pattern[3:])
    return False


def evaluate_predicate(
    expression: str,
    *,
    classifier_signals: dict[str, Any] | None = None,
    decision_answers: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a validated predicate against classifier / diff signals."""
    validate_predicate(expression)
    signals = classifier_signals or {}
    answers = decision_answers or {}
    expr = expression.strip()

    if expr.startswith("decision."):
        node_id, _, outcome = expr.partition(" is ")
        node_id = node_id.removeprefix("decision.").strip()
        answer = answers.get(node_id)
        if answer is None:
            return False
        actual = getattr(answer, "outcome", None)
        return str(actual) == outcome.strip()

    if expr.startswith("changed_paths matches "):
        pattern = expr.split("'", 2)[1]
        paths = [str(p) for p in signals.get("changed_paths", [])]
        return any(_path_matches(pattern, path) for path in paths)

    if expr.startswith("risk_band >= "):
        threshold = expr.rsplit(">= ", 1)[1].strip()
        actual = str(signals.get("risk_band", "low"))
        return risk_at_or_above(actual, threshold)

    if expr.startswith("languages includes "):
        needle = expr.rsplit("includes ", 1)[1].strip()
        languages = {str(lang).lower() for lang in signals.get("languages", [])}
        return needle.lower() in languages

    if expr.startswith("analyzer_findings.severity >= "):
        threshold = expr.rsplit(">= ", 1)[1].strip()
        findings = signals.get("analyzer_findings", [])
        if not isinstance(findings, list):
            return False
        max_severity = 0
        for item in findings:
            if isinstance(item, dict):
                severity = str(item.get("severity", "Minor"))
                max_severity = max(max_severity, _SEVERITY_ORDER.get(severity, 0))
        return max_severity >= _SEVERITY_ORDER.get(threshold, 0)

    msg = f"unknown predicate operator in {expression!r}"
    raise PipelineValidationError(msg)


def parse_pipeline(text: str, *, source: PipelineSource = "repo") -> PipelineDefinition:
    """Parse a pipeline YAML document into a :class:`PipelineDefinition`."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        msg = "pipeline document must be a mapping with a steps list"
        raise PipelineValidationError(msg)
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        msg = "pipeline must declare at least one step"
        raise PipelineValidationError(msg)

    steps: list[PipelineStep] = []
    for entry in steps_raw:
        if not isinstance(entry, dict):
            msg = "each pipeline step must be a mapping"
            raise PipelineValidationError(msg)
        step = PipelineStep.model_validate(entry)
        if step.when is not None:
            validate_predicate(step.when)
        if step.kind is PipelineStepKind.agent and not step.agent:
            msg = f"agent step {step.id!r} missing agent reference"
            raise PipelineValidationError(msg)
        if step.kind is PipelineStepKind.fan_out and not step.agents:
            msg = f"fan_out step {step.id!r} missing agents list"
            raise PipelineValidationError(msg)
        if step.kind is PipelineStepKind.decision and not step.decision:
            msg = f"decision step {step.id!r} missing decision reference"
            raise PipelineValidationError(msg)
        steps.append(step)

    return PipelineDefinition(steps=tuple(steps), source=source)


def lint_pipeline_agents(pipeline: PipelineDefinition, registry: Any) -> list[str]:
    """Return human-readable errors for agent references missing from the registry."""
    from mergecraft.agents.registry import Registry, resolve_agent_ref

    if not isinstance(registry, Registry):
        msg = "registry must be a mergecraft.agents.registry.Registry"
        raise TypeError(msg)

    errors: list[str] = []
    for step in pipeline.steps:
        refs: list[str] = []
        if step.kind is PipelineStepKind.agent and step.agent:
            refs.append(step.agent)
        if step.kind is PipelineStepKind.fan_out:
            refs.extend(step.agents)
        for ref in refs:
            try:
                resolve_agent_ref(registry, ref)
            except KeyError:
                errors.append(f"unknown agent id {ref!r} in step {step.id!r}")
    return errors


__all__ = [
    "RISK_BANDS",
    "OnErrorPolicy",
    "PipelineDefinition",
    "PipelineSource",
    "PipelineStep",
    "PipelineStepKind",
    "PipelineValidationError",
    "evaluate_predicate",
    "lint_pipeline_agents",
    "parse_pipeline",
    "risk_at_or_above",
    "validate_predicate",
]

RISK_BANDS = _RISK_BANDS
