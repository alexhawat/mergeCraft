"""Join corpus case -> diff-review findings -> score_findings -> DetectionMetrics.

(#140, B3, RED wave — "the centre of the plan", N5)

``evals/benchmark.py`` (structural decision replay) and ``evals/scoring.py`` (finding-location
precision/recall/F1) are two disconnected halves today; ``run_structural_replay()``'s own
docstring says live provider finding-location metrics are "not populated." B3 is the join:
corpus case -> ``diff-review --json`` -> findings -> ``score_findings()`` -> ``AggregateScoreReport``
-> a new optional ``detection`` section on ``BenchmarkResultSet``.

None of ``mergecraft.evals.live_run``'s symbols exist yet -- this whole file fails at **collection
time** via ``ImportError`` today, which is the correct RED signature for this PR specifically
(unlike B1/B2, where every referenced symbol already existed and RED came from ``AttributeError``/
``ValidationError`` at call time -- see ``docs/dev/test-plans/eval-benchmark-b1-metrics.md`` and
``eval-benchmark-b2-gate.md``). Every other imported symbol below (``BenchmarkResultSet``,
``run_structural_replay``, ``has_credentials_for_slug``, ``Case``, ``add_case``,
``AggregateScoreReport``) already exists and resolves cleanly -- confirm a red run shows exactly one
failure reason (the missing module), not a typo against something that already exists.

See ``docs/dev/test-plans/eval-benchmark-b3-live.md`` for the full design-gate resolution this file
pins: why the join needs a dependency-injection seam (``review_fn``) to stay keyless and
deterministic, the on-disk detection-corpus format this pass invents for B4 to follow, and the two
distinct skip reasons (no credential vs. no patch-bearing cases) and their precedence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.evals.benchmark import (
    DEFAULT_BENCHMARK_PROVIDERS,
    RESULT_SET_SCHEMA_VERSION,
    BenchmarkResultSet,
    run_structural_replay,
)
from mergecraft.evals.live_run import (
    BASELINE_FILENAME,
    PATCH_CANDIDATES,
    SKIP_REASON_NO_CASES,
    SKIP_REASON_NO_CREDENTIAL,
    DetectionCase,
    DetectionCaseResult,
    DetectionMetrics,
    ReviewRunFailed,
    discover_detection_cases,
    run_detection,
    run_full_benchmark,
    run_live_detection,
)
from mergecraft.evals.scoring import AggregateScoreReport
from mergecraft.evals.store import Case, add_case
from mergecraft.utils.learnings import LearningProvenance

_WHEN = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

# Verified verbatim against `src/mergecraft/harbor/agent.py:23` (2026-08-15). Not imported from
# `mergecraft.harbor.agent` -- that module requires the optional `harbor` extra
# (`pyproject.toml:39`), which is not installed in this checkout (confirmed:
# `uv run python -c "import harbor"` -> ModuleNotFoundError). See B3.0 design-gate finding 1 in
# the test-plan doc for why `evals/live_run.py` must not hard-import it either.
_HARBOR_PATCH_CANDIDATES = ("task.patch", "changes.patch", "diff.patch", "review.patch")


# ── bank-case fixtures (structural replay side, unchanged B1/B2 machinery) ──


def _provenance() -> LearningProvenance:
    return LearningProvenance(
        run_id="synthetic",
        pr_number=1,
        source_field="eval_bank",
        author_login="synthetic",
        author_association="OWNER",
        trust_tier="trusted",
        timestamp=_WHEN,
    )


def _bank_case(case_id: str) -> Case:
    """A trivially-replayable bank case -- exercises the structural (B1/B2) half only."""
    return Case(
        id=case_id,
        title=f"live-run fixture {case_id}",
        category="missed_finding",
        submitted_at=_WHEN,
        run_id="synthetic",
        pr_number=1,
        failure_mode="wrong_decision",
        expected_finding="synthetic",
        expected_decision="neutral",
        replay_command=f"mergecraft eval replay {case_id}",
        provenance=_provenance(),
        body="",
        recorded_findings=[],
        run_succeeded=True,
        trust_tier="trusted",
    )


# ── detection-corpus fixtures (the new B3 on-disk shape, see test-plan doc) ──


def _write_detection_case(
    corpus_dir: Path,
    case_id: str,
    *,
    issues: list[dict[str, Any]],
    closed_world: bool,
    patch_name: str = "task.patch",
) -> None:
    case_dir = corpus_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / patch_name).write_text(
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    (case_dir / BASELINE_FILENAME).write_text(
        json.dumps({"closed_world": closed_world, "issues": issues}),
        encoding="utf-8",
    )


def _stub_review_fn(
    responses: dict[str, list[dict[str, Any]]],
) -> tuple[Any, list[str]]:
    """Return a ``review_fn`` and the list of case ids it was actually invoked for.

    Standing in for a real ``mergecraft diff-review --json`` subprocess call (design-gate
    finding 4) -- this is the dependency-injection seam that keeps the RED suite keyless and
    deterministic. A production ``review_fn`` shells out and reads back the ``{"findings": [...]}``
    file ``write_findings_json`` produces; this stub returns canned rows of the same shape.
    """
    calls: list[str] = []

    def _fn(case: DetectionCase) -> list[dict[str, Any]]:
        calls.append(case.case_id)
        return responses.get(case.case_id, [])

    return _fn, calls


# ── B3.1 bullet 1: end-to-end on a fixture corpus, hand-computed P/R/F1 ──


def test_end_to_end_fixture_corpus_produces_correct_prf1(tmp_path: Path) -> None:
    """Two-case fixture corpus, hand-computed against ``score_findings``'s own rules.

    Case A (open-world): 2 baseline issues, one located, one extra unmatched finding elsewhere.
    recall = 1/2 = 0.5, corpus_confirmed_precision = 1/2 = 0.5, f1 = 0.5.

    Case B (closed-world / clean): 0 baseline issues, 0 findings.
    ``strict_precision`` denominator is 0 -> 1.0 (``ScoreReport.strict_precision``'s own rule,
    scoring.py:225-228) -- the B3.1 "zero findings on a clean case" scenario.

    Folded aggregate: total_issues=2, total_reported=2, found=1, recall=0.5,
    corpus_confirmed_precision=0.5, f1=0.5 (``fold_score_reports`` is pure summation, already
    covered by B1's own suite -- this test is pinning that ``live_run.py`` calls it correctly, not
    re-deriving its arithmetic).
    """
    corpus = tmp_path / "detect-corpus"
    _write_detection_case(
        corpus,
        "bench-detect-open-001",
        closed_world=False,
        issues=[
            {"id": "issue-1", "path": "src/a.py", "start_line": 10, "end_line": 12},
            {"id": "issue-2", "path": "src/b.py", "start_line": 20, "end_line": 22},
        ],
    )
    _write_detection_case(
        corpus,
        "bench-detect-clean-001",
        closed_world=True,
        issues=[],
    )

    review_fn, calls = _stub_review_fn(
        {
            "bench-detect-open-001": [
                {"path": "src/a.py", "start_line": 10, "end_line": 12, "message": "m1"},
                {"path": "src/c.py", "start_line": 5, "end_line": 5, "message": "extra"},
            ],
            "bench-detect-clean-001": [],
        }
    )

    cases = discover_detection_cases(corpus)
    assert {c.case_id for c in cases} == {"bench-detect-open-001", "bench-detect-clean-001"}

    results_dir = tmp_path / "results"
    metrics = run_live_detection(
        cases,
        provider="claude",
        model="claude-sonnet-5",
        review_fn=review_fn,
        results_dir=results_dir,
    )

    assert isinstance(metrics, DetectionMetrics)
    assert sorted(calls) == ["bench-detect-clean-001", "bench-detect-open-001"]
    assert metrics.cases_run == 2
    assert metrics.provider == "claude"
    assert metrics.model == "claude-sonnet-5"

    agg = metrics.aggregate
    assert isinstance(agg, AggregateScoreReport)
    assert agg.total_issues == 2
    assert agg.total_reported == 2
    assert agg.found == 1
    assert agg.recall == pytest.approx(0.5)
    assert agg.corpus_confirmed_precision == pytest.approx(0.5)
    assert agg.f1 == pytest.approx(0.5)

    by_case = {r.case_id: r for r in metrics.case_results}
    open_result = by_case["bench-detect-open-001"]
    assert open_result.closed_world is False
    assert open_result.recall == pytest.approx(0.5)
    assert open_result.strict_precision is None

    clean_result = by_case["bench-detect-clean-001"]
    assert clean_result.closed_world is True
    assert clean_result.total_issues == 0
    assert clean_result.total_reported == 0
    # The B3.1 checklist's exact scenario: zero findings on a clean case.
    assert clean_result.strict_precision == pytest.approx(1.0)

    # Raw findings persisted per case (B3.2 checklist: `evals/results/<stamp>/raw-findings/`).
    raw_dir = Path(metrics.raw_findings_dir)
    assert raw_dir.is_dir()
    assert (raw_dir / "bench-detect-open-001.json").is_file()
    assert (raw_dir / "bench-detect-clean-001.json").is_file()


def test_detection_case_result_omits_strict_precision_for_open_world_case() -> None:
    """Unit-level pin, independent of the fixture-corpus plumbing above: an open-world
    ``DetectionCaseResult`` carries ``strict_precision=None``, never a raised exception bubbling
    out of ``ScoreReport.strict_precision`` (D4) and never a fabricated number."""
    result = DetectionCaseResult(
        case_id="c",
        closed_world=False,
        total_issues=1,
        total_reported=1,
        found=1,
        recall=1.0,
        corpus_confirmed_precision=1.0,
        f1=1.0,
    )
    assert result.strict_precision is None


# ── B3.1 bullet 2: no credentials -> detection omitted, skipped recorded ──


def test_run_detection_reports_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "detect-corpus"
    _write_detection_case(corpus, "bench-detect-open-001", closed_world=False, issues=[])
    review_fn, calls = _stub_review_fn({})

    monkeypatch.setattr(
        "mergecraft.evals.live_run.has_credentials_for_slug",
        lambda _model: False,
    )

    metrics, skipped_reason = run_detection(
        provider="claude",
        model="claude-sonnet-5",
        corpus_dir=corpus,
        results_dir=tmp_path / "results",
        review_fn=review_fn,
    )

    assert metrics is None
    assert skipped_reason == SKIP_REASON_NO_CREDENTIAL
    assert skipped_reason == "no live credential"  # evals/README.md's exact promised string
    # Metrics omitted, never fabricated -- the review path must not even run.
    assert calls == []


def test_run_detection_reports_no_cases_even_with_valid_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 has not landed: ``evals/bench/mergecraft/`` carries zero patch-bearing cases today.
    Distinct from the missing-credential path -- pinned with credentials mocked *present* so the
    two skip reasons cannot be silently conflated."""
    monkeypatch.setattr(
        "mergecraft.evals.live_run.has_credentials_for_slug",
        lambda _model: True,
    )
    empty_corpus = tmp_path / "empty-detect-corpus"

    metrics, skipped_reason = run_detection(
        provider="claude",
        model="claude-sonnet-5",
        corpus_dir=empty_corpus,
        results_dir=tmp_path / "results",
        review_fn=_stub_review_fn({})[0],
    )

    assert metrics is None
    assert skipped_reason == SKIP_REASON_NO_CASES
    assert skipped_reason == "no patch-bearing cases"


