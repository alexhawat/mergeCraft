"""Incremental first-pass miss labelling (RC9, D10) — W6.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W6).
Pins ``mergecraft.modes._incremental_miss`` helpers and the exact D10 label string.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

# D10 — exact wording; W6.2c must use this constant verbatim (not a paraphrase target).
FIRST_PASS_MISS_LABEL = (
    "_(First-pass miss — this line was already present at the first reviewed commit.)_"
)

_INCREMENTAL_DIFF_PRE_EXISTING = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@
 def handler():
+    fix_line()
     buggy = missing_guard()
"""

_INCREMENTAL_DIFF_ADDED_LINE = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@
 def handler():
+    fix_line()
     buggy = missing_guard()
"""


def _miss_mod() -> Any:
    try:
        return importlib.import_module("mergecraft.modes._incremental_miss")
    except ImportError as err:
        pytest.fail(f"W6.2 module missing: {err}")


def test_finding_on_pre_existing_line_is_labelled_a_first_pass_miss() -> None:
    miss = _miss_mod()

    assert miss.is_first_pass_miss_line(
        "src/app.py",
        12,
        _INCREMENTAL_DIFF_PRE_EXISTING,
    )
    labelled = miss.apply_first_pass_miss_label(
        "The guard is still missing.",
        path="src/app.py",
        line=12,
        incremental_diff_text=_INCREMENTAL_DIFF_PRE_EXISTING,
    )
    assert FIRST_PASS_MISS_LABEL in labelled


def test_finding_on_a_line_the_fix_added_is_not_labelled_a_miss() -> None:
    miss = _miss_mod()

    assert not miss.is_first_pass_miss_line(
        "src/app.py",
        11,
        _INCREMENTAL_DIFF_ADDED_LINE,
    )
    labelled = miss.apply_first_pass_miss_label(
        "New helper lacks validation.",
        path="src/app.py",
        line=11,
        incremental_diff_text=_INCREMENTAL_DIFF_ADDED_LINE,
    )
    assert FIRST_PASS_MISS_LABEL not in labelled


def test_miss_label_wording_matches_the_pinned_string() -> None:
    miss = _miss_mod()

    assert miss.FIRST_PASS_MISS_LABEL == FIRST_PASS_MISS_LABEL
    labelled = miss.apply_first_pass_miss_label("Stale null check.")
    assert labelled.startswith(FIRST_PASS_MISS_LABEL)
