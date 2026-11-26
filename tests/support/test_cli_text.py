"""Tests for the width-stable CLI text helper (#1565)."""

from __future__ import annotations

from tests.support.cli_text import compact_cli_text


def test_phrase_split_across_a_panel_border_is_contiguous() -> None:
    """Happy: a phrase broken by a Rich panel border reads as one phrase again."""
    rendered = "usage: mergecraft review\n│ a live │\n│ agent  │\n"

    assert "a live agent" in compact_cli_text(rendered)


def test_ansi_escape_sequences_are_removed() -> None:
    """Happy: colour codes never survive into a phrase assertion."""
    rendered = "\x1b[1mresult cache\x1b[0m does not restore a \x1b[36mlive agent\x1b[0m"

    compact = compact_cli_text(rendered)

    assert compact == "result cache does not restore a live agent"
    assert "\x1b" not in compact


def test_box_drawing_characters_from_a_table_are_not_glued_to_words() -> None:
    """Edge: table rules and corners become spaces, not dropped word joins."""
    rendered = "┏━━━━━━━┳━━━━━━━┓\n┃ value ┃ yaml  ┃\n┗━━━━━━━┻━━━━━━━┛"

    assert compact_cli_text(rendered) == "value yaml"


def test_runs_of_whitespace_collapse_and_ends_are_trimmed() -> None:
    """Edge: indentation and wrapping whitespace collapse to single spaces."""
    assert compact_cli_text("  a   live\n\t agent  ") == "a live agent"


def test_plain_text_is_returned_unchanged_in_content() -> None:
    """Happy: a phrase already on one line passes through untouched."""
    assert compact_cli_text("--resume is the result cache") == "--resume is the result cache"
