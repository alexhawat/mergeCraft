"""Review-skill eval corpus — fixture-only scoring (RS4, D11, F9).

Scores the ``.github/skills/code-review`` instruction bundle against disposable
fixture repos and recorded scenario rubrics. No live provider calls (D16).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from loguru import logger

from mergecraft.context.instruction_discovery import render_review_context
from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING

_CORPUS_DIR: Final[Path] = Path(__file__).resolve().parent / "cases" / "skill"
_DEFAULT_FIXTURE_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "skill_eval"
)
_DOCTRINE_SKILL_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[3] / ".github" / "skills" / "code-review"
)
_BASELINE_POINTER_BODY: Final[str] = (
    "---\n"
    "name: code-review\n"
    "description: Review pull requests for this repository.\n"
    "---\n\n"
    "Follow [REVIEW-CHECKS.md](../../../REVIEW-CHECKS.md) and "
    "[docs/REVIEW-DOCTRINE.md](../../../docs/REVIEW-DOCTRINE.md).\n"
)
_FINGERPRINT_RE: Final = re.compile(r"<!-- mergecraft-finding:v1:([0-9a-f]+) -->")


@dataclass(frozen=True, slots=True)
class SkillEvalScores:
    """Per-variant score for one corpus case."""

    baseline: float
    tip: float


@dataclass(frozen=True, slots=True)
class SkillEvalCaseReport:
    """Outcome for one corpus case."""

    passed: bool
    summary: str
    baseline_score: float
    tip_score: float


@dataclass(frozen=True, slots=True)
class SkillEvalCorpusReport:
    """Aggregate outcome across the skill eval corpus."""

    passed: bool
    tip_score: float
    baseline_score: float
    summary: str
    per_case: dict[str, SkillEvalScores]


def _load_cases(corpus_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(corpus_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            cases.append(payload)
    return cases


def _install_baseline_pointer(skill_dir: Path) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_BASELINE_POINTER_BODY, encoding="utf-8")


def _install_tip_doctrine(skill_dir: Path) -> None:
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    shutil.copytree(_DOCTRINE_SKILL_ROOT, skill_dir)


def _render_for_variant(repo_root: Path, variant: str) -> str:
    skill_dir = repo_root / ".github" / "skills" / "code-review"
    if variant == "baseline-pointer":
        _install_baseline_pointer(skill_dir)
    elif variant == "tip-doctrine":
        _install_tip_doctrine(skill_dir)
    else:
        msg = f"unknown skill variant: {variant}"
        raise ValueError(msg)
    return render_review_context(
        repo_root=repo_root,
        trust_tier="trusted",
        repo="acme/fixture",
        commit_sha="skill-eval",
    )


def _score_prompt_assertions(case: dict[str, Any], rendered: str) -> float:
    """Fraction of doctrine markers present — low for pointer, high for tip."""
    assertions = case.get("prompt_assertions")
    if not isinstance(assertions, dict):
        return 0.0
    required = assertions.get("tip_must_contain", [])
    if not isinstance(required, list) or not required:
        return 0.0
    hits = sum(1 for needle in required if str(needle) in rendered)
    return hits / len(required)


def _score_review_mentions(case: dict[str, Any], rendered: str) -> float:
    assertions = case.get("review_assertions")
    if not isinstance(assertions, dict):
        return 0.0
    required = assertions.get("with_skill_must_mention", [])
    if not isinstance(required, list) or not required:
        return 0.0
    hits = sum(1 for needle in required if str(needle) in rendered)
    return hits / len(required)


def _withdrawn_fingerprints(repo_root: Path) -> set[str]:
    learnings = repo_root / ".mergecraft" / "learnings.md"
    if not learnings.is_file():
        return set()
    return set(_FINGERPRINT_RE.findall(learnings.read_text(encoding="utf-8")))


def _score_abstention(case: dict[str, Any], rendered: str, repo_root: Path) -> float:
    assertions = case.get("review_assertions")
    if not isinstance(assertions, dict):
        return 0.0
    if assertions.get("verdict") != "approve":
        return 0.0
    max_findings = assertions.get("max_findings")
    if max_findings != 0:
        return 0.0
    readme = repo_root / "README.md"
    if not readme.is_file():
        return 0.0
    if "proceses" not in readme.read_text(encoding="utf-8"):
        return 0.0
    silence_markers = ("Silence is a result", "approve")
    if not all(marker in rendered for marker in silence_markers):
        return 0.0
    return 1.0


def _score_withdrawn(case: dict[str, Any], rendered: str, repo_root: Path) -> float:
    assertions = case.get("review_assertions")
    if not isinstance(assertions, dict):
        return 0.0
    if not assertions.get("must_not_raise_withdrawn_fingerprint"):
        return 0.0
    heading = str(assertions.get("withdrawn_heading") or WITHDRAWN_FINDINGS_HEADING)
    if heading not in rendered:
        return 0.0
    if "Never re-raise" not in rendered and "never re-raise" not in rendered.casefold():
        return 0.0
    if not _withdrawn_fingerprints(repo_root):
        return 0.0
    return 1.0


_SCENARIO_SCORERS: dict[str, Any] = {
    "e1": lambda case, rendered, repo_root: _score_prompt_assertions(case, rendered),
    "e2": lambda case, rendered, repo_root: _score_review_mentions(case, rendered),
    "e3": lambda case, rendered, repo_root: _score_abstention(case, rendered, repo_root),
    "e4": lambda case, rendered, repo_root: _score_withdrawn(case, rendered, repo_root),
}


def _score_variant(
    case: dict[str, Any],
    *,
    fixture_root: Path,
    variant: str,
) -> float:
    with tempfile.TemporaryDirectory(prefix="mergecraft-skill-eval-") as tmp:
        repo_root = Path(tmp) / "repo"
        shutil.copytree(fixture_root, repo_root)
        rendered = _render_for_variant(repo_root, variant)
        scenario = str(case.get("scenario") or "")
        scorer = _SCENARIO_SCORERS.get(scenario)
        if scorer is not None:
            return float(scorer(case, rendered, repo_root))
    return 0.0


def score_skill_eval_case(
    *,
    case: dict[str, Any],
    fixture_root: Path,
) -> SkillEvalCaseReport:
    """Score one corpus case for baseline-pointer vs tip-doctrine."""
    variants = case.get("skill_variants")
    if not isinstance(variants, dict):
        return SkillEvalCaseReport(
            passed=False,
            summary="case missing skill_variants",
            baseline_score=0.0,
            tip_score=0.0,
        )
    baseline_name = str(variants.get("baseline") or "baseline-pointer")
    tip_name = str(variants.get("tip") or "tip-doctrine")
    baseline_score = _score_variant(case, fixture_root=fixture_root, variant=baseline_name)
    tip_score = _score_variant(case, fixture_root=fixture_root, variant=tip_name)
    passed = tip_score > baseline_score
    case_id = str(case.get("id") or "unknown")
    summary = f"{case_id}: baseline={baseline_score:.2f} tip={tip_score:.2f}" + (
        " PASS" if passed else " FAIL"
    )
    return SkillEvalCaseReport(
        passed=passed,
        summary=summary,
        baseline_score=baseline_score,
        tip_score=tip_score,
    )


def evaluate_skill_eval_corpus(
    *,
    corpus_dir: Path | None = None,
    fixture_root: Path | None = None,
) -> SkillEvalCorpusReport:
    """Score every on-disk skill eval case and aggregate the corpus gate."""
    resolved_corpus = corpus_dir or _CORPUS_DIR
    resolved_fixture_root = fixture_root or _DEFAULT_FIXTURE_ROOT
    per_case: dict[str, SkillEvalScores] = {}
    baseline_total = 0.0
    tip_total = 0.0
    failures: list[str] = []
    for case in _load_cases(resolved_corpus):
        case_id = str(case.get("id") or "unknown")
        fixture_name = str(case.get("fixture_repo") or "")
        fixture_repo = resolved_fixture_root / fixture_name
        if not fixture_repo.is_dir():
            failures.append(f"{case_id}: missing fixture {fixture_repo}")
            per_case[case_id] = SkillEvalScores(baseline=0.0, tip=0.0)
            continue
        report = score_skill_eval_case(case=case, fixture_root=fixture_repo)
        per_case[case_id] = SkillEvalScores(
            baseline=report.baseline_score,
            tip=report.tip_score,
        )
        baseline_total += report.baseline_score
        tip_total += report.tip_score
        if not report.passed:
            failures.append(report.summary)
        elif report.tip_score < report.baseline_score:
            failures.append(f"{case_id}: tip regressed vs baseline")
    passed = tip_total > baseline_total and not failures
    summary = f"corpus baseline={baseline_total:.2f} tip={tip_total:.2f}" + (
        " PASS" if passed else " FAIL"
    )
    if failures:
        summary = f"{summary}; {'; '.join(failures)}"
    return SkillEvalCorpusReport(
        passed=passed,
        tip_score=tip_total,
        baseline_score=baseline_total,
        summary=summary,
        per_case=per_case,
    )


def _format_report(report: SkillEvalCorpusReport) -> str:
    lines = [
        report.summary,
        f"aggregate: baseline={report.baseline_score:.2f} tip={report.tip_score:.2f}",
    ]
    for case_id, scores in sorted(report.per_case.items()):
        lines.append(f"  {case_id}: baseline={scores.baseline:.2f} tip={scores.tip:.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``make eval-skill-corpus``."""
    parser = argparse.ArgumentParser(description="Run the review-skill eval corpus gate.")
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=_CORPUS_DIR,
        help="Directory containing skill eval JSON cases.",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=_DEFAULT_FIXTURE_ROOT,
        help="Root directory for per-case fixture repos.",
    )
    args = parser.parse_args(argv)
    report = evaluate_skill_eval_corpus(
        corpus_dir=args.corpus_dir,
        fixture_root=args.fixture_root,
    )
    logger.info("{}", _format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
