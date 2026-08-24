"""Collect durable-review artifacts after a CLI review completes (Thermos F1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.cli.trace_jsonl import load_trace_jsonl_events
from mergecraft.review.finding_lookup import is_safe_path_stem, load_json_packets_in_dir

if TYPE_CHECKING:
    from collections.abc import Sequence


def _trace_dir_for_repo(repo_root: Path) -> Path:
    env_dir = os.environ.get("MERGECRAFT_TRACE_DIR")
    if env_dir:
        return Path(env_dir)
    return repo_root / ".mergecraft" / "traces"


def _minimal_evidence_packet(fingerprint: str) -> dict[str, Any]:
    return {
        "finding_id": fingerprint,
        "state": "unverified",
        "kinds": [],
    }


def collect_evidence_packets_for_persist(
    findings: Sequence[Any],
    *,
    repo_root: Path,
    evidence_packet_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge per-fingerprint packets from disk with minimal stubs for each finding."""
    packets: dict[str, dict[str, Any]] = {}
    evidence_dir = repo_root / ".mergecraft" / "evidence"
    packets.update(
        load_json_packets_in_dir(evidence_dir, skip_names=frozenset()),
    )
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
            packets[fingerprint] = _minimal_evidence_packet(fingerprint)
    return packets


def collect_trace_events_for_review(
    review_id: str,
    *,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Return trace rows for ``review_id`` from the repo trace directory."""
    events = load_trace_jsonl_events(_trace_dir_for_repo(repo_root))
    return [event for event in events if str(event.get("session_id", "")) == review_id]


__all__ = [
    "collect_evidence_packets_for_persist",
    "collect_trace_events_for_review",
]
