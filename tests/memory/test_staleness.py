"""DG7 memory staleness — TTL, recency weighting, contradictions.

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG7).
Implementation: **DG7.2** — TTL and contradiction detection in ``utils/learnings.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests.memory.support import days_ago, memory_store_path, utc_now


def test_ttl_and_recency_weighting_apply(tmp_path: Path) -> None:
    """Expired memories drop out; recent memories weigh higher than stale ones."""
    from mergecraft.utils.memory import MemoryEntry, apply_recency_weighting

    repo = tmp_path / "repo"
    repo.mkdir()
    now = utc_now()
    entries = [
        MemoryEntry(
            id="fresh",
            text="Prefer httpx over requests in async code.",
            recorded_at=now,
            ttl_days=90,
        ),
        MemoryEntry(
            id="stale",
            text="Avoid the legacy requests shim.",
            recorded_at=days_ago(120),
            ttl_days=90,
        ),
        MemoryEntry(
            id="recent-heavy",
            text="Run make lint before pushing.",
            recorded_at=days_ago(2),
            ttl_days=30,
        ),
    ]

    weighted = apply_recency_weighting(entries, now=now)

    active_ids = {entry.id for entry, weight in weighted if weight > 0.0}
    assert "fresh" in active_ids
    assert "recent-heavy" in active_ids
    assert "stale" not in active_ids

    weights = {entry.id: weight for entry, weight in weighted if weight > 0.0}
    assert weights["recent-heavy"] > weights["fresh"]


def test_contradicting_memories_are_flagged(tmp_path: Path) -> None:
    """Conflicting memories are surfaced instead of silently merged."""
    from mergecraft.utils.memory import MemoryEntry, detect_contradicting_memories

    repo = tmp_path / "repo"
    repo.mkdir()
    _ = memory_store_path(repo)  # repo-scoped store path pinned for DG7.2 layout
    now = utc_now()
    entries = [
        MemoryEntry(
            id="always-flag-sql",
            text="Always flag raw SQL built from request parameters.",
            recorded_at=days_ago(10),
            ttl_days=365,
        ),
        MemoryEntry(
            id="ignore-sql-in-tests",
            text="Do not flag SQL injection findings in tests/fixtures/**.",
            recorded_at=days_ago(3),
            ttl_days=365,
        ),
    ]

    contradictions = detect_contradicting_memories(entries, now=now)

    assert contradictions
    pair = contradictions[0]
    assert {pair.left_id, pair.right_id} == {"always-flag-sql", "ignore-sql-in-tests"}
    assert pair.reason.strip()
