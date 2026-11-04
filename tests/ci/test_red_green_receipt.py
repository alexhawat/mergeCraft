"""Fail-then-pass receipts: parser, verdict, SHA binding, fix detection (#1056 part 5).

``mergecraft.ci.red_green`` is a pure module. It parses the receipt a
consumer's CI uploads (``{"schema": "mergecraft.red-green/1", "base_sha",
"head_sha", "tests": [{"id", "base", "head"}]}``), computes the verdict
(``proven`` needs at least one test red on the base and every listed test green
on the head), binds the receipt to the run's exact SHAs, and decides whether a
pull request is a fix (conventional ``fix`` type or a ``review.fixLabels``
label). mergeCraft never runs the tests itself.

The module is imported inside each test (``_rg()``) so the suite collects
before it exists and every test fails on its own.
"""

from __future__ import annotations

import dataclasses
import json
from importlib import import_module
from typing import Any

import pytest
from pydantic import ValidationError

SCHEMA_ID = "mergecraft.red-green/1"
BASE = "a" * 40
HEAD = "b" * 40
MAX_BYTES = 1_000_000
MAX_TESTS = 2_000
MAX_ID_CHARS = 500
DEFAULT_FIX_LABELS = ["bug", "fix"]


def _rg() -> Any:
    """Load ``mergecraft.ci.red_green`` lazily (fails per test until it exists)."""
    return import_module("mergecraft.ci.red_green")


def _test(
    test_id: str = "tests/test_x.py::test_bug", base: str = "failed", head: str = "passed"
) -> dict[str, str]:
    return {"id": test_id, "base": base, "head": head}


def _doc(
    *,
    tests: list[dict[str, Any]] | None = None,
    base_sha: str = BASE,
    head_sha: str = HEAD,
    schema: str = SCHEMA_ID,
    **extra: Any,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": schema,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "tests": [_test()] if tests is None else tests,
    }
    document.update(extra)
    return document


def _raw(document: Any) -> str:
    return json.dumps(document)


def _padded_to(document: dict[str, Any], size: int) -> bytes:
    """A valid receipt padded with trailing JSON whitespace to exactly ``size`` bytes."""
    body = json.dumps(document).encode("utf-8")
    assert len(body) <= size
    return body + b" " * (size - len(body))


class _TrapBytes(bytes):
    """Bytes that fail the test if anything decodes them (the oversized booby trap)."""

    def decode(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("an oversized receipt was decoded past the byte cap")


def _invalid(raw: str | bytes, **kwargs: Any) -> Any:
    rg = _rg()
    with pytest.raises(rg.RedGreenReceiptError) as excinfo:
        rg.parse_red_green_receipt(raw, **kwargs)
    return excinfo.value


# ── parse: happy path ────────────────────────────────────────────────────────


def test_a_valid_receipt_parses_into_typed_models() -> None:
    rg = _rg()
    receipt = rg.parse_red_green_receipt(_raw(_doc()))

    assert isinstance(receipt, rg.RedGreenReceipt)
    assert receipt.base_sha == BASE
    assert receipt.head_sha == HEAD
    assert isinstance(receipt.tests, tuple)
    assert len(receipt.tests) == 1
    test = receipt.tests[0]
    assert isinstance(test, rg.RedGreenTest)
    assert (test.id, test.base, test.head) == ("tests/test_x.py::test_bug", "failed", "passed")


def test_bytes_and_str_inputs_parse_to_the_same_receipt() -> None:
    rg = _rg()
    raw = _raw(_doc(tests=[_test("t1"), _test("t2", "passed", "passed")]))

    from_str = rg.parse_red_green_receipt(raw)
    from_bytes = rg.parse_red_green_receipt(raw.encode("utf-8"))

    assert from_str == from_bytes
    assert [t.id for t in from_bytes.tests] == ["t1", "t2"]


def test_the_tests_keep_their_order() -> None:
    ids = [f"tests/test_{index:03d}.py::test_case" for index in range(25)]
    receipt = _rg().parse_red_green_receipt(_raw(_doc(tests=[_test(i) for i in ids])))

    assert [t.id for t in receipt.tests] == ids


@pytest.mark.parametrize("result", ["passed", "failed", "error", "skipped"])
def test_every_test_result_literal_is_accepted(result: str) -> None:
    receipt = _rg().parse_red_green_receipt(_raw(_doc(tests=[_test("t", result, result)])))

    assert receipt.tests[0].base == result
    assert receipt.tests[0].head == result


def test_an_empty_test_list_parses() -> None:
    receipt = _rg().parse_red_green_receipt(_raw(_doc(tests=[])))

    assert receipt.tests == ()
    assert receipt.base_sha == BASE


def test_a_unicode_test_id_is_preserved() -> None:
    test_id = "tests/test_ünïcode.py::test_naïve[日本語]"
    receipt = _rg().parse_red_green_receipt(_raw(_doc(tests=[_test(test_id)])).encode("utf-8"))

    assert receipt.tests[0].id == test_id


def test_the_receipt_and_its_tests_are_frozen() -> None:
    receipt = _rg().parse_red_green_receipt(_raw(_doc()))

    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, ValidationError)):
        receipt.head_sha = BASE
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, ValidationError)):
        receipt.tests[0].head = "failed"
    assert receipt.head_sha == HEAD


