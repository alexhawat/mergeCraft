"""Batch HB RED — antislop matcher bugs #434, #435, #438.

Pins that Python ``except`` handlers are matched, node text respects UTF-8
boundaries, and pass-through-wrapper ignores wrappers that bind literal
positionals. Implementation lands in W4 (one commit per issue, D2).
"""

from __future__ import annotations

import pytest

from mergecraft.analyzers.antislop.matcher import apply_rules
from mergecraft.analyzers.antislop.policy import load_native_rules

_RULES = load_native_rules()


def _rule_ids(source: str, *, rel_path: str = "src/sample.py") -> list[str]:
    return sorted(
        match.rule.rule_id for match in apply_rules(rel_path=rel_path, source=source, rules=_RULES)
    )


def _findings(source: str, *, rel_path: str = "src/sample.py") -> list[tuple[str, int, str]]:
    return sorted(
        (match.rule.rule_id, match.start_line, match.snippet)
        for match in apply_rules(rel_path=rel_path, source=source, rules=_RULES)
    )


# --- #434 empty-error-handler / error-obscuring-catch ------------------------


def test_python_except_block_that_only_passes_is_reported() -> None:
    """``except OSError: pass`` swallows the failure and must be reported."""
    source = (
        "def load() -> str:\n"
        "    try:\n"
        "        return open('data.txt', encoding='utf-8').read()\n"
        "    except OSError:\n"
        "        pass\n"
        "    return 'fallback'\n"
    )

    assert "antislop/empty-error-handler" in _rule_ids(source)


def test_python_except_block_returning_none_is_reported() -> None:
    """``except KeyError: return None`` hides the failure and must be reported."""
    source = (
        "def lookup(key: str) -> str | None:\n"
        "    try:\n"
        "        return _fetch(key)\n"
        "    except KeyError:\n"
        "        return None\n"
    )

    assert "antislop/error-obscuring-catch" in _rule_ids(source)


# --- #435 byte-offset slicing ------------------------------------------------


def test_non_ascii_above_an_import_must_not_make_a_used_import_phantom() -> None:
    """A used import stays used when the file contains a non-ASCII character."""
    source = "# café — notes\nimport os\n\n\ndef run() -> str:\n    return os.sep\n"

    assert "antislop/phantom-import" not in _rule_ids(source)


def test_snippet_after_non_ascii_quotes_real_source_text() -> None:
    """The placeholder snippet must be a substring of the file it came from."""
    source = "# — notes\ndef pending(value: int) -> int:\n    raise NotImplementedError\n"

    findings = _findings(source)
    assert findings == [("antislop/placeholder-implementation", 2, "raise NotImplementedError")]


# --- #438 pass-through-wrapper literal positionals -----------------------------


@pytest.mark.xfail(
    reason="green after W4: abort pass-through check on literal positionals (#438)",
    strict=False,
)
def test_wrapper_that_binds_a_literal_argument_is_not_a_pass_through() -> None:
    """A wrapper supplying an extra constant argument adds behaviour."""
    source = "def fetch(url: str) -> object:\n    return request('GET', url)\n"

    assert "antislop/pass-through-wrapper" not in _rule_ids(source)
