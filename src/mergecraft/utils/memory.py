"""Repo-scoped memory: feedback ledger, negative memory, staleness helpers (DG7).

Feedback capture records accepted / dismissed / disputed outcomes keyed by finding
fingerprint. Negative memory stores bounded ``do not flag X when Y`` rules with
an audit trail. Staleness helpers apply TTL/recency weighting and surface
contradicting memories.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

MEMORY_FILE_NAME = "memory.json"
FEEDBACK_FILE_NAME = "feedback.json"
DEFAULT_MAX_NEGATIVE_RULES = 64
DEFAULT_ACTIVE_MEMORY_TTL_DAYS = 365


class FeedbackOutcome(StrEnum):
    """Developer feedback outcome for a finding fingerprint (G14)."""

    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    DISPUTED = "disputed"


class FeedbackRecord(BaseModel):
    """One feedback ledger entry keyed by finding fingerprint."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(min_length=1)
    outcome: FeedbackOutcome
    reason: str = Field(min_length=1)
    pr_number: int | None = None
    recorded_at: datetime


class FeedbackStore(BaseModel):
    """On-disk feedback ledger."""

    model_config = ConfigDict(extra="forbid")

    entries: dict[str, FeedbackRecord] = Field(default_factory=dict)

    def list_entries(self) -> list[FeedbackRecord]:
        return list(self.entries.values())


class NegativeMemoryRule(BaseModel):
    """A bounded negative-memory suppression rule."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1)
    when: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    recorded_at: datetime


class NegativeMemoryAuditEntry(BaseModel):
    """Audit record for a negative-memory rule (convention 7)."""

    model_config = ConfigDict(extra="forbid")

    pattern: str
    when: str
    reason: str
    recorded_at: datetime
    evicted: bool = False


class NegativeMemoryPayload(BaseModel):
    """Serialised negative-memory store."""

    model_config = ConfigDict(extra="forbid")

    rules: list[NegativeMemoryRule] = Field(default_factory=list)
    audit: list[NegativeMemoryAuditEntry] = Field(default_factory=list)


@dataclass
class NegativeMemoryApplyResult:
    """Outcome of applying negative memory to a finding batch."""

    reported: list[Finding] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)
    suppression_reasons: dict[str, str] = field(default_factory=dict)


@dataclass
class OverSuppressionReport:
    """Visibility report when negative memory suppresses too much."""

    is_over_suppressed: bool
    suppressed_count: int
    total_count: int
    audit_entries: list[NegativeMemoryAuditEntry]


class MemoryEntry(BaseModel):
    """One repo-scoped memory item with TTL metadata."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    recorded_at: datetime
    ttl_days: int = Field(ge=1)


class MemoryContradiction(BaseModel):
    """Pair of conflicting memory entries."""

    model_config = ConfigDict(extra="forbid")

    left_id: str
    right_id: str
    reason: str


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def record_finding_feedback(
    *,
    store_path: Path,
    fingerprint: str,
    outcome: FeedbackOutcome,
    reason: str,
    pr_number: int | None = None,
    recorded_at: datetime | None = None,
) -> FeedbackRecord:
    """Persist developer feedback for a finding fingerprint (G14)."""
    ts = recorded_at or _now()
    record = FeedbackRecord(
        fingerprint=fingerprint,
        outcome=outcome,
        reason=reason.strip(),
        pr_number=pr_number,
        recorded_at=ts,
    )
    store = load_feedback_store(store_path)
    store.entries[fingerprint] = record
    _persist_feedback_store(store_path, store)
    return record


def load_feedback_store(store_path: Path) -> FeedbackStore:
    """Load the feedback ledger from disk."""
    data = _read_json(store_path)
    entries: dict[str, FeedbackRecord] = {}
    raw_entries = data.get("entries", {})
    if isinstance(raw_entries, dict):
        for key, item in raw_entries.items():
            if not isinstance(item, dict):
                continue
            try:
                ts_raw = item.get("recorded_at")
                ts = _parse_dt(str(ts_raw)) if ts_raw else _now()
                entries[str(key)] = FeedbackRecord(
                    fingerprint=str(item.get("fingerprint", key)),
                    outcome=FeedbackOutcome(str(item["outcome"])),
                    reason=str(item["reason"]),
                    pr_number=item.get("pr_number"),
                    recorded_at=ts,
                )
            except (KeyError, ValueError, ValidationError):  # fmt: skip
                continue
    return FeedbackStore(entries=entries)