# ── parse: bounds ────────────────────────────────────────────────────────────


def test_the_default_cap_is_one_megabyte_and_a_receipt_at_the_cap_parses() -> None:
    raw = _padded_to(_doc(), MAX_BYTES)

    receipt = _rg().parse_red_green_receipt(raw)

    assert len(raw) == MAX_BYTES
    assert receipt.head_sha == HEAD


def test_a_receipt_one_byte_over_the_cap_is_oversized_and_never_decoded() -> None:
    """1 000 001 bytes of an otherwise valid receipt: refused before any decode."""
    raw = _TrapBytes(_padded_to(_doc(), MAX_BYTES + 1))

    error = _invalid(raw)

    assert len(raw) == MAX_BYTES + 1
    assert error.kind == "oversized"
    assert str(error)


def test_an_oversized_str_receipt_is_refused() -> None:
    raw = _padded_to(_doc(), MAX_BYTES + 1).decode("utf-8")

    error = _invalid(raw)

    assert error.kind == "oversized"


def test_the_cap_counts_utf8_bytes_not_characters() -> None:
    """A str under the cap in characters but over it in UTF-8 bytes is oversized."""
    document = _doc(tests=[_test("é" * 400)])
    body = json.dumps(document, ensure_ascii=False)
    raw = body + " " * 10
    cap = len(raw) + 100  # characters fit; the 400 two-byte characters do not

    assert len(raw.encode("utf-8")) > cap
    error = _invalid(raw, max_bytes=cap)
    assert error.kind == "oversized"


def test_max_bytes_is_honoured_on_both_sides_of_the_boundary() -> None:
    rg = _rg()
    raw = _raw(_doc()).encode("utf-8")

    assert rg.parse_red_green_receipt(raw, max_bytes=len(raw)).head_sha == HEAD
    error = _invalid(raw, max_bytes=len(raw) - 1)
    assert error.kind == "oversized"


def test_two_thousand_tests_parse() -> None:
    tests = [_test(f"t{index}") for index in range(MAX_TESTS)]

    receipt = _rg().parse_red_green_receipt(_raw(_doc(tests=tests)))

    assert len(receipt.tests) == MAX_TESTS


def test_two_thousand_and_one_tests_are_invalid() -> None:
    tests = [_test(f"t{index}") for index in range(MAX_TESTS + 1)]

    error = _invalid(_raw(_doc(tests=tests)))

    assert error.kind == "invalid"
    assert str(error)


def test_a_test_id_of_five_hundred_characters_parses() -> None:
    receipt = _rg().parse_red_green_receipt(_raw(_doc(tests=[_test("x" * MAX_ID_CHARS)])))

    assert len(receipt.tests[0].id) == MAX_ID_CHARS


def test_a_test_id_of_five_hundred_and_one_characters_is_invalid() -> None:
    error = _invalid(_raw(_doc(tests=[_test("x" * (MAX_ID_CHARS + 1))])))

    assert error.kind == "invalid"


# ── parse: invalid documents ─────────────────────────────────────────────────

INVALID_CASES: list[tuple[str, str | bytes]] = [
    ("non-json", "this is not json"),
    ("truncated-json", _raw(_doc())[:-5]),
    ("top-level-array", _raw([_doc()])),
    ("top-level-string", _raw("receipt")),
    ("empty-input", ""),
    ("invalid-utf8", b'{"schema": "\xff\xfe"}'),
    ("wrong-schema-id", _raw(_doc(schema="mergecraft.red-green/2"))),
    ("foreign-schema-id", _raw(_doc(schema="junit/1"))),
    ("missing-schema", _raw({k: v for k, v in _doc().items() if k != "schema"})),
    ("missing-base-sha", _raw({k: v for k, v in _doc().items() if k != "base_sha"})),
    ("missing-head-sha", _raw({k: v for k, v in _doc().items() if k != "head_sha"})),
    ("missing-tests", _raw({k: v for k, v in _doc().items() if k != "tests"})),
    ("unknown-top-level-key", _raw(_doc(verdict="proven"))),
    ("unknown-test-key", _raw(_doc(tests=[{**_test(), "command": "pytest -k bug"}]))),
    ("tests-not-a-list", _raw(_doc(tests={"id": "t"}))),
    ("test-not-an-object", _raw(_doc(tests=["tests/test_x.py::test_bug"]))),
    ("unknown-result-literal", _raw(_doc(tests=[_test(base="flaky")]))),
    ("test-missing-head", _raw(_doc(tests=[{"id": "t", "base": "failed"}]))),
    ("test-missing-id", _raw(_doc(tests=[{"base": "failed", "head": "passed"}]))),
    ("sha-not-a-string", _raw(_doc(base_sha=12345))),
    ("id-not-a-string", _raw(_doc(tests=[{"id": 7, "base": "failed", "head": "passed"}]))),
]


