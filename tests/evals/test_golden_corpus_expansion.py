"""W10.1 — golden / mutation corpora and extra benchmark kinds (#384).

Keep the synthetic mutation corpus separate from the human/reference corpus.
Adversarial corpora are out of scope.
Intended public API (W10.2): ``mergecraft.evals.corpora``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_GOLDEN_CATEGORIES = frozenset(
    {
        "correctness",
        "security",
        "api_breakage",
        "concurrency",
        "migration",
        "performance",
        "dependency",
        "clean",
    }
)

_CASE_KINDS = frozenset(
    {
        "historical_pr",
        "xrepo",
        "requirements",
        "large_pr",
        "incremental_review",
    }
)


def test_golden_categories_cover_issue_384() -> None:
    """Happy: the human-reviewed golden corpus spans every required defect class."""
    from mergecraft.evals.corpora import GOLDEN_CATEGORIES

    names = {str(item).casefold() for item in GOLDEN_CATEGORIES}
    missing = {item for item in _GOLDEN_CATEGORIES if item not in names}
    assert not missing, f"golden corpus missing categories: {sorted(missing)}"


def test_mutation_corpus_is_separate_from_golden() -> None:
    """Happy: synthetic mutation cases are not mixed into the human/reference corpus."""
    from mergecraft.evals.corpora import GOLDEN_CORPUS_DIR, MUTATION_CORPUS_DIR

    golden = Path(GOLDEN_CORPUS_DIR)
    mutation = Path(MUTATION_CORPUS_DIR)
    assert golden != mutation
    assert golden.name != mutation.name


def test_golden_corpus_spans_multiple_languages() -> None:
    """Happy: the expanded golden set is not a single-language Python-only bank."""
    from mergecraft.evals.corpora import golden_languages

    languages = {str(item).casefold() for item in golden_languages()}
    assert len(languages) >= 2, f"expected ≥2 languages, got {sorted(languages)}"


def test_benchmark_case_kinds_include_historical_and_incremental() -> None:
    """Happy: historical-PR, cross-repo, requirements, large-PR, incremental-review exist."""
    from mergecraft.evals.corpora import BENCHMARK_CASE_KINDS

    names = {str(item).casefold() for item in BENCHMARK_CASE_KINDS}
    missing = {item for item in _CASE_KINDS if item not in names}
    assert not missing, f"benchmark kinds missing: {sorted(missing)}"


def test_golden_categories_exclude_adversarial() -> None:
    """#384 out of scope: adversarial corpora are a separate issue."""
    from mergecraft.evals.corpora import GOLDEN_CATEGORIES

    names = {str(item).casefold() for item in GOLDEN_CATEGORIES}
    assert "adversarial" not in names


def test_unknown_corpus_kind_raises() -> None:
    """Error: looking up an unknown case kind raises KeyError or ValueError."""
    from mergecraft.evals.corpora import cases_for_kind

    with pytest.raises((KeyError, ValueError), match=r"kind|corpus"):
        cases_for_kind("not-a-kind")
