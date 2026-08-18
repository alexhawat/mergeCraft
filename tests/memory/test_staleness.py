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


def test_unprovenanced_bullets_ignore_ttl(tmp_path: Path) -> None:
    """Hand-maintained bullets without provenance never expire from prompt weighting."""
    from mergecraft.utils.learnings import load_weighted_active_memories

    text = "# Learnings\n\n## Active\n\n- operator curated rule from 2020\n"
    weighted = load_weighted_active_memories(learnings_text=text)

    assert weighted == [("operator curated rule from 2020", 1.0)]


def test_provenanced_bullets_expire_after_ttl(tmp_path: Path) -> None:
    """Provenanced bullets respect TTL and drop out when expired."""
    from mergecraft.utils.learnings import LearningProvenance, load_weighted_active_memories

    now = utc_now()
    provenance = LearningProvenance(
        run_id="run-old",
        pr_number=1,
        source_field="learnings_md",
        author_login="alice",
        author_association="MEMBER",
        trust_tier="trusted",
        timestamp=days_ago(400),
    )
    text = (
        f"# Learnings\n\n## Active\n\n{provenance.render_comment()}\n- expired provenanced note\n"
    )
    weighted = load_weighted_active_memories(learnings_text=text, now=now, ttl_days=365)

    assert weighted == []


def test_expired_provenanced_bullets_drop_from_assembled_prompt(tmp_path: Path) -> None:
    """Instructions assembly must filter TTL-expired bullets even when none survive weighting."""
    from mergecraft.config.settings import RepoInfo
    from mergecraft.modes import Mode
    from mergecraft.utils.instructions import resolve_instructions
    from mergecraft.utils.learnings import LearningProvenance

    provenance = LearningProvenance(
        run_id="run-old",
        pr_number=1,
        source_field="learnings_md",
        author_login="alice",
        author_association="MEMBER",
        trust_tier="trusted",
        timestamp=days_ago(400),
    )
    learnings = tmp_path / "learnings.md"
    learnings.write_text(
        f"# Learnings\n\n## Active\n\n{provenance.render_comment()}\n- expired provenanced note\n",
        encoding="utf-8",
    )

    resolved = resolve_instructions(
        payload={
            "~mergecraft": True,
            "prompt": "review this",
            "shell": "restricted",
            "event": {"trigger": "pull_request_opened", "title": "PR", "is_pr": True},
        },
        repo=RepoInfo(owner="acme", name="widgets", data={"default_branch": "main"}),
        modes=[Mode(name="Review", description="Review", prompt="do")],
        agent_id="claude",
        learnings_file_path=str(learnings),
    )

    assert "expired provenanced note" not in resolved.full