@pytest.mark.parametrize(
    "raw", [raw for _id, raw in INVALID_CASES], ids=[case_id for case_id, _raw in INVALID_CASES]
)
def test_an_invalid_receipt_raises_the_invalid_kind(raw: str | bytes) -> None:
    error = _invalid(raw)

    assert error.kind == "invalid"
    assert isinstance(str(error), str)
    assert str(error)


def test_the_error_carries_its_kind() -> None:
    rg = _rg()
    invalid = rg.RedGreenReceiptError(kind="invalid")
    oversized = rg.RedGreenReceiptError(kind="oversized")

    assert isinstance(invalid, Exception)
    assert (invalid.kind, oversized.kind) == ("invalid", "oversized")


# ── verdict ──────────────────────────────────────────────────────────────────

VERDICT_CASES: list[tuple[str, list[tuple[str, str]], str]] = [
    ("failed-then-passed", [("failed", "passed")], "proven"),
    ("error-then-passed", [("error", "passed")], "proven"),
    ("one-red-one-already-green", [("failed", "passed"), ("passed", "passed")], "proven"),
    ("two-red-both-green", [("failed", "passed"), ("error", "passed")], "proven"),
    ("never-red", [("passed", "passed")], "not-proven"),
    ("still-failing-on-head", [("failed", "failed")], "not-proven"),
    ("error-on-head", [("failed", "error")], "not-proven"),
    ("skipped-on-head", [("failed", "skipped")], "not-proven"),
    ("skipped-on-base", [("skipped", "passed")], "not-proven"),
    (
        "one-red-but-another-skipped-on-head",
        [("failed", "passed"), ("passed", "skipped")],
        "not-proven",
    ),
    ("one-red-but-another-regressed", [("failed", "passed"), ("passed", "failed")], "not-proven"),
    ("all-skipped", [("skipped", "skipped")], "not-proven"),
    ("empty", [], "no-tests"),
]


@pytest.mark.parametrize(
    ("results", "expected"),
    [(results, expected) for _id, results, expected in VERDICT_CASES],
    ids=[case_id for case_id, _results, _expected in VERDICT_CASES],
)
def test_the_verdict_table(results: list[tuple[str, str]], expected: str) -> None:
    rg = _rg()
    tests = [_test(f"t{index}", base, head) for index, (base, head) in enumerate(results)]
    receipt = rg.parse_red_green_receipt(_raw(_doc(tests=tests)))

    assert rg.red_green_verdict(receipt) == expected


def test_a_receipt_built_in_code_gets_the_same_verdict() -> None:
    rg = _rg()
    receipt = rg.RedGreenReceipt(
        base_sha=BASE,
        head_sha=HEAD,
        tests=(rg.RedGreenTest(id="t", base="error", head="passed"),),
    )

    assert rg.red_green_verdict(receipt) == "proven"


# ── SHA binding ──────────────────────────────────────────────────────────────


def _receipt(base_sha: str = BASE, head_sha: str = HEAD) -> Any:
    return _rg().parse_red_green_receipt(_raw(_doc(base_sha=base_sha, head_sha=head_sha)))


MATCH_CASES: list[tuple[str, str, str, str, str, bool]] = [
    # (id, receipt base, receipt head, run base, run head, matches)
    ("exact", BASE, HEAD, BASE, HEAD, True),
    ("receipt-uppercase", BASE.upper(), HEAD.upper(), BASE, HEAD, True),
    ("run-uppercase", BASE, HEAD, BASE.upper(), HEAD.upper(), True),
    ("mixed-case", "Aa" * 20, "bB" * 20, "aA" * 20, "Bb" * 20, True),
    ("head-differs-last-char", BASE, HEAD[:-1] + "c", BASE, HEAD, False),
    ("base-differs", "c" * 40, HEAD, BASE, HEAD, False),
    ("swapped", HEAD, BASE, BASE, HEAD, False),
    ("short-receipt-head", BASE, HEAD[:7], BASE, HEAD, False),
    ("short-receipt-base", BASE[:12], HEAD, BASE, HEAD, False),
    ("short-run-head", BASE, HEAD, BASE, HEAD[:7], False),
    ("short-on-both-sides", BASE[:7], HEAD[:7], BASE[:7], HEAD[:7], False),
    ("empty-on-both-sides", "", "", "", "", False),
    ("non-hex-equal-strings", "z" * 40, "y" * 40, "z" * 40, "y" * 40, False),
]


