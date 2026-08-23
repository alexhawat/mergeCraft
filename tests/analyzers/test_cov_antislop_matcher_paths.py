"""Negative and boundary paths for the anti-slop rule matcher (#431, rules from #393).

``tests/analyzers/test_antislop.py`` proves each rule fires on its positive
fixture and stays quiet on its false-positive fixture. This file drives the
decisions *between* those two poles: source that nearly matches a rule and must
not be reported, rule definitions that are malformed or aimed at the wrong
language, and the guards that keep a mid-edit file from crashing the analyzer.

Every rule here lands findings on real pull requests, so a wrongly-taken branch
is a false positive in somebody's review.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

import pytest

from mergecraft.analyzers.antislop.matcher import _snippet, apply_rules
from mergecraft.analyzers.antislop.policy import AntislopRule, load_native_rules

if TYPE_CHECKING:
    from mergecraft.analyzers.antislop.policy import MatchKind

_RULES = load_native_rules()


def _findings(source: str, *, rel_path: str = "src/sample.py") -> list[tuple[str, int, str]]:
    """Run the shipped rule set and return ``(rule_id, start_line, snippet)`` rows."""
    return sorted(
        (match.rule.rule_id, match.start_line, match.snippet)
        for match in apply_rules(rel_path=rel_path, source=source, rules=_RULES)
    )


def _rule_ids(source: str, *, rel_path: str = "src/sample.py") -> list[str]:
    return [rule_id for rule_id, _line, _snippet in _findings(source, rel_path=rel_path)]


def _custom_rule(
    *,
    kind: str,
    languages: set[str],
    pattern: str | None = None,
    rule_id: str = "antislop/custom",
) -> AntislopRule:
    """Build a rule directly, bypassing the YAML loader's validation."""
    return AntislopRule(
        rule_id=rule_id,
        source_path="custom.yaml",
        severity="minor",
        confidence="likely",
        category="Maintainability & Code Quality",
        message="custom",
        remediation="",
        languages=frozenset(languages),
        match_kind=cast("MatchKind", kind),
        pattern=pattern,
        compiled_pattern=re.compile(pattern) if pattern is not None else None,
    )


# --- language selection -------------------------------------------------------


def test_unsupported_extension_is_never_scanned() -> None:
    """A non-source path returns no matches even when its text is full of slop.

    Markdown and config files routinely contain ``# Step 1:`` prose. Scanning
    them would put a finding on every documentation change.
    """
    source = "# Step 1: install\n# ==========\n# TODO: implement the rest\n"

    assert apply_rules(rel_path="docs/guide.md", source=source, rules=_RULES) == []
    assert _rule_ids(source) == [
        "antislop/placeholder-comment",
        "antislop/section-divider-spam",
        "antislop/step-comment",
    ]


def test_python_only_rules_do_not_fire_on_javascript() -> None:
    """``.js`` resolves to javascript, so a python-only rule is gated out.

    ``antislop/wrong-language-idiom`` flags ``.push`` in Python. In JavaScript
    ``.push`` is the correct API — firing there would flag idiomatic code.
    """
    source = "const items = [];\nitems.push(1);\n"

    assert _rule_ids(source, rel_path="src/app.js") == []
    assert _rule_ids(source, rel_path="src/app.mjs") == []
    assert _rule_ids("items = []\nitems.push(1)\n") == ["antislop/wrong-language-idiom"]


def test_typescript_suffixes_resolve_to_typescript_not_javascript() -> None:
    """``.ts``/``.tsx`` get the typescript label, ``.js``/``.jsx`` do not.

    A rule declaring ``languages: [typescript]`` must fire on TypeScript alone.
    Collapsing both to one label would silently widen every such rule.
    """
    rule = _custom_rule(kind="line_regex", languages={"typescript"}, pattern=r"marker")
    source = "const marker = 1;\n"

    def fired(rel_path: str) -> bool:
        return bool(apply_rules(rel_path=rel_path, source=source, rules=(rule,)))

    assert fired("src/app.ts") is True
    assert fired("src/app.tsx") is True
    assert fired("src/app.js") is False
    assert fired("src/app.jsx") is False
    assert fired("src/app.cjs") is False


# --- malformed / mis-aimed rule definitions -----------------------------------


