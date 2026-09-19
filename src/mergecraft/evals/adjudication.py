"""Configurable adjudication of eval corpus labels (#736, #738).

Three adjudicator kinds may assign ground-truth labels to eval cases: a
human, the Jev gate, or a general LLM. Which of them *may* run is repo
configuration; what a resulting label *entitles a caller to claim* is not.
Those two questions are deliberately answered by different code paths here,
so that enabling an adjudicator can never by itself upgrade a calibration
claim.

The corpus this guards is agent-seeded. Scoring an LLM judge against labels
the same model produced is circular, which is why the labels were previously
restricted to human provenance. The restriction that actually matters is
**independence from the producer**, not humanity: an adjudicator may not
score labels its own pinned model emitted. ``assert_independent`` enforces
that regardless of configuration.

Module: mergecraft.evals.adjudication
Depends: collections.abc, datetime, typing, pydantic, loguru

Exports:
    IndependenceTier: How independent an adjudicator is of the corpus.
    AdjudicatorKind: ``human`` | ``jev`` | ``llm``.
    AdjudicatorNotApproved: Raised when configuration does not approve a kind.
    SelfAdjudicationRefused: Raised when an adjudicator would score itself.
    AdjudicationRecord: Who adjudicated one label, with what, and when.
    approved_kinds: The adjudicator kinds configuration approves.
    resolve_adjudicator: Approve a requested kind or raise.
    assert_independent: Refuse self-adjudication irrespective of config.
    provenance_for: Derive the corpus ``provenance`` string for a record.
    tier_for_provenance: Map a stored ``provenance`` string to its tier.
    CalibrationStatus: Whether a label set may back a calibration claim.
    calibration_status: Partition labels by tier and decide eligibility.
    adjudicate_label: Approve, check independence, and build one record.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

IndependenceTier = Literal["independent", "model", "none"]
AdjudicatorKind = Literal["human", "jev", "llm"]

#: Every adjudicator kind, as a typed tuple for iteration.
_ALL_KINDS: tuple[AdjudicatorKind, ...] = ("human", "jev", "llm")

#: Name-to-literal lookup so a configured string narrows without a cast.
_TIER_BY_NAME: dict[str, IndependenceTier] = {
    "independent": "independent",
    "model": "model",
    "none": "none",
}

#: Ordering used to compare a label's tier against the configured bar.
_TIER_RANK: dict[IndependenceTier, int] = {"none": 0, "model": 1, "independent": 2}

#: ``provenance`` strings written into baseline rows, by adjudicator kind.
_PROVENANCE_BY_KIND: dict[AdjudicatorKind, str] = {
    "human": "human",
    "jev": "jev-adjudicated",
    "llm": "llm-adjudicated",
}

#: Reverse mapping plus the legacy strings already present in the corpus.
_TIER_BY_PROVENANCE: dict[str, IndependenceTier] = {
    "human": "independent",
    "jev-adjudicated": "model",
    "llm-adjudicated": "model",
    "agent-seeded": "none",
    "": "none",
}


class AdjudicatorNotApproved(Exception):
    """A requested adjudicator kind is not approved by repo configuration."""


class SelfAdjudicationRefused(Exception):
    """An adjudicator would score labels its own pinned model produced."""


class AdjudicationRecord(BaseModel):
    """Who adjudicated one label, with which model, and when.

    Attached to a label so ``provenance`` is derived rather than asserted by
    hand. ``produced_by`` names the model that emitted the label under
    adjudication, and is what ``assert_independent`` compares against.
    """

    # Internal record: only the derived ``provenance`` string is persisted,
    # so no camelCase wire alias is needed here.
    model_config = ConfigDict(extra="forbid")

    adjudicated_by: AdjudicatorKind
    model: str = ""
    produced_by: str = ""
    independence: IndependenceTier = "none"
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def approved_kinds(settings: Mapping[str, object] | None) -> frozenset[AdjudicatorKind]:
    """Return the adjudicator kinds the given ``adjudication`` block approves.

    Args:
        settings: The ``adjudicators`` mapping from repo configuration, or
            ``None`` when the block is absent.

    Returns:
        frozenset[AdjudicatorKind]: Approved kinds; empty when none are.
    """
    if not settings:
        return frozenset()
    approved: set[AdjudicatorKind] = set()
    for kind in _ALL_KINDS:
        entry = settings.get(kind)
        enabled = getattr(entry, "enabled", None)
        if enabled is None and isinstance(entry, Mapping):
            enabled = entry.get("enabled")
        if enabled:
            approved.add(kind)
    return frozenset(approved)


def resolve_adjudicator(
    kind: AdjudicatorKind,
    *,
    settings: Mapping[str, object] | None,
) -> IndependenceTier:
    """Approve ``kind`` against configuration and return its independence tier.

    Args:
        kind: The adjudicator the caller wants to run.
        settings: The ``adjudicators`` mapping from repo configuration.

    Returns:
        IndependenceTier: The configured tier for ``kind``.

    Raises:
        AdjudicatorNotApproved: When configuration does not approve ``kind``.
    """
    if kind not in approved_kinds(settings):
        msg = (
            f"adjudicator {kind!r} is not approved — enable "
            f"adjudication.adjudicators.{kind}.enabled in .mergecraft/config.yaml"
        )
        raise AdjudicatorNotApproved(msg)
    entry = (settings or {}).get(kind)
    tier = getattr(entry, "independence", None)
    if tier is None and isinstance(entry, Mapping):
        tier = entry.get("independence")
    return _TIER_BY_NAME.get(str(tier), "none")


def assert_independent(record: AdjudicationRecord) -> None:
    """Refuse an adjudication that cannot be shown independent of the label.

    Configuration cannot waive this: a model scoring its own output yields a
    circular label no matter which block approved the run.

    Fails closed on missing identity. A model adjudicator with no ``model`` or
    no ``produced_by`` is refused rather than allowed, because an unknown
    producer cannot be *shown* to differ from the adjudicator — permitting it
    would let the invariant be bypassed by omitting an argument. A human
    adjudicator carries no model identity and is exempt.

    Args:
        record: The adjudication about to be recorded.

    Raises:
        SelfAdjudicationRefused: When adjudicator and producer are the same
            model, or when a model adjudicator's identities are unknown.
    """
    if record.adjudicated_by == "human":
        return
    adjudicator = record.model.strip()
    producer = record.produced_by.strip()
    if not adjudicator or not producer:
        msg = (
            f"refusing {record.adjudicated_by} adjudication without auditable "
            "identities: both the adjudicating model and the model that produced "
            "the label are required, so independence can be checked rather than "
            "assumed"
        )
        raise SelfAdjudicationRefused(msg)
    if adjudicator == producer:
        msg = (
            f"refusing self-adjudication: {adjudicator!r} produced this label "
            "and cannot also adjudicate it"
        )
        raise SelfAdjudicationRefused(msg)


def provenance_for(record: AdjudicationRecord) -> str:
    """Derive the corpus ``provenance`` string a record should write."""
    return _PROVENANCE_BY_KIND[record.adjudicated_by]


def tier_for_provenance(provenance: str) -> IndependenceTier:
    """Map a stored ``provenance`` string to its independence tier.

    Unknown strings resolve to ``none`` so an unrecognised label can never
    silently satisfy a calibration bar.
    """
    return _TIER_BY_PROVENANCE.get(provenance.strip(), "none")


class CalibrationStatus(BaseModel):
    """Whether a set of labels may back a calibration claim."""

    model_config = ConfigDict(extra="forbid")

    counts: dict[str, int] = Field(default_factory=dict)
    required: IndependenceTier = "independent"
    eligible: bool = False
    reason: str = ""


def calibration_status(
    provenances: Iterable[str],
    *,
    required: IndependenceTier = "independent",
) -> CalibrationStatus:
    """Partition labels by tier and decide whether they meet ``required``.

    A label set is eligible only when it is non-empty and **every** label
    meets the bar. One agent-seeded row is enough to make a corpus-wide
    calibration claim indefensible, so this deliberately does not take a
    majority or a ratio.

    Args:
        provenances: The ``provenance`` string of each label considered.
        required: Minimum tier every label must meet.

    Returns:
        CalibrationStatus: Per-tier counts, eligibility, and a stated reason.
    """
    counts: dict[IndependenceTier, int] = {"independent": 0, "model": 0, "none": 0}
    for provenance in provenances:
        counts[tier_for_provenance(provenance)] += 1
    total = sum(counts.values())
    bar = _TIER_RANK[required]
    below = sum(count for tier, count in counts.items() if _TIER_RANK[tier] < bar)
    if total == 0:
        reason = "no labels to score"
    elif below:
        reason = f"{below} of {total} labels below the {required!r} bar"
    else:
        reason = f"all {total} labels meet the {required!r} bar"
    eligible = total > 0 and below == 0
    if not eligible:
        logger.debug("calibration claim withheld — {}", reason)
    return CalibrationStatus(
        counts={str(tier): count for tier, count in counts.items()},
        required=required,
        eligible=eligible,
        reason=reason,
    )


def adjudicate_label(
    kind: AdjudicatorKind,
    *,
    settings: Mapping[str, object] | None,
    model: str = "",
    produced_by: str = "",
) -> AdjudicationRecord:
    """Approve, check independence, and build the record for one label.

    This is the single entry point a label-writing path must use. It is what
    makes ``enabled`` and the self-adjudication ban real rather than advisory:
    a caller that bypasses it can still write any ``provenance`` string it
    likes, so writers go through here.

    Args:
        kind: The adjudicator assigning the label.
        settings: The ``adjudicators`` mapping from repo configuration.
        model: Pinned model id of the adjudicator, empty for a human.
        produced_by: Model that produced the label being adjudicated.

    Returns:
        AdjudicationRecord: The record to attach, carrying the resolved tier.

    Raises:
        AdjudicatorNotApproved: Configuration does not approve ``kind``.
        SelfAdjudicationRefused: ``model`` produced the label itself.
    """
    tier = resolve_adjudicator(kind, settings=settings)
    record = AdjudicationRecord(
        adjudicated_by=kind,
        model=model,
        produced_by=produced_by,
        independence=tier,
    )
    assert_independent(record)
    logger.info("label adjudicated by {} at tier {}", kind, tier)
    return record


__all__ = [
    "AdjudicationRecord",
    "AdjudicatorKind",
    "AdjudicatorNotApproved",
    "CalibrationStatus",
    "IndependenceTier",
    "SelfAdjudicationRefused",
    "adjudicate_label",
    "approved_kinds",
    "assert_independent",
    "calibration_status",
    "provenance_for",
    "resolve_adjudicator",
    "tier_for_provenance",
]