@pytest.mark.parametrize(
    ("receipt_base", "receipt_head", "run_base", "run_head", "matches"),
    [case[1:] for case in MATCH_CASES],
    ids=[case[0] for case in MATCH_CASES],
)
def test_receipt_matches_compares_full_length_hex_case_insensitively(
    receipt_base: str, receipt_head: str, run_base: str, run_head: str, matches: bool
) -> None:
    receipt = _receipt(receipt_base, receipt_head)

    assert _rg().receipt_matches(receipt, base_sha=run_base, head_sha=run_head) is matches


def test_receipt_matches_takes_the_shas_by_keyword_only() -> None:
    with pytest.raises(TypeError):
        _rg().receipt_matches(_receipt(), BASE, HEAD)


# ── fix detection ────────────────────────────────────────────────────────────

TITLE_CASES: list[tuple[str, bool]] = [
    ("fix: handle empty receipts", True),
    ("fix(ci): handle empty receipts", True),
    ("fix!: drop the legacy receipt format", True),
    ("fix(ci)!: drop the legacy receipt format", True),
    ("fix(scope-with-dash): x", True),
    ("Fix: capitalised type", True),
    ("FIX(ci): shouted type", True),
    ("  fix: leading whitespace is stripped", True),
    ("\tfix(ci)!: leading tab", True),
    ("feat: add receipts", False),
    ("feat: fix the receipt parser", False),
    ("fixture: add receipt samples", False),
    ("prefix: something", False),
    ("fixes: typo", False),
    ("chore(fix): bump", False),
    ("docs: describe fix: receipts", False),
    ("Hotfix the parser", False),
    ("", False),
]


@pytest.mark.parametrize(
    ("title", "expected"), TITLE_CASES, ids=[title or "<empty>" for title, _e in TITLE_CASES]
)
def test_a_conventional_fix_title_makes_a_fix_pull_request(title: str, expected: bool) -> None:
    assert _rg().is_fix_pull_request(title, [], fix_labels=DEFAULT_FIX_LABELS) is expected


@pytest.mark.parametrize(
    ("labels", "fix_labels", "expected"),
    [
        (["bug"], DEFAULT_FIX_LABELS, True),
        (["fix"], DEFAULT_FIX_LABELS, True),
        (["Bug"], DEFAULT_FIX_LABELS, True),
        (["documentation", "BUG"], DEFAULT_FIX_LABELS, True),
        (["enhancement"], DEFAULT_FIX_LABELS, False),
        (["bugfix"], DEFAULT_FIX_LABELS, False),
        ([], DEFAULT_FIX_LABELS, False),
        (["regression"], ["regression"], True),
        (["bug"], ["regression"], False),
        (["hotfix"], ["Hotfix"], True),
        (["bug"], [], False),
    ],
    ids=[
        "bug",
        "fix",
        "label-case",
        "one-of-many",
        "other-label",
        "label-is-not-a-prefix-match",
        "no-labels",
        "custom-label",
        "custom-list-replaces-default",
        "configured-label-case",
        "empty-fix-labels",
    ],
)
def test_a_fix_label_makes_a_fix_pull_request(
    labels: list[str], fix_labels: list[str], expected: bool
) -> None:
    title = "chore: tidy the receipt module"

    assert _rg().is_fix_pull_request(title, labels, fix_labels=fix_labels) is expected


def test_a_fix_title_needs_no_label() -> None:
    assert _rg().is_fix_pull_request("fix: x", [], fix_labels=[]) is True


def test_a_label_alone_marks_a_fix_whatever_the_title_says() -> None:
    assert _rg().is_fix_pull_request("feat: new thing", ["bug"], fix_labels=DEFAULT_FIX_LABELS)


def test_fix_labels_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        _rg().is_fix_pull_request("fix: x", [], DEFAULT_FIX_LABELS)


# ── the module stays pure ────────────────────────────────────────────────────


def test_the_receipt_module_does_no_io() -> None:
    """Pure by contract: it imports no network, subprocess or filesystem client."""
    import ast
    from pathlib import Path

    module = _rg()
    source = Path(module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "json" in imported or "pydantic" in imported
    forbidden = {"subprocess", "httpx", "socket", "requests", "urllib", "asyncio"}
    assert not (imported & forbidden)
    assert not any(
        name.startswith(("mergecraft.utils.github", "mergecraft.scm")) for name in imported
    )
