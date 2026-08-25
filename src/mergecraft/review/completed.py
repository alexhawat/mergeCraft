"""Durable completed-review storage for CLI follow-up commands (#453 / D4).

Exports:
    COMPLETED_REVIEW_SCHEMA_VERSION: Schema version for ``completed.json``.
    CompletedReview: Snapshot + manifest + findings for one finished review.
    completed_review_dir: On-disk directory for a stored review id.
    persist_completed_review: Write a completed review and related artifacts.
    load_completed_review: Reload a stored review, or ``None`` on miss/corrupt.
    list_completed_review_ids: Enumerate stored review ids under a repo root.
    lookup_finding_packet_in_review: Evidence packet lookup scoped to one review.
    lookup_finding_row_in_review: Finding row lookup scoped to one review.
    completed_review_payload: Load a stored review as a tool/API payload dict.
    persist_offline_review: Persist an offline review with evidence and trace artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

from mergecraft.analyzers.finding import Finding, finding_record_without_short_id
from mergecraft.evidence.minimal_packet import minimal_evidence_packet
from mergecraft.review.finding_lookup import (
    is_safe_path_stem,
    load_json_packets_in_dir,
    lookup_packet_by_finding_id,
)
from mergecraft.review.output import finding_json_records
from mergecraft.review.snapshot import ReviewSnapshot

COMPLETED_REVIEW_SCHEMA_VERSION = "1.0.0"
_REVIEWS_SUBDIR = ".mergecraft/reviews"
COMPLETED_REVIEWS_GITIGNORE_LINE = f"{_REVIEWS_SUBDIR}/"
_REVIEW_ARTIFACT_SKIP = frozenset(
    {"snapshot.json", "manifest.json", "findings.json", "completed.json"}
)


def completed_review_dir(review_id: str, *, repo_root: Path) -> Path:
    """Return ``<repo>/.mergecraft/reviews/<review_id>``."""
    return repo_root / _REVIEWS_SUBDIR / review_id


def completed_review_exists(review_id: str, *, repo_root: Path) -> bool:
    """Return whether ``review_id`` has a readable ``completed.json`` marker."""
    if not is_safe_path_stem(review_id):
        return False
    return (completed_review_dir(review_id, repo_root=repo_root) / "completed.json").is_file()


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
    if not is_safe_path_stem(review.review_id):
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
        if not is_safe_path_stem(fingerprint):
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


def persist_offline_review(
    *,
    review_id: str,
    trace_session_id: str,
    snapshot: ReviewSnapshot,
    repo_root: Path,
    model: str,
    prompt: str | None,
    findings: Sequence[Finding],
    evidence_packet_path: str | None = None,
    trace_dir: Path | None = None,
    agent_id: str = "mergecraft",
) -> list[dict[str, Any]]:
    """Persist an offline review and return serialized finding rows."""
    from mergecraft.evidence.run_manifest import build_run_manifest
    from mergecraft.review.completed_artifacts import (
        collect_evidence_packets_for_persist,
        collect_trace_events_for_review,
    )

    manifest = build_run_manifest(
        cwd=repo_root,
        model=model,
        agent_id=agent_id,
        prompt_text=prompt or "",
    )
    findings_records = finding_json_records(findings)
    review = CompletedReview(
        review_id=review_id,
        snapshot=snapshot,
        manifest=manifest,
        findings=findings_records,
        trace_session_id=trace_session_id,
    )
    evidence_packets = collect_evidence_packets_for_persist(
        findings,
        repo_root=repo_root,
        evidence_packet_path=evidence_packet_path,
    )
    trace_events = collect_trace_events_for_review(
        trace_session_id,
        repo_root=repo_root,
        trace_dir=trace_dir,
    )
    persist_completed_review(
        review,
        repo_root=repo_root,
        evidence_packets=evidence_packets,
        trace_events=trace_events,
    )
    return findings_records


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_loaded_findings(raw_findings: list[Any]) -> list[dict[str, Any]] | None:
    validated: list[dict[str, Any]] = []
    for row in raw_findings:
        if not isinstance(row, dict):
            return None
        short_id = row.get("short_id")
        payload = finding_record_without_short_id(row)
        try:
            record = Finding.model_validate(payload).model_dump(mode="json")
        except ValueError:
            return None
        if isinstance(short_id, str):
            record["short_id"] = short_id
        validated.append(record)
    return validated


def load_completed_review(review_id: str, *, repo_root: Path) -> CompletedReview | None:
    """Load a stored review, or ``None`` when missing or corrupt."""
    if not is_safe_path_stem(review_id):
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
        schema_version = completed_payload.get("schema_version")
        if schema_version != COMPLETED_REVIEW_SCHEMA_VERSION:
            return None
        raw_findings = findings_payload.get("findings")
        if not isinstance(raw_findings, list):
            return None
        findings = _validate_loaded_findings(raw_findings)
        if findings is None:
            return None
        snapshot = ReviewSnapshot.model_validate(snapshot_payload)
        trace_session_id = completed_payload.get("trace_session_id")
        return CompletedReview(
            review_id=str(completed_payload.get("review_id", review_id)),
            snapshot=snapshot,
            manifest=manifest_payload,
            findings=findings,
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
        if not is_safe_path_stem(review_id):
            continue
        if (child / "completed.json").is_file():
            ids.append(review_id)
    return ids


def _packets_in_review_dir(review_dir: Path) -> dict[str, dict[str, Any]]:
    return load_json_packets_in_dir(review_dir, skip_names=_REVIEW_ARTIFACT_SKIP)


def _fingerprints_from_findings(findings: list[dict[str, Any]]) -> list[str]:
    fingerprints: list[str] = []
    for row in findings:
        fp = row.get("fingerprint")
        if isinstance(fp, str) and fp:
            fingerprints.append(fp)
    return fingerprints


def _finding_row_for_id(
    findings: list[dict[str, Any]],
    finding_id: str,
) -> dict[str, Any] | None:
    for row in findings:
        if row.get("short_id") == finding_id:
            return row
        if row.get("fingerprint") == finding_id:
            return row
    return None


def lookup_finding_row_in_review(
    review_id: str,
    finding_id: str,
    *,
    repo_root: Path,
) -> dict[str, Any] | None:
    """Return a finding row when the review exists and the id matches."""
    loaded = load_completed_review(review_id, repo_root=repo_root)
    if loaded is None:
        return None
    return _finding_row_for_id(loaded.findings, finding_id)


def completed_review_payload(
    review_id: str,
    *,
    repo_root: Path,
) -> dict[str, Any] | None:
    """Load a stored review as a tool/API payload dict."""
    loaded = load_completed_review(review_id, repo_root=repo_root)
    if loaded is None:
        return None
    return {
        "review_id": loaded.review_id,
        "manifest": loaded.manifest,
        "findings": loaded.findings,
        "trace_session_id": loaded.trace_session_id,
    }


def lookup_finding_packet_in_review(
    review_id: str,
    finding_id: str,
    *,
    repo_root: Path,
) -> dict[str, Any] | None:
    """Resolve a finding id against one completed review's co-located evidence."""
    if not is_safe_path_stem(review_id):
        return None
    review_dir = completed_review_dir(review_id, repo_root=repo_root)
    if not review_dir.is_dir():
        return None
    packets_by_fingerprint = _packets_in_review_dir(review_dir)
    if packets_by_fingerprint:
        packet = lookup_packet_by_finding_id(finding_id, packets_by_fingerprint)
        if packet is not None:
            return packet
    loaded = load_completed_review(review_id, repo_root=repo_root)
    if loaded is None:
        return None
    fingerprints = _fingerprints_from_findings(loaded.findings)
    if not fingerprints:
        return None
    fallback_packets = {fp: minimal_evidence_packet(fp) for fp in fingerprints}
    return lookup_packet_by_finding_id(finding_id, fallback_packets)


def load_completed_review_trace_events(
    review_id: str,
    *,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Return trace rows stored beside a completed review."""
    if not is_safe_path_stem(review_id):
        return []
    trace_path = completed_review_dir(review_id, repo_root=repo_root) / "trace.jsonl"
    if not trace_path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            events.append(loaded)
    return events


__all__ = [
    "COMPLETED_REVIEWS_GITIGNORE_LINE",
    "COMPLETED_REVIEW_SCHEMA_VERSION",
    "CompletedReview",
    "completed_review_dir",
    "completed_review_exists",
    "completed_review_payload",
    "list_completed_review_ids",
    "load_completed_review",
    "load_completed_review_trace_events",
    "lookup_finding_packet_in_review",
    "lookup_finding_row_in_review",
    "persist_completed_review",
    "persist_offline_review",
]
