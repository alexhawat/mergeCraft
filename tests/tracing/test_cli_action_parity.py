"""CLI / Action parity for review correlation — OB1.1 RED suite (part 3 of 3).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB1,
sub-wave OB1.1). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

The CLI (``src/mergecraft/offline_review.py``) and the Action
(``src/mergecraft/main.py``) are separate entry points that build their
tracers separately; per the plan, "parity is an assertion, not an assumption".
OB1.2 binds a ``ReviewContext`` (``tracing/review_context.bind_review_context``)
at each entry point; once bound, the D4 close-time merge (pinned in
``tests/tracing/test_review_context.py``) puts ``review.id`` + the baseline
attrs on every span regardless of which entry point started the run.

Driving both entry points end to end requires agent CLIs and credentials, so
this test pins the *wiring* the same way
``tests/test_runtime_call_sites.py`` pins load-bearing call sites: it parses
each entry module's AST and requires a real ``bind_review_context(...)`` call.
The behavioural half (bound context → attrs on every span, at close time, for
either entry point's tracer) is covered by the sibling module; the full
runtime proof across the harness subprocess is the OB1 Final evidence gate.

The test is one function (plan §OB1.1 names exactly one) covering both entry
points; it carries a non-strict ``xfail`` (``green after OB1.2``) and is
expected RED until the binding lands in both modules.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

_SRC_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "mergecraft"
_ENTRY_MODULES: Final[tuple[str, ...]] = ("offline_review.py", "main.py")


def _module_calls_bind_review_context(path: Path) -> bool:
    """Return whether ``path`` contains a real ``bind_review_context(...)`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "bind_review_context":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "bind_review_context":
            return True
    return False


@pytest.mark.xfail(reason="green after OB1.2: entry-point review-context binding", strict=False)
def test_both_entry_points_emit_review_id_and_baseline() -> None:
    """Both run entry points bind a ``ReviewContext`` so their spans emit ``review.id``.

    With the binding in place, the D4 close-time merge guarantees the CLI and
    the Action emit the same ``review.id`` + baseline attr set (O1/O3); without
    it in either module, that entry point's spans are silently uncorrelated.
    """
    missing = [
        name for name in _ENTRY_MODULES if not _module_calls_bind_review_context(_SRC_DIR / name)
    ]
    assert not missing, (
        "entry points that never bind a ReviewContext — their spans cannot carry "
        f"review.id / baseline attrs: {missing}"
    )
