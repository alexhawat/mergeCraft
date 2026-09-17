"""Jev wire types — System One responses, answers, and call results.

Exports:
    PINNED_MODEL: Versioned Jev model id (D8).
    JevError: Structured client/parse failure.
    EVIDENCE_PACK_ID: Versioned ``evidence/v1`` pack id (J4).
    CLAIM_PACK_ID: Versioned ``claim/v1`` pack id (J4).
    ALIGN_PACK_ID: Versioned ``align/v1`` pack id (J5).
    LENS_PACK_ID: Versioned ``lens/v1`` pack id (J5).
    Usage: Token counts; either field may be ``None`` (T4).
    NoulAnswer: Probability of yes; no confidence field (T5 / G6).
    ChoiceAnswer: Discrete choice with confidence and probabilities.
    ScoreAnswer: Ordered score with confidence, legend, and probabilities.
    SystemOneResponse: Parsed ``system_one`` body.
    JevCallResult: One client call outcome, including honest skips.
    HunkUnit: One hunk-shaped review unit (D2).
    UnitAssessment: Parsed ``unit/v1`` battery.
    PolicyVerdict: Prior or incoming ratchet verdict.
    JevPrediction: Shadow prediction; never skip or suppress.
    JevThreshold: Pack-versioned floor with corpus row ids.
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
    legend: dict[int, str] = Field(default_factory=dict)
    probabilities: dict[int, float] = Field(default_factory=dict)


JevAnswer = ChoiceAnswer | ScoreAnswer | NoulAnswer


class SystemOneResponse(BaseModel):
    """Parsed System One response body (T3)."""

    model_config = ConfigDict(extra="ignore")

    request_id: str | None = None
    model: str
    usage: Usage = Field(default_factory=Usage)
    answers: dict[str, JevAnswer] = Field(default_factory=dict)


UNIT_PACK_ID: Final[str] = "unit/v1"
EVIDENCE_PACK_ID: Final[str] = "evidence/v1"
CLAIM_PACK_ID: Final[str] = "claim/v1"
ALIGN_PACK_ID: Final[str] = "align/v1"
LENS_PACK_ID: Final[str] = "lens/v1"
CERTAIN_CONFIDENCE_FLOOR: Final[float] = 0.9
LIKELY_CONFIDENCE_FLOOR: Final[float] = 0.6
NOUL_ACT_FLOOR: Final[float] = 0.5
UNIT_THRESHOLD_CORPUS_IDS: Final[tuple[str, ...]] = (
    "jev-unit-privilege-drop-home",
    "jev-unit-auth-stem-author",
    "jev-unit-mcp-config-root",
)
LENS_THRESHOLD_CORPUS_IDS: Final[tuple[str, ...]] = (
    "jev-lens-privilege-drop-not-generic-security",
    "jev-lens-copy-vs-code-help-string",
    "jev-lens-data-integrity-write-before-confirm",
)
ALIGN_THRESHOLD_CORPUS_IDS: Final[tuple[str, ...]] = (
    "jev-align-auth-author-paraphrase",
    "jev-align-n5-weaker-first",
    "jev-align-withdrawn-reraise",
)

SEVERITY_BY_SCORE: Final[dict[int, str]] = {
    0: "Trivial",
    1: "Minor",
    2: "Major",
    3: "Critical",
}

TriageChoice = Literal["clean", "suspicious", "defective"]
TrustTierName = Literal["trusted", "untrusted"]


class HunkUnit(BaseModel):
    """One hunk-shaped review unit (D2). Function units are out of scope."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["hunk"] = "hunk"
    path: str
    content: str
    context_lines: int
    unit_id: str
    start_line: int
    end_line: int


class UnitAssessment(BaseModel):
    """Parsed ``unit/v1`` battery for one hunk."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    choice: str
    confidence: float
    severity_score: float
    severity: str | None = None
    pack_id: str = UNIT_PACK_ID
    lane: str | None = None


class PolicyVerdict(BaseModel):
    """A prior or incoming policy verdict the ratchet compares."""

    model_config = ConfigDict(extra="forbid")

    choice: str
    confidence: float
    severity: str
    severity_score: float


class JevPrediction(BaseModel):
    """Shadow prediction for one unit. Never skip or suppress (D7)."""

    model_config = ConfigDict(extra="forbid")

    action: str
    skip_reviewer: bool = False
    suppressed: bool = False
    enforced: bool = False
    choice: str
    confidence: float
    severity: str
    severity_score: float
    unit_id: str | None = None
    pack_id: str = UNIT_PACK_ID
    lane: str | None = None
    discarded_deescalation: bool = False
    concluded_clean: bool = False
    cleared: bool = False
    recorded: bool = False
    trust_tier: str = "trusted"
    outcome: str | None = None
    diagnostic: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JevThreshold(BaseModel):
    """One pack-versioned threshold tied to eval-corpus rows (D15)."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str
    value: float
    corpus_ids: tuple[str, ...]
    name: str | None = None


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
                "legend": _intify_keys(raw.get("legend")),
                "probabilities": _intify_keys(raw.get("probabilities")),
            }
        )
    if "noul" in raw:
        return NoulAnswer.model_validate({"noul": raw["noul"]})
    raise JevError("unrecognized answer shape", code="invalid_response")


def _intify_keys(value: object) -> dict[int, Any]:
    if not isinstance(value, dict):
        return {}
    converted: dict[int, Any] = {}
    for key, item in value.items():
        converted[int(key)] = item
    return converted


__all__ = [
    "ALIGN_PACK_ID",
    "ALIGN_THRESHOLD_CORPUS_IDS",
    "CERTAIN_CONFIDENCE_FLOOR",
    "CLAIM_PACK_ID",
    "EVIDENCE_PACK_ID",
    "LENS_PACK_ID",
    "LENS_THRESHOLD_CORPUS_IDS",
    "LIKELY_CONFIDENCE_FLOOR",
    "NOUL_ACT_FLOOR",
    "PINNED_MODEL",
    "SEVERITY_BY_SCORE",
    "UNIT_PACK_ID",
    "UNIT_THRESHOLD_CORPUS_IDS",
    "ChoiceAnswer",
    "HunkUnit",
    "JevAnswer",
    "JevCallResult",
    "JevError",
    "JevPrediction",
    "JevSkipReason",
    "JevThreshold",
    "NoulAnswer",
    "PolicyVerdict",
    "ScoreAnswer",
    "SystemOneResponse",
    "TransportEnvelope",
    "TransportError",
    "TransportHttp",
    "TriageChoice",
    "TrustTierName",
    "UnitAssessment",
    "Usage",
    "parse_system_one_response",
]
