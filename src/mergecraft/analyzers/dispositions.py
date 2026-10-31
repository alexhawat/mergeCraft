"""Disposition ledger — every raw analyzer hit ends with one recorded disposition (#941).

A raw hit can disappear between a tool's output and the published review: out-of-hunk
scoping, withdrawn memory, baseline suppression, clustering, the generated-file policy
and the verifier each remove or merge hits, and before this ledger no single place
answered "was this hit kept or dropped, and why?". A bug in any stage silently removed
real findings and the gate, which only reads survivors, could not see it.

The ledger gives every raw hit a stable ``hit_id`` at parse time. A stage that removes
or merges a hit records ``{hit_id, disposition, stage, reason, ref}`` against it (the
reason is required and non-empty — there is no default). When the pipeline finishes,
:meth:`DispositionLedger.close` marks the survivors ``kept``; a raw hit with no entry
is an *orphan*, and the evidence packet turns a non-empty orphan set into an
inconclusive run that names them.

Module: mergecraft.analyzers.dispositions
Depends: mergecraft.analyzers.finding, pydantic, loguru

Exports:
    Classes:
        DispositionEntry — One hit's disposition at one stage, with a required reason.
        SuppressionAuditRow — One persisted baseline-suppression decision.
        DispositionCounts — Raw/kept/merged/downgraded totals and drops per stage.
        DispositionSummary — Counts plus the orphaned hit ids.
        DispositionLedger — The mutable ledger one pipeline run appends to.
    Functions:
        hit_id_for — Stable identity of a raw hit (tool, rule, path, lines, message hash).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mergecraft.analyzers.finding import Finding

Disposition = Literal[
    "kept",
    "merged",
    "downgraded",
    "dropped:out_of_scope",
    "dropped:baseline",
    "dropped:withdrawn",
    "dropped:generated",
    "dropped:verifier",
]

#: Display order of the per-stage drop counts in the pre-merge Analyzers row.
_STAGE_ORDER = (
    "out_of_scope",
    "generated",
    "withdrawn",
    "baseline",
    "cluster",
    "dedupe",
    "verifier",
)


def hit_id_for(finding: Finding) -> str:
    """Return the stable identity of a raw hit.

    Derived from the fields a stage cannot legitimately change — tool, rule, path,
    line range and a hash of the message — so it survives ``model_copy`` annotations
    (``introduced_by_pr``, severity) and re-clustering. Two rows with the same
    identity are the same hit.
    """
    message_digest = hashlib.sha256(finding.message.encode("utf-8")).hexdigest()[:16]
    material = "\0".join(
        [
            finding.tool,
            finding.rule_id,
            finding.path,
            str(finding.start_line),
            str(finding.end_line),
            message_digest,
        ]
    )
    return "h-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class DispositionEntry(BaseModel):
    """One hit's disposition at one stage. The reason is required and non-blank."""

    model_config = ConfigDict(extra="forbid")

    hit_id: str
    disposition: Disposition
    stage: str
    reason: str
    ref: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "a disposition requires a non-empty reason"
            raise ValueError(msg)
        return value


