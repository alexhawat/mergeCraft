"""RS1.6 — review-skill eval corpus gate (RS4, D11, F9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_CORPUS_DIR = Path(__file__).resolve().parents[2] / "src/mergecraft/evals/cases/skill"
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "skill_eval"


def _load_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for path in sorted(_CORPUS_DIR.glob("*.json")):
        cases.append(json.loads(path.read_text(encoding="utf-8")))
    assert cases, "skill eval corpus must not be empty"
    return cases


def _case_ids() -> list[str]:
    return [str(case["id"]) for case in _load_cases()]


@pytest.mark.parametrize("case_id", _case_ids())
def test_skill_eval_case_scores(case_id: str) -> None:
    from mergecraft.evals.skill import score_skill_eval_case

    case = next(item for item in _load_cases() if item["id"] == case_id)
    fixture_repo = _FIXTURE_ROOT / str(case["fixture_repo"])
    assert fixture_repo.is_dir(), f"missing fixture repo: {fixture_repo}"
    report = score_skill_eval_case(case=case, fixture_root=fixture_repo)
    assert report.passed, report.summary


def test_skill_beats_its_baseline_on_the_corpus() -> None:
    from mergecraft.evals.skill import evaluate_skill_eval_corpus

    report = evaluate_skill_eval_corpus(corpus_dir=_CORPUS_DIR, fixture_root=_FIXTURE_ROOT)
    assert report.tip_score > report.baseline_score, report.summary
    for case_id, scores in report.per_case.items():
        assert scores.tip >= scores.baseline, f"{case_id} regressed vs baseline"
