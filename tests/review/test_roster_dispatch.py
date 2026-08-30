"""Unit tests for reviewer dispatch batches and harness instructions (D15)."""

from __future__ import annotations

from mergecraft.review.roster_dispatch import (
    flatten_dispatch_batches,
    format_reviewer_dispatch_instructions,
)


def test_format_dispatch_instructions_empty() -> None:
    assert format_reviewer_dispatch_instructions(()) == ""


def test_format_dispatch_instructions_single_reviewer() -> None:
    assert format_reviewer_dispatch_instructions((("reviewer",),)) == ""


def test_format_dispatch_instructions_parallel_level() -> None:
    text = format_reviewer_dispatch_instructions((("reviewer-a", "reviewer-b"),))
    assert "Level 0 (parallel): reviewer-a, reviewer-b" in text
    assert "level N+1" in text
    assert "record_reviewer_dispatch_error" in text


def test_format_dispatch_instructions_chained_levels() -> None:
    text = format_reviewer_dispatch_instructions(
        (("reviewer-a",), ("reviewer-b", "reviewer-c")),
    )
    assert "Level 0 (parallel): reviewer-a" in text
    assert "Level 1 (after level 0 completes): reviewer-b, reviewer-c" in text


def test_flatten_dispatch_batches_preserves_level_order() -> None:
    batches = (("a", "b"), ("c",))
    assert flatten_dispatch_batches(batches) == ("a", "b", "c")
