"""Learnings persistence keeps one ``## Active`` / ``## Staging`` pair.

Each run's net-new bullets go into the existing sections, so entries from every
run stay visible to ``learnings active`` / ``learnings staging`` and to the
review prompt, which reads only the first ``## Active`` section.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mergecraft.utils.learnings import (
    LearningProvenance,
    list_active_entries,
    list_staging_entries,
    load_weighted_active_memories,
    route_learnings_for_persist,
)

_INIT_SCAFFOLD = "# Learnings\n\nOperational notes accumulated across agent runs.\n"


def _provenance(run: int, *, association: str) -> LearningProvenance:
    return LearningProvenance(
        run_id=str(run),
        pr_number=7,
        source_field="learnings_md",
        author_login="maintainer",
        author_association=association,
        trust_tier="trusted" if association == "OWNER" else "untrusted",
        timestamp=datetime.now(UTC),
    )


def _persist(seed: str, bullet: str, *, run: int, promote: bool) -> str:
    """One run: the agent appends ``bullet`` to the seed, then persist routes it."""
    body = route_learnings_for_persist(
        current=f"{seed.rstrip()}\n{bullet}\n",
        seed=seed,
        provenance=_provenance(run, association="OWNER" if promote else "NONE"),
        autopromote=promote,
    )
    assert body is not None
    return body


def _bullets(entries: list[dict[str, object | None]]) -> list[str]:
    return [
        line.strip().lstrip("-* ").strip()
        for entry in entries
        for line in str(entry.get("body") or "").splitlines()
        if line.strip()
    ]


def _heading_count(text: str, heading: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() == heading)


def test_three_promoting_runs_leave_one_pair_and_every_entry_reaches_the_prompt() -> None:
    text = _INIT_SCAFFOLD
    for run, bullet in enumerate(("- use uv", "- pin action SHAs", "- run make lint"), start=1):
        text = _persist(text, bullet, run=run, promote=True)

    assert _heading_count(text, "## Active") == 1
    assert _heading_count(text, "## Staging") == 1
    assert _bullets(list_active_entries(text)) == ["use uv", "pin action SHAs", "run make lint"]
    prompt_texts = {entry for entry, _weight in load_weighted_active_memories(learnings_text=text)}
    assert {"use uv", "pin action SHAs", "run make lint"} <= prompt_texts


def test_staged_and_promoted_entries_land_in_their_own_section_across_runs() -> None:
    text = _persist(_INIT_SCAFFOLD, "- trusted one", run=1, promote=True)
    text = _persist(text, "- untrusted two", run=2, promote=False)
    text = _persist(text, "- trusted three", run=3, promote=True)

    assert _heading_count(text, "## Active") == 1
    assert _heading_count(text, "## Staging") == 1
    assert _bullets(list_active_entries(text)) == ["trusted one", "trusted three"]
    assert _bullets(list_staging_entries(text)) == ["untrusted two"]


def test_a_file_with_duplicated_section_pairs_is_collapsed_on_the_next_persist() -> None:
    damaged = (
        "# Learnings\n\n## Active\n\n- first\n\n## Staging\n\n\n\n"
        "## Active\n\n\n\n## Staging\n\n- staged second\n"
    )

    text = _persist(damaged, "- third", run=3, promote=True)

    assert _heading_count(text, "## Active") == 1
    assert _heading_count(text, "## Staging") == 1
    assert _bullets(list_active_entries(text)) == ["first", "third"]
    assert _bullets(list_staging_entries(text)) == ["staged second"]


def test_content_after_the_sections_is_kept() -> None:
    seed = (
        "# Learnings\n\n## Active\n\n- first\n\n## Staging\n\n\n"
        "## Withdrawn review findings\n\n- abc123: refuted\n"
    )

    text = _persist(seed, "- second", run=2, promote=True)

    assert "## Withdrawn review findings\n\n- abc123: refuted" in text
    assert _bullets(list_active_entries(text)) == ["first", "second"]


def test_the_init_scaffold_has_no_staged_and_no_active_entries() -> None:
    assert list_staging_entries(_INIT_SCAFFOLD) == []
    assert list_active_entries(_INIT_SCAFFOLD) == []


def test_a_legacy_flat_file_lists_its_bullets_without_the_title() -> None:
    flat = "# Learnings\n\nOperational notes accumulated across agent runs.\n\n- use uv\n"

    assert _bullets(list_active_entries(flat)) == ["use uv"]
    assert list_staging_entries(flat) == []
