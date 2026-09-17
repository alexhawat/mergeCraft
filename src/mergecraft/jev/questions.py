"""Versioned Jev question packs. ``unit/v1`` (J3), ``evidence/v1`` and ``claim/v1`` (J4).

J5 packs stay registered by id only so ``get_pack`` can name every versioned
pack. Their questions land with that wave.

Exports:
    QuestionPack: Versioned pack with typed questions.
    unit_pack: Per-hunk Choice + Score + Noul battery.
    evidence_pack: Citation-check battery per finding (T12).
    claim_pack: Prose-claim battery for plan 21 D6 rules 1, 3, 4.
    align_pack: Stub ``align/v1`` (J5).
    lens_pack: Stub ``lens/v1`` (J5).
    get_pack: Lookup by versioned pack id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.jev.types import CLAIM_PACK_ID, EVIDENCE_PACK_ID, UNIT_PACK_ID, JevError
from mergecraft.review_taxonomy import FINDING_SEVERITIES

QuestionKind = Literal["choice", "score", "noul"]

_SEVERITY_LEGEND: dict[int, str] = {
    0: "Trivial — nitpick; body-only and never a merge blocker",
    1: "Minor — real issue that does not block the merge",
    2: "Major — blocking defect (repo Critical/Major grade)",
    3: "Critical — highest-grade blocking defect",
}

# Repo taxonomy names are the Score legend labels (axis is Trivial → Critical).
assert set(FINDING_SEVERITIES) == {"Trivial", "Minor", "Major", "Critical"}


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
    """Pack ``align/v1`` — questions land in J5."""
    return QuestionPack(pack_id="align/v1")


def lens_pack() -> QuestionPack:
    """Pack ``lens/v1`` — live catalog read lands in J5."""
    return QuestionPack(pack_id="lens/v1")


_PACK_FACTORIES = {
    UNIT_PACK_ID: unit_pack,
    EVIDENCE_PACK_ID: evidence_pack,
    CLAIM_PACK_ID: claim_pack,
    "align/v1": align_pack,
    "lens/v1": lens_pack,
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


__all__ = [
    "QuestionPack",
    "QuestionSpec",
    "align_pack",
    "claim_pack",
    "evidence_pack",
    "get_pack",
    "lens_pack",
    "unit_pack",
]
