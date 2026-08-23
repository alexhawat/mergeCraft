"""Durable completed-review storage for CLI follow-up commands (#453 / D4).

Exports:
    COMPLETED_REVIEW_SCHEMA_VERSION: Schema version for ``completed.json``.
    CompletedReview: Snapshot + manifest + findings for one finished review.
    completed_review_dir: On-disk directory for a stored review id.
    persist_completed_review: Write a completed review and related artifacts.
    load_completed_review: Reload a stored review, or ``None`` on miss/corrupt.
    list_completed_review_ids: Enumerate stored review ids under a repo root.
    lookup_finding_packet_in_review: Evidence packet lookup scoped to one review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mergecraft.analyzers.finding import FINDING_SHORT_ID_PREFIX, resolve_finding_short_ids
from mergecraft.review.snapshot import ReviewSnapshot

COMPLETED_REVIEW_SCHEMA_VERSION = "1.0.0"
_REVIEWS_SUBDIR = ".mergecraft/reviews"


def _is_safe_review_id(review_id: str) -> bool:
    if not review_id or review_id in {".", ".."}:
        return False
    if "/" in review_id or "\\" in review_id:
        return False
    return Path(review_id).parts == (review_id,)


def _is_safe_packet_stem(finding_id: str) -> bool:
    if not finding_id or finding_id in {".", ".."}:
        return False
    if "/" in finding_id or "\\" in finding_id:
        return False
    return Path(finding_id).parts == (finding_id,)


def completed_review_dir(review_id: str, *, repo_root: Path) -> Path:
    """Return ``<repo>/.mergecraft/reviews/<review_id>``."""
    return repo_root / _REVIEWS_SUBDIR / review_id


@dataclass(frozen=True, slots=True)
class CompletedReview:
    """One finished review composed for durable lookup (D4)."""

    review_id: str
    snapshot: ReviewSnapshot
    manifest: dict[str, Any]
    findings: list[dict[str, Any]]
    trace_session_id: str | None = None


def persist_completed_review(
    review: CompletedReview,
    *,
    repo_root: Path,
    evidence_packets: dict[str, dict[str, Any]] | None = None,
    trace_events: list[dict[str, Any]] | None = None,
) -> Path:
    """Persist ``review`` and optional evidence/trace artifacts; return the directory."""
    if not _is_safe_review_id(review.review_id):
        msg = f"unsafe review id {review.review_id!r}"
        raise ValueError(msg)
    root = completed_review_dir(review.review_id, repo_root=repo_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "snapshot.json").write_text(
        json.dumps(review.snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(review.manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "findings.json").write_text(
        json.dumps({"findings": review.findings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    completed_marker = {
        "schema_version": COMPLETED_REVIEW_SCHEMA_VERSION,
        "review_id": review.review_id,
        "trace_session_id": review.trace_session_id or review.review_id,
    }
    (root / "completed.json").write_text(
        json.dumps(completed_marker, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for fingerprint, packet in (evidence_packets or {}).items():
        if not _is_safe_packet_stem(fingerprint):
            continue
        (root / f"{fingerprint}.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    events = trace_events or []
    if events:
        lines = [json.dumps(event, ensure_ascii=False) for event in events]
        (root / "trace.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_completed_review(review_id: str, *, repo_root: Path) -> CompletedReview | None:
    """Load a stored review, or ``None`` when missing or corrupt."""
    if not _is_safe_review_id(review_id):
        return None
    root = completed_review_dir(review_id, repo_root=repo_root)
    completed_path = root / "completed.json"
    snapshot_path = root / "snapshot.json"
    manifest_path = root / "manifest.json"
    findings_path = root / "findings.json"
    if not all(
        path.is_file() for path in (completed_path, snapshot_path, manifest_path, findings_path)
    ):
        return None
    try:
        completed_payload = _read_json_file(completed_path)
        snapshot_payload = _read_json_file(snapshot_path)
        manifest_payload = _read_json_file(manifest_path)
        findings_payload = _read_json_file(findings_path)
        if not isinstance(completed_payload, dict):
            return None
        if not isinstance(manifest_payload, dict):
            return None
        if not isinstance(findings_payload, dict):
            return None
        raw_findings = findings_payload.get("findings")
        if not isinstance(raw_findings, list):
            return None
        snapshot = ReviewSnapshot.model_validate(snapshot_payload)
        trace_session_id = completed_payload.get("trace_session_id")
        return CompletedReview(
            review_id=str(completed_payload.get("review_id", review_id)),
            snapshot=snapshot,
            manifest=manifest_payload,
            findings=[row for row in raw_findings if isinstance(row, dict)],
            trace_session_id=str(trace_session_id) if trace_session_id else None,
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def list_completed_review_ids(*, repo_root: Path) -> list[str]:
    """Return review ids with a readable ``completed.json`` marker."""
    reviews_root = repo_root / _REVIEWS_SUBDIR
    if not reviews_root.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(reviews_root.iterdir()):
        if not child.is_dir():
            continue
        review_id = child.name
        if not _is_safe_review_id(review_id):
            continue
        if (child / "completed.json").is_file():
            ids.append(review_id)
    return ids


def _packets_in_review_dir(review_dir: Path) -> dict[str, dict[str, Any]]:
    packets: dict[str, dict[str, Any]] = {}
    for path in sorted(review_dir.glob("*.json")):
        if path.name in {"snapshot.json", "manifest.json", "findings.json", "completed.json"}:
            continue
        stem = path.stem
        if not _is_safe_packet_stem(stem):
            continue
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            packets[stem] = loaded
    return packets


def lookup_finding_packet_in_review(
    review_id: str,
    finding_id: str,
    *,
    repo_root: Path,
) -> dict[str, Any] | None:
    """Resolve a finding id against one completed review's co-located evidence."""
    if not _is_safe_review_id(review_id):
        return None
    review_dir = completed_review_dir(review_id, repo_root=repo_root)
    if not review_dir.is_dir():
        return None
    packets_by_fingerprint = _packets_in_review_dir(review_dir)
    if not packets_by_fingerprint:
        return None
    if finding_id.startswith(FINDING_SHORT_ID_PREFIX):
        suffix = finding_id[len(FINDING_SHORT_ID_PREFIX) :]
        if not suffix or not all(char in "0123456789abcdef" for char in suffix):
            return None
        mapping = resolve_finding_short_ids(list(packets_by_fingerprint))
        for fingerprint, mapped_id in mapping.items():
            if mapped_id == finding_id:
                return packets_by_fingerprint[fingerprint]
        return None
    if not _is_safe_packet_stem(finding_id):
        return None
    direct = packets_by_fingerprint.get(finding_id)
    if direct is not None:
        return direct
    for packet in packets_by_fingerprint.values():
        if str(packet.get("finding_id", "")) == finding_id:
            return packet
    return None


def load_completed_review_trace_events(
    review_id: str,
    *,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Return trace rows stored beside a completed review."""
    if not _is_safe_review_id(review_id):
        return []
    trace_path = completed_review_dir(review_id, repo_root=repo_root) / "trace.jsonl"
    if not trace_path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            events.append(loaded)
    return events


__all__ = [
    "COMPLETED_REVIEW_SCHEMA_VERSION",
    "CompletedReview",
    "completed_review_dir",
    "list_completed_review_ids",
    "load_completed_review",
    "load_completed_review_trace_events",
    "lookup_finding_packet_in_review",
    "persist_completed_review",
]
