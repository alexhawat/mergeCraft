"""Jev wire types — System One responses, answers, and call results.

Exports:
    PINNED_MODEL: Versioned Jev model id (D8).
    JevError: Structured client/parse failure.
    Usage: Token counts; either field may be ``None`` (T4).
    NoulAnswer: Probability of yes; no confidence field (T5 / G6).
    ChoiceAnswer: Discrete choice with confidence and probabilities.
    ScoreAnswer: Ordered score with confidence, legend, and probabilities.
    SystemOneResponse: Parsed ``system_one`` body.
    JevCallResult: One client call outcome, including honest skips.
    TransportHttp: Recorded HTTP envelope.
    TransportError: Recorded TypeSafe error object.
    TransportEnvelope: Recorded transport fixture payload.
    parse_system_one_response: Parse a recorded or live response body.
"""

from __future__ import annotations

from typing import Any, Final, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

PINNED_MODEL: Final[str] = "jev-1.13.0"

JevSkipReason = Literal["disabled", "credential_absent", "kill_switch"]


class JevError(Exception):
    """Structured Jev failure with a stable ``code`` contract."""

    def __init__(self, message: str = "", *, code: str) -> None:
        super().__init__(message or code)
        self.code = code


class Usage(BaseModel):
    """Token counts as TypeSafe reports them — both fields may be ``None`` (T4)."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = None
    output_tokens: int | None = None


class NoulAnswer(BaseModel):
    """Noul primitive: a yes-probability and nothing else (T5)."""

    model_config = ConfigDict(extra="forbid")

    noul: float


class ChoiceAnswer(BaseModel):
    """Choice primitive with calibrated confidence (T5)."""

    model_config = ConfigDict(extra="forbid")

    choice: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)


class ScoreAnswer(BaseModel):
    """Score primitive with legend and per-bucket probabilities (T5)."""

    model_config = ConfigDict(extra="forbid")

    score: float
    confidence: float
    legend: dict[str, str] = Field(default_factory=dict)
    probabilities: dict[str, float] = Field(default_factory=dict)


JevAnswer = ChoiceAnswer | ScoreAnswer | NoulAnswer


class SystemOneResponse(BaseModel):
    """Parsed System One response body (T3)."""

    model_config = ConfigDict(extra="ignore")

    request_id: str | None = None
    model: str
    usage: Usage = Field(default_factory=Usage)
    answers: dict[str, JevAnswer] = Field(default_factory=dict)


class JevCallResult(BaseModel):
    """Outcome of one ``AsyncJevClient.call``.

    Skips use the tokens ``disabled``, ``credential_absent``, and
    ``kill_switch`` — never English prose.
    """

    model_config = ConfigDict(extra="forbid")

    skipped: bool
    available: bool
    incomplete: bool = False
    reason: str | None = None
    model: str | None = None
    response: SystemOneResponse | None = None
    latency_ms: float | None = None
    cost_known: bool = False
    cost_usd: float | None = None


class TransportHttp(TypedDict):
    """Recorded HTTP status and headers."""

    status: int
    headers: dict[str, str]


class TransportError(TypedDict, total=False):
    """Recorded TypeSafe error object from a fixture envelope."""

    type: str
    status_code: int
    code: str


class TransportEnvelope(TypedDict, total=False):
    """Recorded TypeSafe transport fixture (HTTP + body or error)."""

    http: TransportHttp
    body: dict[str, Any]
    error: TransportError


def parse_system_one_response(data: dict[str, Any]) -> SystemOneResponse:
    """Parse a System One JSON body into typed answers.

    Args:
        data: Response body mapping (never a live HTTP call).

    Returns:
        SystemOneResponse: Validated model, usage, and answers.

    Raises:
        JevError: When the body is empty or structurally invalid.
    """
    if not data or not isinstance(data, dict):
        raise JevError("system_one response body is empty", code="invalid_response")
    model = data.get("model")
    answers_raw = data.get("answers")
    if not isinstance(model, str) or not model or not isinstance(answers_raw, dict):
        raise JevError("system_one response is missing model or answers", code="invalid_response")
    usage_raw = data.get("usage")
    usage = Usage.model_validate(usage_raw) if isinstance(usage_raw, dict) else Usage()
    answers: dict[str, JevAnswer] = {}
    for name, raw in answers_raw.items():
        if not isinstance(raw, dict):
            raise JevError(f"answer {name!r} is not an object", code="invalid_response")
        answers[str(name)] = _parse_answer(raw)
    request_id = data.get("request_id")
    return SystemOneResponse(
        request_id=request_id if isinstance(request_id, str) else None,
        model=model,
        usage=usage,
        answers=answers,
    )


def _parse_answer(raw: dict[str, Any]) -> JevAnswer:
    if "choice" in raw:
        return ChoiceAnswer.model_validate(raw)
    if "score" in raw:
        return ScoreAnswer.model_validate(
            {
                "score": raw["score"],
                "confidence": raw.get("confidence", 0.0),
                "legend": _stringify_keys(raw.get("legend")),
                "probabilities": _stringify_keys(raw.get("probabilities")),
            }
        )
    if "noul" in raw:
        return NoulAnswer.model_validate({"noul": raw["noul"]})
    raise JevError("unrecognized answer shape", code="invalid_response")


def _stringify_keys(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


__all__ = [
    "PINNED_MODEL",
    "ChoiceAnswer",
    "JevAnswer",
    "JevCallResult",
    "JevError",
    "JevSkipReason",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "TransportEnvelope",
    "TransportError",
    "TransportHttp",
    "Usage",
    "parse_system_one_response",
]
