"""EV2 — orchestrator kind is a scored dimension of the result set.

RED suite for PR EV2 (sub-wave EV2.1; implementation EV2.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

File 3's W-23 asks whether ``hybrid`` actually beats ``llm`` on this corpus —
that question is unanswerable until the benchmark scores **per orchestrator
kind**, the way ``BenchmarkMetrics.by_corpus_class`` already scores per corpus
bucket. The pinned contract mirrors that existing dimension (same
``CorpusClassRollup`` shape), but as a pure function over typed rows so it can
be unit-tested without a bank (global convention 7: production tags each case
with its orchestrator kind — the typed attribution the agent-registry/AP work
on this branch provides; scoring folds it here):

- ``rollup_by_orchestrator_kind(rows_by_kind: dict[str, list[CaseReplayRow]])
  -> dict[str, CorpusClassRollup]`` (new in ``evals/benchmark.py``).
- Rollup mapping, derived purely from the row's replay ``status``:
  ``passed`` -> ``correct``, ``regression`` -> ``incorrect``,
  ``blocked`` -> ``inconclusive``.

The symbol is imported lazily inside the test (ImportError at RED time;
collection stays clean). Keyless and pure: ``skipped: no live gate``.
"""

from __future__ import annotations

import pytest

from mergecraft.evals.benchmark import CaseReplayRow
from mergecraft.evals.store import (
    CASE_STATUS_BLOCKED,
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
)

_XFAIL_EV2_2 = pytest.mark.xfail(
    reason="green after EV2.2: rollup_by_orchestrator_kind scores hybrid vs llm (W-23)",
    strict=False,
)


def _row(case_id: str, status: str) -> CaseReplayRow:
    return CaseReplayRow(
        case_id=case_id,
        corpus_class="correctness",
        status=status,
        expected_decision="block",
        current_decision="block" if status == CASE_STATUS_PASSED else "neutral",
        replayable=True,
    )


@_XFAIL_EV2_2
def test_orchestrator_kind_is_a_scored_dimension() -> None:
    """The same replay rows rolled up per orchestrator kind: hybrid and llm
    each get their own total/correct/incorrect/inconclusive counts, so the
    W-23 comparison is a lookup, not a re-run."""
    from mergecraft.evals.benchmark import rollup_by_orchestrator_kind

    rollups = rollup_by_orchestrator_kind(
        {
            "hybrid": [
                _row("c-1", CASE_STATUS_PASSED),
                _row("c-2", CASE_STATUS_PASSED),
                _row("c-3", CASE_STATUS_REGRESSION),
            ],
            "llm": [
                _row("c-1", CASE_STATUS_PASSED),
                _row("c-2", CASE_STATUS_REGRESSION),
                _row("c-3", CASE_STATUS_BLOCKED),
            ],
        }
    )

    assert set(rollups) == {"hybrid", "llm"}
    hybrid = rollups["hybrid"]
    assert hybrid.total == 3
    assert hybrid.correct == 2
    assert hybrid.incorrect == 1
    assert hybrid.inconclusive == 0
    llm = rollups["llm"]
    assert llm.total == 3
    assert llm.correct == 1
    assert llm.incorrect == 1
    assert llm.inconclusive == 1