def test_run_detection_prefers_no_cases_over_no_credential_when_both_are_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Locked precedence (B3.0 finding 3): case discovery is checked before the credential
    check, so an empty corpus reports ``SKIP_REASON_NO_CASES`` even when credentials are also
    absent -- there being nothing to detect on is the more specific, more useful diagnosis."""
    monkeypatch.setattr(
        "mergecraft.evals.live_run.has_credentials_for_slug",
        lambda _model: False,
    )
    empty_corpus = tmp_path / "empty-detect-corpus"

    _, skipped_reason = run_detection(
        provider="claude",
        model="claude-sonnet-5",
        corpus_dir=empty_corpus,
        results_dir=tmp_path / "results",
        review_fn=_stub_review_fn({})[0],
    )

    assert skipped_reason == SKIP_REASON_NO_CASES


# ── discover_detection_cases: D7 two-corpora separation ──


def test_discover_detection_cases_ignores_a_directory_without_baseline_or_patch(
    tmp_path: Path,
) -> None:
    """D7 -- ``evals/cases/`` bank entries (decision-only, no patch) must never surface as
    detection cases even if a stray directory of the same shape ends up under the detection
    corpus root. A directory with neither a recognized patch filename nor ``baseline.json`` is
    silently skipped, mirroring ``list_cases()``'s tolerant-skip behaviour in ``store.py``."""
    corpus = tmp_path / "detect-corpus"
    bank_like = corpus / "bench-correctness-off-by-one"
    bank_like.mkdir(parents=True)
    (bank_like / "notes.md").write_text("not a patch, not a baseline", encoding="utf-8")

    _write_detection_case(corpus, "bench-detect-real-001", closed_world=False, issues=[])

    cases = discover_detection_cases(corpus)

    assert [c.case_id for c in cases] == ["bench-detect-real-001"]


