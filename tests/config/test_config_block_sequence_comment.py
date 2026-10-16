"""A column-0 comment inside a top-level sequence does not end the block (#920).

``replace_config_block`` treats a column-0 ``- item`` as part of its key's block,
so a repeated write to a list-valued key replaces the whole sequence. A
column-0 *comment* between two items used to end the block early, leaving the
trailing items behind: ``models: [z, b]`` instead of ``models: [z]``.
"""

from __future__ import annotations

import yaml

from mergecraft.config.io import _top_level_block_span, replace_config_block


def _loaded(text: str) -> dict[str, object]:
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    return loaded


def test_the_exact_reproduction_replaces_the_whole_sequence() -> None:
    text = "models:\n- a\n# fallback\n- b\nother: 1\n"

    patched = replace_config_block(text, "models", ["z"])

    assert _loaded(patched) == {"models": ["z"], "other": 1}
    assert patched.count("models:") == 1


def test_the_span_covers_the_item_after_the_comment() -> None:
    lines = "models:\n- a\n# fallback\n- b\nother: 1\n".splitlines(keepends=True)

    assert _top_level_block_span(lines, "models") == (0, 4)


def test_an_indented_comment_still_replaces_the_whole_block() -> None:
    text = "models:\n  - a\n  # fallback\n  - b\nother: 1\n"

    patched = replace_config_block(text, "models", ["z"])

    assert _loaded(patched) == {"models": ["z"], "other": 1}


def test_a_comment_after_the_last_item_stays_outside_the_block() -> None:
    """The comment introduces the next key; replacing the block must not eat it."""
    text = "models:\n- a\n- b\n# the other section\nother: 1\n"

    patched = replace_config_block(text, "models", ["z"])

    assert _loaded(patched) == {"models": ["z"], "other": 1}
    assert "# the other section" in patched


def test_several_column_zero_comments_between_items_are_all_scanned_past() -> None:
    text = "models:\n- a\n# one\n\n# two\n- b\n- c\nother: 1\n"

    patched = replace_config_block(text, "models", ["z"])

    assert _loaded(patched) == {"models": ["z"], "other": 1}


def test_other_comments_in_the_file_are_preserved() -> None:
    text = "# header\nmodels:\n- a\n# fallback\n- b\n# tail note\nother: 1  # keep\n"

    patched = replace_config_block(text, "models", ["z"])

    assert patched.startswith("# header\n")
    assert "# tail note" in patched
    assert "other: 1  # keep" in patched
    assert "# fallback" not in patched, "a comment inside the replaced block goes with the block"


def test_a_comment_followed_by_a_new_top_level_key_ends_the_block() -> None:
    text = "models:\n- a\n# fallback\nother: 1\nmore: 2\n"

    patched = replace_config_block(text, "models", ["z"])

    assert _loaded(patched) == {"models": ["z"], "other": 1, "more": 2}
    assert "# fallback" in patched


def test_a_scalar_header_is_still_a_one_line_block() -> None:
    lines = "mode: x\n# comment\n- stray\n".splitlines(keepends=True)

    assert _top_level_block_span(lines, "mode") == (0, 1)


def test_the_docstring_states_the_column_zero_comment_rule() -> None:
    doc = " ".join((_top_level_block_span.__doc__ or "").split())
    assert "the blank or comment lines between them" not in doc
    assert "column-0 comment" in doc
