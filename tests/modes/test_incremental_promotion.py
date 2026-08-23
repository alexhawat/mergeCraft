"""Incremental deferred-finding promotion (RC9, W3 ledger) — W6.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W6).
Pins ``mergecraft.modes._incremental_promotion`` helpers that promote ledger
``deferred`` records when the incremental diff touches their cited region.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from mergecraft.review_taxonomy import finding_fingerprint

_DEFERRED_PATH = "src/deferred.py"
_UNTOUCHED_PATH = "src/other.py"
_DEFERRED_BODY = "Unchecked null dereference in handler."
_DEFERRED_FP = finding_fingerprint(path=_DEFERRED_PATH, body=_DEFERRED_BODY)


def _promotion_mod() -> Any:
    try:
        return importlib.import_module("mergecraft.modes._incremental_promotion")
    except ImportError as err:
        pytest.fail(f"W6.2 module missing: {err}")


def _ledger_mod() -> Any:
    return importlib.import_module("mergecraft.findings.ledger")


def _deferred_row() -> dict[str, object]:
    return {
        "path": _DEFERRED_PATH,
        "line": 42,
        "body": _DEFERRED_BODY,
        "severity": "Major",
        "fingerprint": _DEFERRED_FP,
    }


def test_deferred_finding_is_promoted_when_its_region_changes() -> None:
    promotion = _promotion_mod()
    ledger = _ledger_mod()

    book = ledger.FindingLedger()
    book.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)

    promoted = promotion.promote_deferred_for_incremental_paths(
        book,
        deferred_findings=[_deferred_row()],
        incremental_changed_paths=[_DEFERRED_PATH],
        round_index=2,
        recorded_at="2026-08-22T12:00:00Z",
    )

    assert _DEFERRED_FP in promoted
    current = next(record for record in book.records() if record.fingerprint == _DEFERRED_FP)
    assert current.state == "open"
    assert current.reason is not None
    assert current.reason.strip()


def test_deferred_finding_in_an_untouched_region_stays_deferred() -> None:
    promotion = _promotion_mod()
    ledger = _ledger_mod()

    book = ledger.FindingLedger()
    book.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)

    promoted = promotion.promote_deferred_for_incremental_paths(
        book,
        deferred_findings=[_deferred_row()],
        incremental_changed_paths=[_UNTOUCHED_PATH],
        round_index=2,
        recorded_at="2026-08-22T12:00:00Z",
    )

    assert promoted == frozenset()
    current = next(record for record in book.records() if record.fingerprint == _DEFERRED_FP)
    assert current.state == "deferred"


def test_promoted_finding_is_not_rediscovered_from_scratch() -> None:
    promotion = _promotion_mod()
    ledger = _ledger_mod()

    book = ledger.FindingLedger()
    book.record(_DEFERRED_FP, "deferred", source="overflow", round_index=1)
    before = {record.fingerprint for record in book.records()}

    promotion.promote_deferred_for_incremental_paths(
        book,
        deferred_findings=[_deferred_row()],
        incremental_changed_paths=[_DEFERRED_PATH],
        round_index=2,
        recorded_at="2026-08-22T12:00:00Z",
    )

    after = {record.fingerprint for record in book.records()}
    assert before == after
    assert _DEFERRED_FP in after
    taxonomy_fp = finding_fingerprint(path=_DEFERRED_PATH, body=_DEFERRED_BODY)
    assert taxonomy_fp == _DEFERRED_FP