def test_discover_detection_cases_on_a_missing_dir_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert discover_detection_cases(missing) == []


# ── B3.0 finding 1: patch-filename reuse, verbatim, not extended ──


def test_patch_candidates_matches_harbor_agent_verbatim() -> None:
    assert PATCH_CANDIDATES == _HARBOR_PATCH_CANDIDATES


# ── B3.1 bullet 4: BenchmarkResultSet forward-compat (D3) ──


def test_benchmark_result_set_without_a_detection_section_still_parses(tmp_path: Path) -> None:
    """A result set shaped exactly like the ones B1/B2 already write (no ``detection`` or
    ``skipped_reason`` key at all -- what every ``evals/results/*.json`` committed before B3
    looks like) must still validate once those two optional fields exist.

    Built from a real ``run_structural_replay()`` call so everything *but* the two new keys is
    byte-faithful to production output, then those two keys are explicitly popped to simulate a
    pre-B3 committed file -- a dump taken *after* the fields exist always includes them (at their
    default), so popping is the only way to reconstruct what an old file on disk actually looked
    like; asserting the keys are absent first documents that this is deliberate, not a fixture
    bug.
    """
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))
    old_style_dump = run_structural_replay(bank, providers=DEFAULT_BENCHMARK_PROVIDERS).model_dump(
        mode="json"
    )
    old_style_dump.pop("detection", None)
    old_style_dump.pop("skipped_reason", None)
    assert "detection" not in old_style_dump
    assert "skipped_reason" not in old_style_dump

    restored = BenchmarkResultSet.model_validate(old_style_dump)

    assert restored.detection is None
    assert restored.skipped_reason is None
    # Structural section is untouched by the field addition.
    assert restored.metrics.cases_total == 1


