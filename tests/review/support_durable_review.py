"""Shared helpers for CD #453 durable completed-review RED tests (D4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.analyzers.support import import_module
from tests.analyzers.support_short_id import require_callable as require_finding_callable

_COMPLETED_MOD = "mergecraft.review.completed"
_REVIEWS_SUBDIR = ".mergecraft/reviews"
_ARTIFACT_NAMES = ("snapshot.json", "manifest.json", "findings.json")

_SAMPLE_FINGERPRINT = "a83f91c2d4e5f6a7b8c9d0e1f2a3b4c5"
_SAMPLE_REVIEW_ID = "review-cd-fixture-001"


def completed_module() -> Any:
    """Return the ``mergecraft.review.completed`` module."""
    return import_module(_COMPLETED_MOD)


def require_attr(name: str) -> Any:
    """Return a symbol from ``mergecraft.review.completed`` or fail the RED test."""
    mod = completed_module()
    value = getattr(mod, name, None)
    assert value is not None, f"{_COMPLETED_MOD}.{name} is not implemented"
    return value


def require_callable(name: str) -> Any:
    """Return a callable from ``mergecraft.review.completed`` or fail the RED test."""
    value = require_attr(name)
    assert callable(value), f"{_COMPLETED_MOD}.{name} must be callable"
    return value


def sample_review_id() -> str:
    """Stable review id used across CD CLI fixtures."""
    return _SAMPLE_REVIEW_ID


def sample_fingerprint() -> str:
    """Fingerprint backing the sample short finding id."""
    return _SAMPLE_FINGERPRINT


def sample_short_finding_id() -> str:
    """Return ``MC-…`` for the sample fingerprint (CA #452 helper)."""
    finding_short_id = require_finding_callable("finding_short_id")
    return finding_short_id(_SAMPLE_FINGERPRINT)


def sample_finding_dict() -> dict[str, Any]:
    """One structured finding dict for durable-review fixtures."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import os",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
        fingerprint=_SAMPLE_FINGERPRINT,
    )
    return finding.model_dump()


def sample_snapshot() -> Any:
    """Canonical CLI ``ReviewSnapshot`` for persistence tests."""
    snapshot_mod = import_module("mergecraft.review.snapshot")
    return snapshot_mod.canonical_review_snapshot(entry="cli", source="tests")


def sample_manifest() -> dict[str, Any]:
    """Minimal run manifest payload composed into a completed review (D4)."""
    manifest_mod = import_module("mergecraft.evidence.run_manifest")
    return manifest_mod.build_run_manifest(
        cwd=Path("."),
        model="claude-opus",
        agent_id="mergecraft",
        prompt_text="review prompt",
    )


def sample_trace_events(*, review_id: str) -> list[dict[str, Any]]:
    """Trace rows replay should read without re-running the review agent."""
    return [
        {
            "session_id": review_id,
            "kind": "span",
            "name": "review",
            "ts_start_ns": 1_000,
        },
        {
            "session_id": review_id,
            "kind": "span",
            "name": "publish",
            "ts_start_ns": 2_000,
        },
    ]


def sample_evidence_packet(*, fingerprint: str | None = None) -> dict[str, Any]:
    """Evidence packet stored beside the completed review."""
    fp = fingerprint or _SAMPLE_FINGERPRINT
    return {
        "finding_id": fp,
        "state": "unverified",
        "kinds": ["changed_lines"],
    }


def completed_review_dir(repo_root: Path, review_id: str) -> Path:
    """Expected on-disk directory for one completed review."""
    return repo_root / _REVIEWS_SUBDIR / review_id


def build_completed_review(*, review_id: str | None = None) -> Any:
    """Construct a ``CompletedReview`` record for store round-trips."""
    completed_cls = require_attr("CompletedReview")
    rid = review_id or _SAMPLE_REVIEW_ID
    return completed_cls(
        review_id=rid,
        snapshot=sample_snapshot(),
        manifest=sample_manifest(),
        findings=[sample_finding_dict()],
        trace_session_id=rid,
    )


def seed_completed_review(
    repo_root: Path,
    *,
    review_id: str | None = None,
    evidence_packets: dict[str, dict[str, Any]] | None = None,
    trace_events: list[dict[str, Any]] | None = None,
) -> Path:
    """Persist a completed review through the public store API (CD impl)."""
    persist = require_callable("persist_completed_review")
    rid = review_id or _SAMPLE_REVIEW_ID
    packets = evidence_packets
    if packets is None:
        packets = {sample_fingerprint(): sample_evidence_packet()}
    events = trace_events if trace_events is not None else sample_trace_events(review_id=rid)
    review = build_completed_review(review_id=rid)
    return persist(
        review,
        repo_root=repo_root,
        evidence_packets=packets,
        trace_events=events,
    )


def artifact_paths(repo_root: Path, review_id: str) -> dict[str, Path]:
    """Map artifact names to their expected paths under ``.mergecraft/reviews``."""
    root = completed_review_dir(repo_root, review_id)
    return {name: root / name for name in _ARTIFACT_NAMES}


def read_json(path: Path) -> Any:
    """Read JSON from ``path`` for assertions."""
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "artifact_paths",
    "build_completed_review",
    "completed_module",
    "completed_review_dir",
    "read_json",
    "require_attr",
    "require_callable",
    "sample_evidence_packet",
    "sample_finding_dict",
    "sample_fingerprint",
    "sample_manifest",
    "sample_review_id",
    "sample_short_finding_id",
    "sample_snapshot",
    "sample_trace_events",
    "seed_completed_review",
]
