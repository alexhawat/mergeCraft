"""Versioned Jev question packs, including live-catalog ``lens/v1`` (J5).

Exports:
    QuestionPack: Versioned pack with typed questions.
    LensQuestionPack: ``lens/v1`` bound to the live lens catalog.
    LensSelection: Selected lens ids plus the source of the choice.
    unit_pack: Per-hunk Choice + Score + Noul battery.
    evidence_pack: Citation-check battery per finding (T12).
    claim_pack: Prose-claim battery for plan 21 D6 rules 1, 3, 4.
    align_pack: Entity-alignment battery per candidate pair (G14).
    lens_pack: One Choice per catalog lens, read live (plan 21 D9).
    get_pack: Lookup by versioned pack id.
    select_lenses: One ``lens/v1`` call per PR.
    select_lenses_or_fallback: ``jev:`` toggle + confidence-floor fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from mergecraft.jev.architecture import build_system_one_questions
from mergecraft.jev.types import (
    ALIGN_PACK_ID,
    CLAIM_PACK_ID,
    EVIDENCE_PACK_ID,
    LENS_PACK_ID,
    LIKELY_CONFIDENCE_FLOOR,
    UNIT_PACK_ID,
    ChoiceAnswer,
    JevError,
)
from mergecraft.review_taxonomy import FINDING_SEVERITIES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.agents.lenses._base import LensDefinition
    from mergecraft.config.settings import RepoSettings
    from mergecraft.jev.client import AsyncJevClient

QuestionKind = Literal["choice", "score", "noul"]
LensSource = Literal["jev", "triggers"]

_SEVERITY_LEGEND: dict[int, str] = {
    0: "Trivial — nitpick; body-only and never a merge blocker",
    1: "Minor — real issue that does not block the merge",
    2: "Major — blocking defect (repo Critical/Major grade)",
    3: "Critical — highest-grade blocking defect",
}

# Repo taxonomy names are the Score legend labels (axis is Trivial → Critical).
assert set(FINDING_SEVERITIES) == {"Trivial", "Minor", "Major", "Critical"}


def _live_lens_definitions() -> dict[str, LensDefinition]:
    """Return the live catalog object — never a copied name list (plan 21 D9)."""
    from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS

    return LENS_DEFINITIONS


class QuestionSpec(BaseModel):
    """One System One question. Instructions and criteria are the same ask (T11)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: QuestionKind
    instructions: str
    criteria: dict[str, str] = Field(default_factory=dict)
    legend: dict[int, str] = Field(default_factory=dict)

    def as_system_one(self) -> dict[str, Any]:
        """Render the TypeSafe question object for one ``system_one`` call."""
        payload: dict[str, Any] = {"type": self.kind, "instructions": self.instructions}
        if self.kind == "choice":
            payload["criteria"] = dict(self.criteria)
        if self.kind == "score":
            payload["legend"] = dict(self.legend)
        return payload


class QuestionPack(BaseModel):
    """Versioned question pack. ``pack_id`` is recorded on every span and shadow row."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str
    questions: tuple[QuestionSpec, ...] = ()

    @property
    def question_names(self) -> tuple[str, ...]:
        return tuple(question.name for question in self.questions)

    def question_type(self, name: str) -> QuestionKind:
        """Return the primitive kind for ``name``.

        Args:
            name: Question name inside this pack.

        Returns:
            QuestionKind: ``choice``, ``score``, or ``noul``.

        Raises:
            KeyError: When ``name`` is not in the pack.
        """
        for question in self.questions:
            if question.name == name:
                return question.kind
        raise KeyError(name)

    def as_system_one(self) -> dict[str, Any]:
        """Render the ``questions=`` mapping for ``system_one``."""
        return {question.name: question.as_system_one() for question in self.questions}


class LensQuestionPack(QuestionPack):
    """``lens/v1`` pack whose families are read from the live catalog."""

    reads_live_catalog: bool = True

    @property
    def source_catalog(self) -> Mapping[str, LensDefinition]:
        return _live_lens_definitions()

    @property
    def lens_ids(self) -> tuple[str, ...]:
        return tuple(_live_lens_definitions())


class LensSelection(BaseModel):
    """Lenses chosen by Jev or by today's trigger matching."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str = LENS_PACK_ID
    lens_ids: tuple[str, ...] = ()
    source: LensSource = "jev"
    confidence: float | None = None
    skipped: bool = False
    reason: str | None = None