def _persist_feedback_store(store_path: Path, store: FeedbackStore) -> None:
    payload = {
        "entries": {
            fp: {
                "fingerprint": rec.fingerprint,
                "outcome": rec.outcome.value,
                "reason": rec.reason,
                "pr_number": rec.pr_number,
                "recorded_at": rec.recorded_at.astimezone(UTC).isoformat(),
            }
            for fp, rec in store.entries.items()
        }
    }
    _write_json(store_path, payload)


def get_finding_feedback(*, store_path: Path, fingerprint: str) -> FeedbackRecord | None:
    """Return the latest feedback record for ``fingerprint``, if any."""
    store = load_feedback_store(store_path)
    return store.entries.get(fingerprint)


class NegativeMemoryStore:
    """Bounded negative-memory rule store with audit trail."""

    def __init__(self, *, path: Path, max_entries: int = DEFAULT_MAX_NEGATIVE_RULES) -> None:
        self.path = path
        self.max_entries = max(1, max_entries)
        self._payload = self._load()

    def _load(self) -> NegativeMemoryPayload:
        data = _read_json(self.path)
        rules: list[NegativeMemoryRule] = []
        audit: list[NegativeMemoryAuditEntry] = []
        for item in data.get("rules", []) if isinstance(data.get("rules"), list) else []:
            if not isinstance(item, dict):
                continue
            ts = _parse_dt(str(item.get("recorded_at", _now().isoformat())))
            rules.append(
                NegativeMemoryRule(
                    pattern=str(item["pattern"]),
                    when=str(item["when"]),
                    reason=str(item["reason"]),
                    recorded_at=ts,
                )
            )
        for item in data.get("audit", []) if isinstance(data.get("audit"), list) else []:
            if not isinstance(item, dict):
                continue
            ts = _parse_dt(str(item.get("recorded_at", _now().isoformat())))
            audit.append(
                NegativeMemoryAuditEntry(
                    pattern=str(item["pattern"]),
                    when=str(item["when"]),
                    reason=str(item["reason"]),
                    recorded_at=ts,
                    evicted=bool(item.get("evicted", False)),
                )
            )
        return NegativeMemoryPayload(rules=rules, audit=audit)

    def _save(self) -> None:
        payload = {
            "rules": [
                {
                    "pattern": rule.pattern,
                    "when": rule.when,
                    "reason": rule.reason,
                    "recorded_at": rule.recorded_at.astimezone(UTC).isoformat(),
                }
                for rule in self._payload.rules
            ],
            "audit": [
                {
                    "pattern": entry.pattern,
                    "when": entry.when,
                    "reason": entry.reason,
                    "recorded_at": entry.recorded_at.astimezone(UTC).isoformat(),
                    "evicted": entry.evicted,
                }
                for entry in self._payload.audit
            ],
        }
        _write_json(self.path, payload)

    def add_rule(self, *, pattern: str, when: str, reason: str) -> NegativeMemoryRule:
        """Append a negative-memory rule, evicting oldest active rules when over cap."""
        ts = _now()
        rule = NegativeMemoryRule(
            pattern=pattern.strip(), when=when.strip(), reason=reason.strip(), recorded_at=ts
        )
        self._payload.rules.append(rule)
        self._payload.audit.append(
            NegativeMemoryAuditEntry(
                pattern=rule.pattern,
                when=rule.when,
                reason=rule.reason,
                recorded_at=ts,
            )
        )
        while len(self._payload.rules) > self.max_entries:
            evicted = self._payload.rules.pop(0)
            self._payload.audit.append(
                NegativeMemoryAuditEntry(
                    pattern=evicted.pattern,
                    when=evicted.when,
                    reason=evicted.reason,
                    recorded_at=evicted.recorded_at,
                    evicted=True,
                )
            )
        self._save()
        return rule

    def list_rules(self) -> list[NegativeMemoryRule]:
        return list(self._payload.rules)

    def audit_trail(self) -> list[NegativeMemoryAuditEntry]:
        return list(self._payload.audit)