@pytest.mark.parametrize("kind", ["comment_regex", "line_regex"])
def test_regex_rule_without_a_compiled_pattern_matches_nothing(kind: str) -> None:
    """A pattern-less regex rule is inert instead of raising.

    ``compiled_pattern`` is ``None`` whenever a rule file omits ``match.pattern``.
    Without the guard the matcher would call ``.search`` on ``None`` and take the
    whole analyzer down for every file in the diff.
    """
    rule = _custom_rule(kind=kind, languages={"python"}, pattern=None)
    source = "# TODO: implement this\nvalue = 1\n"

    assert apply_rules(rel_path="src/sample.py", source=source, rules=(rule,)) == []


def test_python_only_match_kind_declared_for_typescript_is_inert() -> None:
    """A tree-sitter Python kind aimed at TypeScript yields nothing, not a crash.

    The Python matchers parse with ``tree_sitter_python``. A rules author who
    declares ``kind: python_pass_through_wrapper`` for ``[typescript]`` must get
    silence, not Python-parsed nonsense over a TypeScript file.
    """
    rule = _custom_rule(kind="python_pass_through_wrapper", languages={"typescript"})
    source = "function wrap(a) {\n  return helper(a);\n}\n"

    assert apply_rules(rel_path="src/app.ts", source=source, rules=(rule,)) == []


def test_unknown_match_kind_produces_no_matches() -> None:
    """An unrecognised match kind is skipped rather than misrouted.

    The YAML loader rejects unknown kinds, so this is the second line of defence
    for a rule constructed in code: the matcher must not fall through into some
    other kind's handler.
    """
    rule = _custom_rule(kind="python_future_kind", languages={"python"})
    source = "def pending(value: int) -> int:\n    pass\n"

    assert apply_rules(rel_path="src/sample.py", source=source, rules=(rule,)) == []


def test_one_finding_per_rule_and_line_even_with_two_matches_on_it() -> None:
    """Matches are deduplicated on ``(rule_id, start_line)``.

    ``import os, sys`` binds two unused names on one line. The matcher reports
    that line once, so a single-line import list cannot inflate the review with
    duplicate comments anchored to the same line.
    """
    source = "import os, sys\n\n\ndef run() -> str:\n    return 'ok'\n"

    assert _findings(source) == [("antislop/phantom-import", 1, "import os is unused")]


# --- comment rules: the near-miss cases ---------------------------------------


def test_comment_rules_only_inspect_whole_line_comments() -> None:
    """A narrator comment trailing a statement is not reported.

    ``_extract_line_comment`` requires the stripped line to *start* with the
    comment prefix. Relaxing that would make every ``value = x  # ...`` line a
    candidate, including comment text inside string literals.
    """
    assert _rule_ids("x = 1  # This function does things\n") == []
    assert _rule_ids("# This function does things\n") == ["antislop/narrator-comment"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# This is a fine remark\n", []),
        ("# This function does things\n", ["antislop/narrator-comment"]),
        ("# Steps 1 and 2 are combined\n", []),
        ("# Step 1: do the thing\n", ["antislop/step-comment"]),
        ("# == two is not a divider\n", []),
        ("# === three is\n", ["antislop/section-divider-spam"]),
        ("# TODO: implement the parser\n", ["antislop/placeholder-comment"]),
        ("# TODO: the parser is slow under load\n", []),
    ],
)
def test_comment_rule_boundaries(source: str, expected: list[str]) -> None:
    """Each comment rule fires on its trigger and stays quiet one step short of it.

    The near-miss half of every pair is prose a human would legitimately write:
    a "This is" sentence, a plural "Steps", a two-character divider, and a TODO
    that records a known problem instead of unfinished work.
    """
    assert _rule_ids(source) == expected


# --- line rules: quoted literals and word boundaries --------------------------


def test_line_rules_ignore_text_inside_string_literals() -> None:
    """Prose that quotes a suppression comment is not a suppression.

    Rule files, docs strings, and error messages talk about ``# noqa``. Matching
    the raw line would flag the code that *documents* lint evasion.
    """
    assert _rule_ids('msg = "add a # noqa: E501 comment"\n') == []
    assert _rule_ids("value = compute()  # noqa: E501\n") == ["antislop/lint-evasion"]


