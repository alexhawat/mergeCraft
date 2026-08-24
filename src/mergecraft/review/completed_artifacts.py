"""Collect durable-review artifacts after a CLI review completes (#453)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.evidence.minimal_packet import minimal_evidence_packet
from mergecraft.review.finding_lookup import is_safe_path_stem
from mergecraft.tracing.trace_jsonl import default_trace_dir, load_trace_jsonl_events

if TYPE_CHECKING:
    from collections.abc import Sequence


def collect_evidence_packets_for_persist(
    findings: Sequence[Any],
    *,
    repo_root: Path,
    evidence_packet_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load packets for current findings only; stub any fingerprint still missing."""
    packets: dict[str, dict[str, Any]] = {}
    evidence_dir = repo_root / ".mergecraft" / "evidence"
    for finding in findings:
        fingerprint = finding.fingerprint
        if not is_safe_path_stem(fingerprint):
            continue
        path = evidence_dir / f"{fingerprint}.json"
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                packets[fingerprint] = loaded
    if evidence_packet_path:
        path = Path(evidence_packet_path)
        if path.is_file() and is_safe_path_stem(path.stem):
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    packets[path.stem] = loaded
            except (OSError, json.JSONDecodeError):
                pass
    for finding in findings:
        fingerprint = finding.fingerprint
        if fingerprint not in packets:
            packets[fingerprint] = minimal_evidence_packet(fingerprint)
    return packets


def collect_trace_events_for_review(
    review_id: str,
    *,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Return trace rows for ``review_id`` from the repo trace directory."""
    return load_trace_jsonl_events(
        default_trace_dir(repo_root=repo_root),
        session_id=review_id,
    )


__all__ = [
    "collect_evidence_packets_for_persist",
    "collect_trace_events_for_review",
]