def test_benchmark_result_set_still_forbids_unknown_fields() -> None:
    """D3 regression guard: adding ``detection``/``skipped_reason`` must not loosen
    ``extra='forbid'`` for genuinely unrecognized keys."""
    bank_result = run_structural_replay(Path("does-not-exist"))
    payload = bank_result.model_dump(mode="json")
    payload["not_a_real_field"] = "nope"
    with pytest.raises(ValidationError):
        BenchmarkResultSet.model_validate(payload)


# ── run_full_benchmark: the join itself ──


def test_full_benchmark_structural_section_matches_a_bare_structural_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The join must not perturb B1/B2's existing behaviour (B3.1 bullet 2's other half): the
    ``metrics``/``pins``/``case_results`` a bare ``run_structural_replay()`` call produces are
    identical whether or not detection ran alongside it."""
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))
    add_case(bank, _bank_case("synthetic-002"))

    corpus = tmp_path / "detect-corpus"
    _write_detection_case(corpus, "bench-detect-open-001", closed_world=False, issues=[])
    monkeypatch.setattr(
        "mergecraft.evals.live_run.has_credentials_for_slug",
        lambda _model: True,
    )

    direct = run_structural_replay(bank, providers=DEFAULT_BENCHMARK_PROVIDERS)
    joined = run_full_benchmark(
        bank,
        detection_corpus_dir=corpus,
        results_dir=tmp_path / "results",
        providers=DEFAULT_BENCHMARK_PROVIDERS,
        review_fn=_stub_review_fn({})[0],
    )

    assert joined.metrics == direct.metrics
    assert joined.case_results == direct.case_results
    assert joined.detection is not None
    assert joined.skipped_reason is None


def test_full_benchmark_omits_detection_when_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No credentials -> ``detection`` omitted and ``skipped`` recorded; the structural section
    still populates normally -- the join must not break B1/B2's existing behaviour when it
    cannot run (B3.1 bullet 2, full sentence)."""
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))

    corpus = tmp_path / "detect-corpus"
    _write_detection_case(corpus, "bench-detect-open-001", closed_world=False, issues=[])
    monkeypatch.setattr(
        "mergecraft.evals.live_run.has_credentials_for_slug",
        lambda _model: False,
    )

    result = run_full_benchmark(
        bank,
        detection_corpus_dir=corpus,
        results_dir=tmp_path / "results",
        providers=DEFAULT_BENCHMARK_PROVIDERS,
        review_fn=_stub_review_fn({})[0],
    )

    assert result.detection is None
    assert result.skipped_reason == SKIP_REASON_NO_CREDENTIAL
    # Structural section still populates -- the join is additive, not a gate on the rest.
    assert result.metrics.cases_total == 1
    assert result.metrics.cases_replayable == 1
    assert result.pins.corpus_commit  # unchanged VersionPins machinery still runs