def unit_pack() -> QuestionPack:
    """Pack ``unit/v1`` — one call per residual hunk (D1)."""
    return QuestionPack(
        pack_id=UNIT_PACK_ID,
        questions=(
            QuestionSpec(
                name="triage",
                kind="choice",
                instructions="What is the defect status of this change?",
                criteria={
                    "clean": "The change is free of defects.",
                    "suspicious": "The change may introduce a defect.",
                    "defective": "The change introduces a defect.",
                },
            ),
            QuestionSpec(
                name="severity",
                kind="score",
                instructions=(
                    "How severe is the defect this change introduces, using "
                    "mergeCraft's Trivial → Minor → Major → Critical grades?"
                ),
                legend=_SEVERITY_LEGEND,
            ),
            QuestionSpec(
                name="security",
                kind="noul",
                instructions=(
                    "This change introduces an authorization, injection, or "
                    "secret-handling problem."
                ),
            ),
            QuestionSpec(
                name="error_discard",
                kind="noul",
                instructions="This change discards or swallows an error.",
            ),
            QuestionSpec(
                name="contract_break",
                kind="noul",
                instructions="This change alters a documented API or wire contract.",
            ),
            QuestionSpec(
                name="untrusted_input",
                kind="noul",
                instructions="This change accepts unvalidated input as trusted.",
            ),
            QuestionSpec(
                name="missing_tests",
                kind="noul",
                instructions="The risk this change introduces is untested.",
            ),
            QuestionSpec(
                name="style_nit",
                kind="noul",
                instructions=(
                    "This change is only a formatting or naming nit with no runtime effect."
                ),
            ),
        ),
    )


def evidence_pack() -> QuestionPack:
    """Pack ``evidence/v1`` — one call per finding (T12 citation-check)."""
    return QuestionPack(
        pack_id=EVIDENCE_PACK_ID,
        questions=(
            QuestionSpec(
                name="relation",
                kind="choice",
                instructions="How does the cited code relate to the finding's claim?",
                criteria={
                    "supports": "The cited code supports the finding's claim.",
                    "contradicts": "The cited code contradicts the finding's claim.",
                    "says_nothing": "The cited code says nothing about the finding's claim.",
                },
            ),
            QuestionSpec(
                name="falsifiable",
                kind="noul",
                instructions="The claim can be checked against the diff rather than asserted.",
            ),
            QuestionSpec(
                name="located",
                kind="noul",
                instructions="The cited path and line range are the ones the claim is about.",
            ),
        ),
    )


def claim_pack() -> QuestionPack:
    """Pack ``claim/v1`` — one call per extracted prose claim (plan 21 D6 1/3/4)."""
    return QuestionPack(
        pack_id=CLAIM_PACK_ID,
        questions=(
            QuestionSpec(
                name="backed_by_row",
                kind="noul",
                instructions="This claim corresponds to a row in the findings table.",
            ),
            QuestionSpec(
                name="blocking_language",
                kind="noul",
                instructions="This claim asserts something that should block the merge.",
            ),
            QuestionSpec(
                name="contradicts_verdict",
                kind="noul",
                instructions="This claim is inconsistent with the stated terminal verdict.",
            ),
        ),
    )


def align_pack() -> QuestionPack:
    """Pack ``align/v1`` — one call per candidate pair (G14)."""
    return QuestionPack(
        pack_id=ALIGN_PACK_ID,
        questions=(
            QuestionSpec(
                name="same_defect",
                kind="choice",
                instructions="How do these two findings relate?",
                criteria={
                    "same": "Both findings describe the same defect.",
                    "related": "The findings describe related defects.",
                    "distinct": "The findings describe unrelated defects.",
                },
            ),
            QuestionSpec(
                name="is_withdrawn_reraise",
                kind="noul",
                instructions=(
                    "This finding re-raises one recorded under Withdrawn review findings."
                ),
            ),
        ),
    )


def lens_pack() -> LensQuestionPack:
    """Pack ``lens/v1`` — one Choice per live catalog family (plan 21 D9)."""
    questions = tuple(
        QuestionSpec(
            name=lens_id,
            kind="choice",
            instructions=f"Should the {definition.title} lens apply to this change?",
            criteria={
                "apply": f"The {definition.title} lens applies to this change.",
                "skip": f"The {definition.title} lens is outside this change.",
            },
        )
        for lens_id, definition in _live_lens_definitions().items()
    )
    return LensQuestionPack(pack_id=LENS_PACK_ID, questions=questions)