def test_line_rule_snippet_quotes_the_original_line_not_the_stripped_one() -> None:
    """The reported snippet comes from the source line, literals intact.

    Matching runs against a literal-stripped copy; reporting must not, or the
    review comment would quote text that is nowhere in the file.
    """
    findings = _findings('value = "keep me"  # noqa: E501\n')

    assert len(findings) == 1
    _rule_id, _line, snippet = findings[0]
    assert "keep me" in snippet
    assert "noqa" in snippet


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(x: anything) -> None:\n    return None\n", []),
        ("def f(x: Any) -> None:\n    return None\n", ["antislop/type-evasion"]),
        ("pushed = compute()\n", []),
        ("items.pushall()\n", []),
        ("items.push(1)\n", ["antislop/wrong-language-idiom"]),
        ("length = len(items)\n", []),
        ("items.length\n", ["antislop/wrong-language-idiom"]),
    ],
)
def test_line_rule_word_boundaries(source: str, expected: list[str]) -> None:
    """Word-boundary anchors keep identifiers containing a keyword out of scope.

    ``anything`` is not ``any``, ``pushed`` is not ``.push``, and ``pushall`` is
    a method whose name merely starts with the JavaScript one.
    """
    assert _rule_ids(source) == expected


# --- placeholder implementation ------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected_snippet"),
    [
        ("    pass\n", "function body is only pass"),
        ("    ...\n", "function body is only ..."),
        ("    raise NotImplementedError\n", "raise NotImplementedError"),
        ("    # keep this\n    pass\n", "function body is only pass"),
    ],
)
def test_placeholder_bodies_are_reported_with_their_shape(body: str, expected_snippet: str) -> None:
    """Each placeholder body form is reported, and comments do not hide one.

    Comment nodes are filtered before the single-statement check, so adding a
    comment above ``pass`` must not launder a stub past the rule.
    """
    findings = _findings(f"def pending(value: int) -> int:\n{body}")

    assert findings == [("antislop/placeholder-implementation", 1, expected_snippet)]


@pytest.mark.parametrize(
    "body",
    [
        '    """Documented, deliberately empty."""\n',
        "    raise ValueError('bad input')\n",
        "    return value\n",
        '    """Doc."""\n    return value\n',
    ],
)
def test_real_function_bodies_are_not_placeholders(body: str) -> None:
    """Bodies that do something — or that raise a *real* error — are left alone.

    A docstring-only function is a deliberate no-op, ``raise ValueError`` is
    working code, and any multi-statement body is past the stub stage. Flagging
    these would fire on ordinary functions in every opted-in repository.
    """
    assert "antislop/placeholder-implementation" not in _rule_ids(
        f"def handler(value: int) -> int:\n{body}"
    )


def test_function_without_a_parsable_body_does_not_crash_the_matcher() -> None:
    """A truncated definition yields no finding instead of an exception.

    Analyzers run on whatever the diff contains, including a file that does not
    parse cleanly. ``child_by_field_name("body")`` returns ``None`` there.
    """
    assert _rule_ids("def f():\n") == []


# --- pass-through wrapper ------------------------------------------------------


def test_pass_through_wrapper_reports_a_forwarding_helper() -> None:
    """A wrapper forwarding its exact parameter list is reported once."""
    source = "def helper(value: int) -> int:\n    return value * 2\n\n\ndef wrapper(value: int) -> int:\n    return helper(value)\n"

    assert ("antislop/pass-through-wrapper", 5, "return helper(value)") in _findings(source)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("def wrap():\n    return helper()\n", "no parameters to forward"),
        ("def wrap(a, b):\n    return helper(b, a)\n", "arguments reordered"),
        ("def wrap(a):\n    return helper(value=a)\n", "forwarded by keyword"),
        ("def wrap(a):\n    return a\n", "returns a value, not a call"),
        ("def wrap(a):\n    return wrap(a)\n", "recursive call, not a wrapper"),
        ("def wrap(a):\n    log(a)\n    return helper(a)\n", "adds behaviour"),
    ],
)
def test_pass_through_wrapper_near_misses_are_not_reported(source: str, reason: str) -> None:
    """Only an exact positional forward counts as a pass-through wrapper.

    Reordering, appending, or keyword-binding arguments is adaptation, and a
    self-recursive call is not a wrapper at all — each of these is real logic
    that the rule must not claim adds nothing.
    """
    assert "antislop/pass-through-wrapper" not in _rule_ids(source), reason


