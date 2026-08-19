"""DG7 learnings section preservation across memory forget/import."""

from __future__ import annotations

from pathlib import Path

from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING
from mergecraft.utils.memory import (
    import_memory_bundle,
    memory_entry_id,
    remove_memory_entry_from_learnings,
)


def _sectioned_learnings_with_withdrawn() -> str:
    return (
        "# Learnings\n\n"
        "## Active\n\n"
        "- keep this memory\n"
        "- drop this memory\n\n"
        "## Staging\n\n"
        "- staged item\n\n"
        f"{WITHDRAWN_FINDINGS_HEADING}\n\n"
        "- Refuted SQL injection false positive\n"
    )


def test_forget_preserves_withdrawn_section() -> None:
    """Forgetting an active bullet must not drop post-staging Withdrawn content."""
    text = _sectioned_learnings_with_withdrawn()
    drop_id = memory_entry_id("drop this memory")

    result = remove_memory_entry_from_learnings(text, drop_id)

    assert "keep this memory" in result
    assert "drop this memory" not in result
    assert WITHDRAWN_FINDINGS_HEADING in result
    assert "Refuted SQL injection false positive" in result


def test_import_preserves_withdrawn_section(tmp_path: Path) -> None:
    """Importing new bullets must not drop post-staging Withdrawn content."""
    repo = tmp_path / "repo"
    repo.mkdir()
    learnings = repo / ".mergecraft" / "learnings.md"
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text(
        "# Learnings\n\n## Active\n\n- existing memory\n\n## Staging\n\n\n"
        f"{WITHDRAWN_FINDINGS_HEADING}\n\n- withdrawn finding\n",
        encoding="utf-8",
    )

    import_memory_bundle(
        repo=repo,
        bundle={
            "version": 1,
            "entries": [{"id": "imported001", "text": "imported memory bullet"}],
            "feedback": [],
            "negative_memory": {"rules": [], "audit": []},
        },
    )

    text = learnings.read_text(encoding="utf-8")
    assert "existing memory" in text
    assert "imported memory bullet" in text
    assert WITHDRAWN_FINDINGS_HEADING in text
    assert "withdrawn finding" in text