def _match_when(*, when: str, path: str, repo_root: Path) -> bool:
    lowered = when.strip().lower()
    norm_path = path.replace("\\", "/")
    if lowered == "file is generated":
        return "generated" in norm_path.lower()
    if lowered.endswith("__init__.py") or "ends with __init__.py" in lowered:
        return norm_path.endswith("__init__.py")
    if lowered.startswith("path ends with "):
        suffix = lowered.removeprefix("path ends with ").strip()
        return norm_path.endswith(suffix)
    try:
        rel = str(Path(norm_path).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        rel = norm_path
    return lowered in rel.lower()


def _match_pattern(*, pattern: str, message: str) -> bool:
    msg = message.lower()
    pat = pattern.lower()
    if "any lint" in pat and "lint" in msg:
        return True
    return pat in msg


def _rule_matches_finding(*, rule: NegativeMemoryRule, finding: Finding, repo_root: Path) -> bool:
    if not _match_when(when=rule.when, path=finding.path, repo_root=repo_root):
        return False
    return _match_pattern(pattern=rule.pattern, message=finding.message)


def apply_negative_memory(
    *,
    findings: list[Finding],
    store: NegativeMemoryStore,
    repo_root: Path,
) -> NegativeMemoryApplyResult:
    """Apply negative-memory rules, returning reported vs suppressed findings."""
    reported: list[Finding] = []
    suppressed: list[Finding] = []
    reasons: dict[str, str] = {}
    rules = store.list_rules()
    for finding in findings:
        matched_reason: str | None = None
        for rule in rules:
            if _rule_matches_finding(rule=rule, finding=finding, repo_root=repo_root):
                matched_reason = rule.reason
                break
        if matched_reason is not None:
            suppressed.append(finding)
            reasons[finding.fingerprint] = matched_reason
        else:
            reported.append(finding)
    return NegativeMemoryApplyResult(
        reported=reported,
        suppressed=suppressed,
        suppression_reasons=reasons,
    )


def detect_over_suppression(
    *,
    findings: list[Finding],
    store: NegativeMemoryStore,
    repo_root: Path,
    threshold_ratio: float,
) -> OverSuppressionReport:
    """Flag when negative memory suppresses more than ``threshold_ratio`` of findings."""
    result = apply_negative_memory(findings=findings, store=store, repo_root=repo_root)
    total = len(findings)
    suppressed_count = len(result.suppressed)
    ratio = (suppressed_count / total) if total else 0.0
    return OverSuppressionReport(
        is_over_suppressed=ratio >= threshold_ratio and total > 0,
        suppressed_count=suppressed_count,
        total_count=total,
        audit_entries=store.audit_trail(),
    )


def _age_days(*, recorded_at: datetime, now: datetime) -> float:
    delta = now - recorded_at.astimezone(UTC)
    return max(0.0, delta.total_seconds() / 86400.0)


def apply_recency_weighting(
    entries: list[MemoryEntry],
    *,
    now: datetime | None = None,
) -> list[tuple[MemoryEntry, float]]:
    """Drop expired entries (weight 0) and weight survivors by TTL urgency."""
    ts = now or _now()
    weighted: list[tuple[MemoryEntry, float]] = []
    for entry in entries:
        age = _age_days(recorded_at=entry.recorded_at, now=ts)
        if age > float(entry.ttl_days):
            weighted.append((entry, 0.0))
            continue
        remaining = max(0.0, float(entry.ttl_days) - age)
        fraction = remaining / float(entry.ttl_days)
        urgency = 1.0 / float(entry.ttl_days)
        weight = fraction * urgency
        weighted.append((entry, weight))
    return weighted


_ALWAYS_RE = re.compile(r"\balways\b", re.IGNORECASE)
_NEVER_RE = re.compile(r"\b(do not|don\'t|never)\b", re.IGNORECASE)
_TOPIC_KEYWORDS = ("sql", "injection", "timeout", "import", "lint", "token", "auth")


def _entry_topics(text: str) -> set[str]:
    lowered = text.lower()
    return {topic for topic in _TOPIC_KEYWORDS if topic in lowered}


def detect_contradicting_memories(
    entries: list[MemoryEntry],
    *,
    now: datetime | None = None,
) -> list[MemoryContradiction]:
    """Surface conflicting active memories instead of silently merging them."""
    ts = now or _now()
    active = [entry for entry, weight in apply_recency_weighting(entries, now=ts) if weight > 0.0]
    contradictions: list[MemoryContradiction] = []
    for left in active:
        for right in active:
            if left.id >= right.id:
                continue
            left_topics = _entry_topics(left.text)
            right_topics = _entry_topics(right.text)
            if not left_topics.intersection(right_topics):
                continue
            left_always = bool(_ALWAYS_RE.search(left.text))
            left_never = bool(_NEVER_RE.search(left.text))
            right_always = bool(_ALWAYS_RE.search(right.text))
            right_never = bool(_NEVER_RE.search(right.text))
            if (left_always and right_never) or (left_never and right_always):
                contradictions.append(
                    MemoryContradiction(
                        left_id=left.id,
                        right_id=right.id,
                        reason=(
                            f"Conflicting guidance on {', '.join(sorted(left_topics))}: "
                            f"'{left.text}' vs '{right.text}'"
                        ),
                    )
                )
    return contradictions


def memory_entry_id(text: str) -> str:
    """Stable id for a memory bullet line."""
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return digest[:12]


def parse_memory_entries_from_learnings(text: str) -> list[dict[str, str]]:
    """Extract active-section memory bullets from a learnings file."""
    from mergecraft.utils.learnings import list_active_entries

    entries: list[dict[str, str]] = []
    for item in list_active_entries(text):
        body = str(item.get("body") or "").strip()
        if not body:
            continue
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            bullet = stripped.lstrip("-* ").strip()
            if not bullet:
                continue
            entries.append({"id": memory_entry_id(bullet), "text": bullet})
    return entries


def _remove_bullet_lines(lines: list[str], memory_id: str) -> list[str]:
    """Drop bullet lines matching ``memory_id`` and orphaned provenance comments."""
    from mergecraft.utils.learnings import parse_provenance_comment

    kept: list[str] = []
    pending_provenance: str | None = None
    for line in lines:
        stripped = line.strip()
        prov = parse_provenance_comment(line)
        if prov is not None:
            pending_provenance = line
            continue
        bullet = stripped.lstrip("-* ").strip() if stripped else ""
        if bullet and memory_entry_id(bullet) == memory_id:
            pending_provenance = None
            continue
        if pending_provenance is not None:
            kept.append(pending_provenance)
            pending_provenance = None
        kept.append(line)
    return kept


def _has_sectioned_learnings_layout(text: str) -> bool:
    from mergecraft.utils.learnings import ACTIVE_SECTION_HEADING, STAGING_SECTION_HEADING

    lowered_targets = {ACTIVE_SECTION_HEADING.lower(), STAGING_SECTION_HEADING.lower()}
    for line in text.splitlines():
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if match and match.group(2).strip().lower() in lowered_targets:
            return True
    return False


def _append_learnings_tail(*, rebuilt: str, tail: str) -> str:
    """Append post-staging markdown (e.g. Withdrawn findings) to a rebuilt file."""
    if not tail.strip():
        return rebuilt
    return rebuilt.rstrip() + "\n\n" + tail.rstrip() + "\n"


def remove_memory_entry_from_learnings(text: str, memory_id: str) -> str:
    """Remove the active-section bullet whose id matches ``memory_id``."""
    from mergecraft.utils.learnings import (
        ACTIVE_SECTION_HEADING,
        STAGING_SECTION_HEADING,
        split_learnings_by_section,
    )

    if not _has_sectioned_learnings_layout(text):
        kept = _remove_bullet_lines(text.splitlines(), memory_id)
        return "\n".join(kept).rstrip() + ("\n" if text.endswith("\n") else "")

    from mergecraft.utils.learnings import tail_after_staging_section

    prefix, active_body, staging_body = split_learnings_by_section(text)
    new_active = "\n".join(_remove_bullet_lines(active_body.splitlines(), memory_id)).strip()
    seed = prefix.rstrip() or "# Learnings"
    staging_part = staging_body.strip()
    rebuilt = (
        f"{seed}\n\n## {ACTIVE_SECTION_HEADING}\n\n{new_active}\n\n"
        f"## {STAGING_SECTION_HEADING}\n\n{staging_part}\n"
    )
    return _append_learnings_tail(rebuilt=rebuilt, tail=tail_after_staging_section(text))


def export_memory_bundle(*, repo: Path) -> dict[str, Any]:
    """Export repo memory artefacts for ``mergecraft memory export``."""
    learnings_path = repo / ".mergecraft" / "learnings.md"
    learnings_text = learnings_path.read_text(encoding="utf-8") if learnings_path.is_file() else ""
    feedback_path = repo / ".mergecraft" / FEEDBACK_FILE_NAME
    memory_path = repo / ".mergecraft" / MEMORY_FILE_NAME
    feedback = load_feedback_store(feedback_path)
    negative = NegativeMemoryStore(path=memory_path) if memory_path.is_file() else None
    return {
        "version": 1,
        "exported_at": _now().astimezone(UTC).isoformat(),
        "entries": parse_memory_entries_from_learnings(learnings_text),
        "feedback": [
            {
                "fingerprint": rec.fingerprint,
                "outcome": rec.outcome.value,
                "reason": rec.reason,
                "pr_number": rec.pr_number,
                "recorded_at": rec.recorded_at.astimezone(UTC).isoformat(),
            }
            for rec in feedback.list_entries()
        ],
        "negative_memory": (
            {
                "rules": [rule.model_dump(mode="json") for rule in negative.list_rules()],
                "audit": [entry.model_dump(mode="json") for entry in negative.audit_trail()],
            }
            if negative is not None
            else {"rules": [], "audit": []}
        ),
    }


def _import_bundle_sidecars(*, repo: Path, bundle: dict[str, Any]) -> None:
    feedback_path = repo / ".mergecraft" / FEEDBACK_FILE_NAME
    store = load_feedback_store(feedback_path)
    for item in bundle.get("feedback", []):
        if not isinstance(item, dict):
            continue
        fp = str(item.get("fingerprint", ""))
        if not fp:
            continue
        ts = _parse_dt(str(item.get("recorded_at", _now().isoformat())))
        store.entries[fp] = FeedbackRecord(
            fingerprint=fp,
            outcome=FeedbackOutcome(str(item["outcome"])),
            reason=str(item["reason"]),
            pr_number=item.get("pr_number"),
            recorded_at=ts,
        )
    _persist_feedback_store(feedback_path, store)
    negative_raw = bundle.get("negative_memory")
    if isinstance(negative_raw, dict):
        memory_path = repo / ".mergecraft" / MEMORY_FILE_NAME
        _write_json(memory_path, negative_raw)


def _collect_new_import_bullets(
    text: str,
    bundle: dict[str, Any],
) -> list[str]:
    existing = {entry["id"] for entry in parse_memory_entries_from_learnings(text)}
    new_bullets: list[str] = []
    for entry in bundle.get("entries", []):
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id", ""))
        bullet = str(entry.get("text", "")).strip()
        if not bullet or entry_id in existing:
            continue
        new_bullets.append(f"- {bullet}")
        existing.add(entry_id)
    return new_bullets


def import_memory_bundle(*, repo: Path, bundle: dict[str, Any]) -> None:
    """Import a memory export bundle into ``repo``."""
    learnings_path = repo / ".mergecraft" / "learnings.md"
    learnings_path.parent.mkdir(parents=True, exist_ok=True)
    if learnings_path.is_file():
        text = learnings_path.read_text(encoding="utf-8")
    else:
        text = "# Learnings\n\n## Active\n\n## Staging\n\n"
    new_bullets = _collect_new_import_bullets(text, bundle)
    if not _has_sectioned_learnings_layout(text):
        lines = text.rstrip().splitlines()
        lines.extend(new_bullets)
        learnings_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    else:
        from mergecraft.utils.learnings import (
            ACTIVE_SECTION_HEADING,
            STAGING_SECTION_HEADING,
            split_learnings_by_section,
            tail_after_staging_section,
        )

        prefix, active_body, staging_body = split_learnings_by_section(text)
        new_lines = [active_body.rstrip()] if active_body.strip() else []
        new_lines.extend(new_bullets)
        active_block = "\n".join(line for line in new_lines if line).strip()
        seed = prefix.rstrip() or "# Learnings"
        rebuilt = (
            f"{seed}\n\n## {ACTIVE_SECTION_HEADING}\n\n{active_block}\n\n"
            f"## {STAGING_SECTION_HEADING}\n\n{staging_body.strip()}\n"
        )
        learnings_path.write_text(
            _append_learnings_tail(rebuilt=rebuilt, tail=tail_after_staging_section(text)),
            encoding="utf-8",
        )
    _import_bundle_sidecars(repo=repo, bundle=bundle)


__all__ = [
    "DEFAULT_MAX_NEGATIVE_RULES",
    "FEEDBACK_FILE_NAME",
    "MEMORY_FILE_NAME",
    "FeedbackOutcome",
    "FeedbackRecord",
    "FeedbackStore",
    "MemoryContradiction",
    "MemoryEntry",
    "NegativeMemoryApplyResult",
    "NegativeMemoryAuditEntry",
    "NegativeMemoryRule",
    "NegativeMemoryStore",
    "OverSuppressionReport",
    "apply_negative_memory",
    "apply_recency_weighting",
    "detect_contradicting_memories",
    "detect_over_suppression",
    "export_memory_bundle",
    "get_finding_feedback",
    "import_memory_bundle",
    "load_feedback_store",
    "memory_entry_id",
    "parse_memory_entries_from_learnings",
    "record_finding_feedback",
    "remove_memory_entry_from_learnings",
]
