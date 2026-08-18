"""Shared fixtures for DG7 memory/feedback tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mergecraft.analyzers.finding import make_finding as _make_finding
from mergecraft.review_taxonomy import finding_fingerprint, stamp_finding_fingerprint

_PATH = "src/app.py"
_BODY = stamp_finding_fingerprint(path=_PATH, body="Missing timeout on the retry loop.")
SAMPLE_FINGERPRINT = finding_fingerprint(path=_PATH, body=_BODY)


def sample_fingerprint(
    *, path: str = _PATH, body: str = "Missing timeout on the retry loop."
) -> str:
    """Return a stable finding fingerprint for memory/feedback fixtures."""
    stamped = stamp_finding_fingerprint(path=path, body=body)
    return finding_fingerprint(path=path, body=stamped)


def memory_store_path(repo: Path) -> Path:
    """Return the repo-scoped memory store path DG7.2 will persist under."""
    return repo / ".mergecraft" / "memory.json"


def feedback_store_path(repo: Path) -> Path:
    """Return the repo-scoped feedback ledger path DG7.2 will persist under."""
    return repo / ".mergecraft" / "feedback.json"


def utc_now() -> datetime:
    return datetime.now(UTC)


def days_ago(days: int) -> datetime:
    return utc_now() - timedelta(days=days)


def make_finding(**kwargs: Any) -> Any:
    """Build a taxonomy-valid ``Finding`` for DG7 contract tests."""
    defaults: dict[str, Any] = {
        "tool": "agent",
        "rule_id": "agent:1",
        "category": "Functional Correctness",
        "severity": "Major",
        "confidence": "likely",
        "message": "defect",
        "path": "src/app.py",
        "start_line": 10,
        "end_line": 10,
        "source": "agent",
        "introduced_by_pr": "true",
    }
    defaults.update(kwargs)
    return _make_finding(**defaults)
