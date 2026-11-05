"""Prose proof checks removed lines in the base structure, additions in the head."""

from __future__ import annotations

import pytest
from tests.classify.test_whitespace_proof import patch

from mergecraft.classify.triage import triage_diff
from mergecraft.config.settings import FastPathSettings


def tier(before: str, after: str, *, context: int = 3) -> str:
    return triage_diff(
        patch("page.md", before, after, context=context),
        config=FastPathSettings(enabled=True, skip_llm=["prose"]),
        head_files={"page.md": after},
    ).tier


@pytest.mark.parametrize("context", [0, 3])
@pytest.mark.parametrize(
    "front_matter",
    [
        "---\nlayout: admin\nallow: all\n---\n",
        "---\nlayout: admin\nallow: all\n...\n",
        "---\nlayout: admin\nallow: all\n",  # unclosed is not proven prose
    ],
)
def test_front_matter_addition_and_deletion_get_full_review(
    front_matter: str, context: int
) -> None:
    body = "# Title\n\nPublic description.\n"
    assert tier(front_matter + body, body, context=context) == "full"
    assert tier(body, front_matter + body, context=context) == "full"


@pytest.mark.parametrize("context", [0, 3])
@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("---\nallow: all\n---\nBody.\n", "allow: all\n---\nBody.\n"),
        ("---\nallow: all\n---\nBody.\n", "---\n---\nBody.\n"),
        ("---\nallow: all\n---\nBody.\n", "---\nallow: all\nBody.\n"),
        ("---\nallow: all\n---\nBody.\n", "---\nallow: none\n---\nBody.\n"),
        ("Intro.\n\n```yaml\nallow: all\n```\n", "Intro.\n\n```yaml\n```\n"),
    ],
)
def test_deleting_structure_or_configuration_never_becomes_prose(
    before: str, after: str, context: int
) -> None:
    assert tier(before, after, context=context) == "full"


@pytest.mark.parametrize("context", [0, 3])
@pytest.mark.parametrize(
    "prefix", ["", "---\nlayout: public\n---\n", "```yaml\nallow: all\n```\n\n"]
)
def test_ordinary_prose_changes_remain_prose_with_unchanged_structure(
    prefix: str, context: int
) -> None:
    before = prefix + "First paragraph.\n\nOld paragraph.\n\nLast paragraph.\n"
    after = prefix + "Changed first paragraph.\n\nNew paragraph.\n\nLast paragraph.\n"
    assert tier(before, after, context=context) == "skip"
    assert tier(after, before, context=context) == "skip"


def test_mismatched_head_cannot_prove_old_front_matter_absent() -> None:
    decision = triage_diff(
        patch("page.md", "Before.\n", "After.\n"),
        config=FastPathSettings(enabled=True, skip_llm=["prose"]),
        head_files={"page.md": "Different head revision.\n"},
    )
    assert decision.tier == "full"