class SuppressionAuditRow(BaseModel):
    """One baseline-suppression decision, persisted instead of only logged."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    decision: Literal["suppressed", "reported"]
    reason: str


class DispositionCounts(BaseModel):
    """Totals over the raw set. ``dropped_by_stage`` is keyed by the dropping stage."""

    model_config = ConfigDict(extra="forbid")

    raw: int = 0
    kept: int = 0
    merged: int = 0
    downgraded: int = 0
    dropped_by_stage: dict[str, int] = Field(default_factory=dict)


class DispositionSummary(DispositionCounts):
    """Counts plus the hit ids that ended with no disposition at all."""

    orphaned: list[str] = Field(default_factory=list)


class DispositionLedger:
    """The closed ledger one analyzer run appends to.

    Mutable and single-writer per run. Recording is total and non-throwing for hits it
    does not know (a stage may be handed rows that never came from the raw set), but a
    blank reason is a programming error and raises.
    """

    def __init__(self) -> None:
        # hit_id -> (tool, fingerprint), in registration order.
        self._raw: dict[str, tuple[str, str]] = {}
        self._entries: dict[str, DispositionEntry] = {}
        self._severity: dict[str, str] = {}
        self._audit: list[SuppressionAuditRow] = []

    # ------------------------------------------------------------------ registration

    def register_raw(self, findings: Iterable[Finding]) -> list[str]:
        """Register the raw hits, before any stage runs. Returns the registered ids."""
        ids: list[str] = []
        for finding in findings:
            hit_id = hit_id_for(finding)
            if hit_id not in self._raw:
                self._raw[hit_id] = (finding.tool, finding.fingerprint)
            ids.append(hit_id)
        return ids

    # ------------------------------------------------------------------ recording

    def record(
        self,
        hit_id: str,
        disposition: Disposition,
        *,
        stage: str,
        reason: str,
        ref: str | None = None,
    ) -> DispositionEntry:
        """Record a hit's disposition. A blank reason raises; an earlier terminal wins.

        ``kept`` and ``downgraded`` are not final — a later stage (the verifier) may
        supersede them. A hit already ``merged`` or ``dropped:*`` keeps its first entry.
        """
        entry = DispositionEntry(
            hit_id=hit_id, disposition=disposition, stage=stage, reason=reason, ref=ref
        )
        existing = self._entries.get(hit_id)
        if existing is not None and existing.disposition not in {"kept", "downgraded"}:
            logger.debug(
                "dispositions: {} already {} at {} — ignoring {} at {}",
                hit_id,
                existing.disposition,
                existing.stage,
                disposition,
                stage,
            )
            return existing
        self._entries[hit_id] = entry
        return entry

    def record_dropped(
        self,
        finding: Finding,
        disposition: Disposition,
        *,
        stage: str,
        reason: str,
        ref: str | None = None,
    ) -> None:
        """Record against a finding's hit; a finding outside the raw set is ignored."""
        hit_id = hit_id_for(finding)
        if hit_id not in self._raw:
            logger.debug("dispositions: {} is not a registered raw hit — not recorded", hit_id)
            return
        self.record(hit_id, disposition, stage=stage, reason=reason, ref=ref)

    def add_suppression_audit(
        self, *, fingerprint: str, decision: Literal["suppressed", "reported"], reason: str
    ) -> None:
        """Persist one baseline-suppression decision."""
        self._audit.append(
            SuppressionAuditRow(
                fingerprint=fingerprint,
                decision=decision,
                reason=reason or "no reason recorded",
            )
        )

    def close(
        self,
        survivors: Iterable[Finding],
        *,
        merge_by_fingerprint: bool = False,
    ) -> None:
        """Mark the surviving findings ``kept``; whatever is still unresolved is an orphan.

        A survivor whose identity changed in flight is matched to its raw hit by
        fingerprint when exactly one unresolved hit carries it, so a stage that
        rewrites a row cannot manufacture a false orphan. ``merge_by_fingerprint``
        additionally explains an unresolved hit whose fingerprint a survivor carries
        (two raw rows collapsed by the evidence store's dedupe key) as ``merged``.
        """
        survivor_list = list(survivors)
        for survivor in survivor_list:
            hit_id = hit_id_for(survivor)
            if hit_id not in self._raw:
                unresolved = [
                    raw_id
                    for raw_id, (_tool, fingerprint) in self._raw.items()
                    if fingerprint == survivor.fingerprint and raw_id not in self._entries
                ]
                if len(unresolved) != 1:
                    continue
                hit_id = unresolved[0]
            self._severity[hit_id] = survivor.severity
            if hit_id in self._entries:
                continue
            self._entries[hit_id] = DispositionEntry(
                hit_id=hit_id,
                disposition="kept",
                stage="placement",
                reason="survived every stage; published inline, in the mechanical section, "
                "or deferred",
                ref=survivor.fingerprint,
            )
        if merge_by_fingerprint:
            by_fingerprint = {survivor.fingerprint: survivor for survivor in survivor_list}
            for hit_id, (_tool, fingerprint) in self._raw.items():
                if hit_id in self._entries or fingerprint not in by_fingerprint:
                    continue
                self._entries[hit_id] = DispositionEntry(
                    hit_id=hit_id,
                    disposition="merged",
                    stage="dedupe",
                    reason=f"collapsed into the surviving hit with fingerprint {fingerprint}",
                    ref=fingerprint,
                )

    def record_verifier(
        self,
        fingerprint: str,
        *,
        verdict: str,
        reason: str,
        new_severity: str | None,
    ) -> list[str]:
        """Apply a verifier verdict to the surviving hit with ``fingerprint``.

        ``drop`` supersedes ``kept`` with ``dropped:verifier`` (the verifier's reason is
        recorded against the hit, not only in learnings); ``downgrade`` supersedes it
        with ``downgraded`` naming the old and new severity; ``confirm`` changes
        nothing. Returns the affected hit ids.
        """
        affected: list[str] = []
        for hit_id, entry in list(self._entries.items()):
            if entry.disposition not in {"kept", "downgraded"} or entry.ref != fingerprint:
                continue
            if verdict == "drop":
                self._entries[hit_id] = DispositionEntry(
                    hit_id=hit_id,
                    disposition="dropped:verifier",
                    stage="verifier",
                    reason=f"verifier dropped the finding: {reason or 'no reason given'}",
                    ref=fingerprint,
                )
            elif verdict == "downgrade":
                old = self._severity.get(hit_id, "unknown")
                self._entries[hit_id] = DispositionEntry(
                    hit_id=hit_id,
                    disposition="downgraded",
                    stage="verifier",
                    reason=(
                        f"verifier downgraded {old} -> {new_severity or 'unspecified'}: "
                        f"{reason or 'no reason given'}"
                    ),
                    ref=fingerprint,
                )
                if new_severity:
                    self._severity[hit_id] = new_severity
            else:
                continue
            affected.append(hit_id)
        return affected

    def merge(self, other: DispositionLedger) -> None:
        """Fold another run's ledger in (retained segments of one session)."""
        for hit_id, raw in other._raw.items():
            self._raw.setdefault(hit_id, raw)
        for hit_id, entry in other._entries.items():
            self._entries[hit_id] = entry
        self._severity.update(other._severity)
        seen = {(row.fingerprint, row.decision, row.reason) for row in self._audit}
        for row in other._audit:
            if (row.fingerprint, row.decision, row.reason) not in seen:
                self._audit.append(row)

    # ------------------------------------------------------------------ reading

    def entry_for(self, finding: Finding) -> DispositionEntry | None:
        """The recorded disposition for a finding's hit, or ``None``."""
        return self._entries.get(hit_id_for(finding))

    def entries(self) -> list[DispositionEntry]:
        """One terminal entry per resolved hit, in registration order."""
        return [self._entries[hit_id] for hit_id in self._raw if hit_id in self._entries]

    @property
    def suppression_audit(self) -> list[SuppressionAuditRow]:
        """The persisted baseline-suppression rows."""
        return list(self._audit)

    def orphans(self) -> list[str]:
        """Raw hit ids with no disposition — the closure check's failure set."""
        return [hit_id for hit_id in self._raw if hit_id not in self._entries]

    def summary(self) -> DispositionSummary:
        """Counts over the raw set; ``orphaned`` names what no stage accounted for."""
        counts = DispositionSummary(raw=len(self._raw), orphaned=self.orphans())
        dropped: dict[str, int] = {}
        for entry in self.entries():
            if entry.disposition == "kept":
                counts.kept += 1
            elif entry.disposition == "merged":
                counts.merged += 1
            elif entry.disposition == "downgraded":
                counts.downgraded += 1
            else:
                dropped[entry.stage] = dropped.get(entry.stage, 0) + 1
        counts.dropped_by_stage = dropped
        return counts

    def row_summary(self) -> str:
        """The pre-merge Analyzers fragment: ``ruff 14 raw → 3 kept (9 out_of_scope, 2 baseline)``."""
        parts: list[str] = []
        tools = list(dict.fromkeys(tool for tool, _fp in self._raw.values()))
        for tool in sorted(tools):
            ids = [hit_id for hit_id, (hit_tool, _fp) in self._raw.items() if hit_tool == tool]
            kept = 0
            merged = 0
            dropped: dict[str, int] = {}
            for hit_id in ids:
                entry = self._entries.get(hit_id)
                if entry is None:
                    dropped["orphaned"] = dropped.get("orphaned", 0) + 1
                elif entry.disposition in {"kept", "downgraded"}:
                    kept += 1
                elif entry.disposition == "merged":
                    merged += 1
                else:
                    dropped[entry.stage] = dropped.get(entry.stage, 0) + 1
            details = [
                f"{dropped[stage]} {stage}"
                for stage in sorted(dropped, key=_stage_rank)
                if dropped[stage]
            ]
            if merged:
                details.append(f"{merged} merged")
            suffix = f" ({', '.join(details)})" if details else ""
            parts.append(f"{tool} {len(ids)} raw → {kept} kept{suffix}")
        return "; ".join(parts)


def _stage_rank(stage: str) -> tuple[int, str]:
    if stage in _STAGE_ORDER:
        return (_STAGE_ORDER.index(stage), stage)
    return (len(_STAGE_ORDER), stage)


__all__ = [
    "Disposition",
    "DispositionCounts",
    "DispositionEntry",
    "DispositionLedger",
    "DispositionSummary",
    "SuppressionAuditRow",
    "hit_id_for",
]