def test_pass_through_wrapper_reads_annotated_and_defaulted_parameters() -> None:
    """Parameter names are recovered from typed and defaulted parameters.

    ``_python_parameter_names`` has to reach into ``typed_parameter`` and
    ``default_parameter`` nodes; missing them would leave the name list short and
    silently disable the rule for annotated code — which is most of this repo.
    """
    source = "def wrap(a: int, b: int = 2) -> int:\n    return helper(a, b)\n"

    assert _findings(source) == [("antislop/pass-through-wrapper", 1, "return helper(a, b)")]


# --- phantom import ------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected_name"),
    [
        ("import os\n\n\ndef run() -> str:\n    return 'ok'\n", "os"),
        ("import a.b as c\n\n\ndef run() -> str:\n    return 'ok'\n", "c"),
        ("from pkg import alpha as a\n\n\ndef run() -> str:\n    return 'ok'\n", "a"),
        ("from pkg import (alpha, beta)\n\n\ndef run() -> str:\n    return 'ok'\n", "alpha"),
    ],
)
def test_unused_import_is_reported_under_the_name_it_binds(source: str, expected_name: str) -> None:
    """The finding names the binding, not the module path.

    ``import a.b as c`` binds ``c``; reporting ``a`` or ``a.b`` would send the
    author looking for a name that is not in the file.
    """
    assert _findings(source) == [
        ("antislop/phantom-import", 1, f"import {expected_name} is unused")
    ]


@pytest.mark.parametrize(
    "source",
    [
        "import os\n\n\ndef run() -> str:\n    return os.sep\n",
        "import a.b as c\n\n\ndef run() -> object:\n    return c.thing()\n",
        "from pkg import alpha as a\n\n\ndef run() -> object:\n    return a()\n",
        "from pkg import (alpha, beta)\n\n\ndef run() -> object:\n    return alpha(beta)\n",
    ],
)
def test_used_imports_are_never_phantom(source: str) -> None:
    """Every binding form is recognised as used when the body references it.

    A false positive here fires on a correct import in an ordinary file, which
    is the worst outcome for an opt-in style analyzer.
    """
    assert "antislop/phantom-import" not in _rule_ids(source)


def test_type_checking_only_imports_are_exempt_in_every_import_form() -> None:
    """Names imported under ``if TYPE_CHECKING`` count as used in annotations.

    The repo's own style puts annotation-only imports in that block. Each import
    spelling has its own branch in ``_collect_import_names``; a missed one turns
    the house style into a finding on every module that uses it.
    """
    source = (
        "from __future__ import annotations\n"
        "\n"
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    import httpx\n"
        "    import collections.abc as abc\n"
        "    from pathlib import Path\n"
        "    from decimal import Decimal as Dec\n"
        "\n"
        "\n"
        "def fetch(client: httpx.Client, path: Path, amount: Dec, items: abc.Sequence) -> str:\n"
        "    return f'{client}{path}{amount}{items}'\n"
    )

    assert _rule_ids(source) == []


def test_type_checking_exempts_only_the_names_inside_the_block() -> None:
    """A runtime import stays reportable next to a TYPE_CHECKING block.

    The exemption set must not be applied wholesale to the file, or one
    ``if TYPE_CHECKING`` block would disable the rule for the whole module.
    """
    source = (
        "from typing import TYPE_CHECKING\n"
        "\n"
        "import unused_runtime\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from pathlib import Path\n"
        "\n"
        "\n"
        "def fetch(path: Path) -> str:\n"
        "    return f'{path}!'\n"
    )

    assert _findings(source) == [("antislop/phantom-import", 3, "import unused_runtime is unused")]


# --- snippet rendering ---------------------------------------------------------


def test_snippet_windows_around_the_match_and_collapses_whitespace() -> None:
    """A snippet is a bounded window around the match, not the whole line.

    Snippets are posted verbatim into PR comments, so an unbounded one leaks the
    rest of a long line into review output.
    """
    text = "left" * 20 + "  MATCH  " + "right" * 20
    windowed = _snippet(text, re.compile("MATCH"))

    assert "MATCH" in windowed
    assert len(windowed) <= 120
    assert "  " not in windowed
    assert len(windowed) < len(text)


def test_snippet_falls_back_to_the_truncated_text_when_the_pattern_misses() -> None:
    """When the pattern cannot be re-found, the snippet is still bounded.

    The display text is not always the text that was matched (line rules search a
    literal-stripped copy). The fallback must stay capped at the same limit
    rather than returning the entire line — or nothing.
    """
    text = "x" * 400

    assert _snippet(text, re.compile("never-here")) == "x" * 120