_PACK_FACTORIES = {
    UNIT_PACK_ID: unit_pack,
    EVIDENCE_PACK_ID: evidence_pack,
    CLAIM_PACK_ID: claim_pack,
    ALIGN_PACK_ID: align_pack,
    LENS_PACK_ID: lens_pack,
}


def get_pack(pack_id: str) -> QuestionPack:
    """Return the versioned pack for ``pack_id``.

    Args:
        pack_id: One of the five registered pack ids.

    Returns:
        QuestionPack: The named pack.

    Raises:
        JevError: When ``pack_id`` is unknown.
    """
    factory = _PACK_FACTORIES.get(pack_id)
    if factory is None:
        raise JevError(f"unknown question pack {pack_id!r}", code="invalid_pack")
    return factory()


async def select_lenses(
    *,
    state: dict[str, Any],
    client: AsyncJevClient,
) -> LensSelection:
    """Ask ``lens/v1`` which catalog families apply to this PR.

    Args:
        state: Structured PR payload (diff text, paths).
        client: Pinned Jev client (recorded transport in CI).

    Returns:
        LensSelection: Catalog ids Jev marked ``apply``. ``source`` is ``jev``,
        or ``triggers`` when the client skips (D4).
    """
    pack = lens_pack()
    result = await client.call(
        state=state,
        pack_id=pack.pack_id,
        unit_id="pr",
        questions=build_system_one_questions(pack),
    )
    if result.skipped or result.response is None:
        return LensSelection(
            pack_id=pack.pack_id,
            lens_ids=(),
            source="triggers",
            skipped=True,
            reason=result.reason,
        )
    response = result.response
    catalog = _live_lens_definitions()
    selected: list[str] = []
    confidences: list[float] = []
    for lens_id in catalog:
        answer = response.answers.get(lens_id)
        if isinstance(answer, ChoiceAnswer) and answer.choice == "apply":
            selected.append(lens_id)
            confidences.append(float(answer.confidence))
    confidence = min(confidences) if confidences else None
    logger.info(
        "jev lens select pack_id={} lenses={} confidence={}",
        pack.pack_id,
        selected,
        confidence,
    )
    return LensSelection(
        pack_id=pack.pack_id,
        lens_ids=tuple(selected),
        source="jev",
        confidence=confidence,
    )


def select_lenses_or_fallback(
    *,
    enabled: bool,
    trigger_ids: Sequence[str] = (),
    confidence: float | None = None,
    selected_ids: Sequence[str] | None = None,
    settings: RepoSettings | None = None,
) -> LensSelection:
    """Choose Jev lenses or today's trigger matching.

    Disabled Jev, or confidence below the ``lens/v1`` floor, returns the
    trigger-matched ids. A wrong Jev answer must not hide a trigger match:
    when Jev is used, trigger ids are kept and Jev may only add lenses.

    Args:
        enabled: ``jev.enabled`` toggle (D4).
        trigger_ids: Lenses today's trigger matching already selected.
        confidence: Calibrated confidence for the Jev selection, if any.
        selected_ids: Lens ids Jev marked ``apply``.
        settings: Loaded repo settings. When omitted, falls back to defaults.

    Returns:
        LensSelection: ``source`` is ``triggers`` or ``jev``.
    """
    floor = _lens_confidence_floor(settings)
    if not enabled or confidence is None or confidence < floor:
        return LensSelection(
            pack_id=LENS_PACK_ID,
            lens_ids=tuple(trigger_ids),
            source="triggers",
            confidence=confidence,
        )
    # Union: Jev may add a wasted lens pass; it cannot drop a trigger match.
    merged = tuple(dict.fromkeys([*trigger_ids, *(selected_ids or ())]))
    return LensSelection(
        pack_id=LENS_PACK_ID,
        lens_ids=merged,
        source="jev",
        confidence=confidence,
    )


def _lens_confidence_floor(settings: RepoSettings | None = None) -> float:
    if settings is None:
        from mergecraft.config.settings import default_settings

        settings = default_settings()
    value = settings.jev.thresholds.get("lens/v1.likely")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return LIKELY_CONFIDENCE_FLOOR


__all__ = [
    "LensQuestionPack",
    "LensSelection",
    "QuestionPack",
    "QuestionSpec",
    "align_pack",
    "claim_pack",
    "evidence_pack",
    "get_pack",
    "lens_pack",
    "select_lenses",
    "select_lenses_or_fallback",
    "unit_pack",
]