def test_result_set_schema_version_bumped_to_1_2_0() -> None:
    """B3.2 checklist: bump schema -> 1.2.0 for the detection join."""
    assert RESULT_SET_SCHEMA_VERSION == "1.2.0"


# ── review-failure handling (mergeCraft self-review, PR #216) ──────────


def test_review_run_failed_excludes_case_from_scoring_not_a_zero_finding_pass(
    tmp_path: Path,
) -> None:
    """A case whose ``review_fn`` raises ``ReviewRunFailed`` is excluded from
    ``cases_run``/the aggregate and reported via ``cases_failed``/
    ``failed_case_ids`` instead -- never silently scored as "reviewed, found
    nothing" (which would depress recall/F1 for the wrong reason)."""
    corpus = tmp_path / "detect-corpus"
    _write_detection_case(corpus, "bench-detect-ok-001", closed_world=False, issues=[])
    _write_detection_case(corpus, "bench-detect-fails-001", closed_world=False, issues=[])
    cases = discover_detection_cases(corpus)

    def review_fn(case: DetectionCase) -> list[dict[str, Any]]:
        if case.case_id == "bench-detect-fails-001":
            raise ReviewRunFailed("simulated provider rate-limit error")
        return []

    metrics = run_live_detection(
        cases,
        provider="claude",
        model="claude-sonnet-5",
        review_fn=review_fn,
        results_dir=tmp_path / "results",
    )

    assert metrics.cases_run == 1
    assert metrics.cases_failed == 1
    assert metrics.failed_case_ids == ["bench-detect-fails-001"]
    assert {r.case_id for r in metrics.case_results} == {"bench-detect-ok-001"}
    # The failed case's aggregate isn't polluted with a fabricated zero-finding pass.
    assert metrics.aggregate.total_cases == 1


def test_raw_findings_dir_is_scoped_per_run_second_run_does_not_overwrite_first(
    tmp_path: Path,
) -> None:
    """A fixed shared `raw-findings/` path would let a later run silently
    overwrite an earlier publication's evidence. Two `run_live_detection`
    calls (different provider) must write to different directories, and the
    first run's raw findings must still be readable after the second."""
    corpus = tmp_path / "detect-corpus"
    _write_detection_case(corpus, "bench-detect-open-001", closed_world=False, issues=[])
    cases = discover_detection_cases(corpus)
    results_dir = tmp_path / "results"

    review_fn, _ = _stub_review_fn({"bench-detect-open-001": []})
    first = run_live_detection(
        cases,
        provider="claude",
        model="claude-sonnet-5",
        review_fn=review_fn,
        results_dir=results_dir,
    )
    second = run_live_detection(
        cases,
        provider="openai",
        model="gpt-5.1-codex",
        review_fn=review_fn,
        results_dir=results_dir,
    )

    assert first.raw_findings_dir != second.raw_findings_dir
    assert Path(first.raw_findings_dir).is_dir()
    assert (Path(first.raw_findings_dir) / "bench-detect-open-001.json").is_file()
    assert Path(second.raw_findings_dir).is_dir()
    assert (Path(second.raw_findings_dir) / "bench-detect-open-001.json").is_file()


def test_detection_case_forbids_unknown_fields() -> None:
    """Unit-level pin, independent of any orchestration: `extra='forbid'` on the new models."""
    with pytest.raises(ValidationError):
        DetectionCase(
            case_id="c",
            patch_path=Path("p"),
            baseline_path=Path("b"),
            unknown="nope",  # type: ignore[call-arg]
        )
