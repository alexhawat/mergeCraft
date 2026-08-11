"""W8 contract: frozen prompt-surface RubricHash (Go rubric.go)."""

from __future__ import annotations

import re

from meat_python_plus.abridge import Request, build_user_prompt
from meat_python_plus.diffutil import numbered_diff
from meat_python_plus.rubric import SYSTEM_PROMPT, rubric_hash
from meat_python_plus.tools import Toolbox
from _parity_helpers import import_or_fail, require_attr
from fixtures.go_parity import (
    EXACT_MOVE_DIFF,
    GO_PINNED_RUBRIC_HASH,
    SURFACE_FIXTURE_NO_MOVE_DIFF,
)


def test_rubric_hash_format() -> None:
    h = rubric_hash()
    assert re.fullmatch(r"[0-9a-f]{16}", h)
    assert h == rubric_hash()


def test_rubric_hash_pinned_go_surface() -> None:
    surface_mod = import_or_fail("meat_python_plus.prompt_surface")
    surface_fn = require_attr(surface_mod, "prompt_surface")
    hash_fn = require_attr(surface_mod, "rubric_hash_from_surface")
    assert hash_fn(surface_fn()) == GO_PINNED_RUBRIC_HASH
    assert rubric_hash() == GO_PINNED_RUBRIC_HASH


def test_rubric_hash_changes_when_tool_schema_changes() -> None:
    surface_mod = import_or_fail("meat_python_plus.prompt_surface")
    surface_fn = require_attr(surface_mod, "prompt_surface")
    hash_fn = require_attr(surface_mod, "rubric_hash_from_surface")
    baseline = hash_fn(surface_fn())
    mutated = hash_fn(surface_fn() + "\0mutated-tool-schema-fragment")
    assert baseline != mutated


def test_cache_key_includes_full_rubric_surface() -> None:
    from meat_python_plus.cache import cache_key

    old_only = cache_key("diff", "model", "old-scheme-hash")
    full_surface = cache_key("diff", "model", GO_PINNED_RUBRIC_HASH)
    assert old_only != full_surface

    tools = Toolbox(repo_root="/repo", raw_diff=EXACT_MOVE_DIFF)
    schema_a = str(tools.tools()[0].input_schema)
    schema_b = schema_a.replace("remove", "removeX")
    hash_a = import_or_fail("meat_python_plus.prompt_surface").rubric_hash_for_tool_schema(schema_a)
    hash_b = import_or_fail("meat_python_plus.prompt_surface").rubric_hash_for_tool_schema(schema_b)
    assert hash_a != hash_b
    assert cache_key("diff", "m", hash_a) != cache_key("diff", "m", hash_b)


def test_surface_fixtures_cover_move_branches() -> None:
    moves_mod = import_or_fail("meat_python_plus.moves")
    detect = require_attr(moves_mod, "detected_moves_in_diff")
    assert detect(EXACT_MOVE_DIFF)
    assert not detect(SURFACE_FIXTURE_NO_MOVE_DIFF)

    overflow = require_attr(moves_mod, "surface_overflow_diff")()
    max_hints = require_attr(moves_mod, "MAX_MOVE_HINTS")
    assert len(detect(overflow)) > max_hints


def test_user_prompt_includes_detected_move_hint() -> None:
    numbered = numbered_diff(EXACT_MOVE_DIFF)
    prompt = build_user_prompt(Request(unified_diff=EXACT_MOVE_DIFF, repo_root="/repo"), numbered)
    assert "-6..9 ↔ +16..19" in prompt
    assert "identical keep/remove/fold/replace treatment" in prompt

    no_move = build_user_prompt(
        Request(unified_diff=SURFACE_FIXTURE_NO_MOVE_DIFF, repo_root="/repo"),
        numbered_diff(SURFACE_FIXTURE_NO_MOVE_DIFF),
    )
    assert "↔" not in no_move


def test_prompt_surface_excludes_compiler_internal_vocabulary() -> None:
    surface_mod = import_or_fail("meat_python_plus.prompt_surface")
    surfaces = {
        "system": SYSTEM_PROMPT,
        "user_with_move": build_user_prompt(
            Request(unified_diff=EXACT_MOVE_DIFF, repo_root="/repo"),
            numbered_diff(EXACT_MOVE_DIFF),
        ),
    }
    banned = (
        "mandatory",
        "compiler",
        "precedence over",
        "import precedence",
        "hiding wins",
        "wins before",
        "counterpart",
        "compiler-owned",
        "arbitrat",
    )
    for name, text in surfaces.items():
        lower = text.lower()
        for word in banned:
            assert word not in lower, f"{name} leaks compiler vocabulary {word!r}"
