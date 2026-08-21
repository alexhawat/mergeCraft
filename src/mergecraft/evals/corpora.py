"""Golden, mutation, and extra benchmark corpora (#384).

The human-reviewed golden PR corpus and the synthetic mutation corpus live
in **separate directories**. Adversarial corpora stay in
:mod:`mergecraft.evals.adversarial` / :mod:`mergecraft.evals.adversarial_corpora`
and are not mixed in here.

No I/O at import time: on-disk paths are constants; catalog rows are packaged
in this module. Call :func:`cases_for_kind` / :func:`golden_languages` to
inspect them.

Exports:
    GOLDEN_CATEGORIES: Defect classes the golden corpus must cover.
    BENCHMARK_CASE_KINDS: Extra benchmark kinds (#384).
    GOLDEN_CORPUS_DIR: Human/reference corpus directory.
    MUTATION_CORPUS_DIR: Synthetic mutation corpus directory.
    CorpusCase: One labelled corpus row.
    golden_languages: Languages represented in the golden corpus.
    cases_for_kind: Look up benchmark (or golden) rows by kind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "BENCHMARK_CASE_KINDS",
    "GOLDEN_CATEGORIES",
    "GOLDEN_CORPUS_DIR",
    "MUTATION_CORPUS_DIR",
    "BenchmarkCaseKind",
    "CorpusCase",
    "GoldenCategory",
    "cases_for_kind",
    "golden_cases",
    "golden_languages",
    "mutation_cases",
]

GoldenCategory = Literal[
    "correctness",
    "security",
    "api_breakage",
    "concurrency",
    "migration",
    "performance",
    "dependency",
    "clean",
]

BenchmarkCaseKind = Literal[
    "historical_pr",
    "xrepo",
    "requirements",
    "large_pr",
    "incremental_review",
]

GOLDEN_CATEGORIES: Final[frozenset[str]] = frozenset(
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

BENCHMARK_CASE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "historical_pr",
        "xrepo",
        "requirements",
        "large_pr",
        "incremental_review",
    }
)

GOLDEN_CORPUS_DIR: Final[Path] = Path("evals/cases/golden")
MUTATION_CORPUS_DIR: Final[Path] = Path("evals/cases/mutation")


class CorpusCase(BaseModel):
    """One labelled golden, mutation, or extra-kind benchmark row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    language: str
    framework: str
    category: str = ""
    kind: str = ""
    source: Literal["human", "synthetic"] = "human"
    path: str = ""
    start_line: int = 1
    end_line: int = 1
    notes: str = ""


_GOLDEN_CASES: Final[tuple[CorpusCase, ...]] = (
    CorpusCase(
        id="golden-python-fastapi-correctness-001",
        title="Optional nested config dereference without a null guard",
        language="python",
        framework="fastapi",
        category="correctness",
        kind="historical_pr",
        source="human",
        path="app/settings.py",
        start_line=44,
        end_line=48,
        notes="Human-reviewed historical PR; Python/FastAPI.",
    ),
    CorpusCase(
        id="golden-typescript-express-security-001",
        title="Unparameterized SQL concatenated from a request query",
        language="typescript",
        framework="express",
        category="security",
        kind="historical_pr",
        source="human",
        path="src/routes/search.ts",
        start_line=18,
        end_line=26,
        notes="Human-reviewed historical PR; TypeScript/Express.",
    ),
    CorpusCase(
        id="golden-go-chi-api-breakage-001",
        title="Exported handler signature drop breaks downstream clients",
        language="go",
        framework="chi",
        category="api_breakage",
        kind="xrepo",
        source="human",
        path="pkg/api/handlers.go",
        start_line=90,
        end_line=110,
        notes="Cross-repo consumer still pins the old signature.",
    ),
    CorpusCase(
        id="golden-rust-tokio-concurrency-001",
        title="Shared HashMap mutated across tasks without a lock",
        language="rust",
        framework="tokio",
        category="concurrency",
        kind="historical_pr",
        source="human",
        path="src/cache.rs",
        start_line=55,
        end_line=80,
        notes="Human-reviewed concurrency defect.",
    ),
    CorpusCase(
        id="golden-python-django-migration-001",
        title="Destructive column drop without a expand/contract step",
        language="python",
        framework="django",
        category="migration",
        kind="historical_pr",
        source="human",
        path="app/migrations/0042_drop_legacy_slug.py",
        start_line=1,
        end_line=24,
        notes="Human-reviewed migration failure.",
    ),
    CorpusCase(
        id="golden-java-spring-performance-001",
        title="N+1 repository call inside a request mapping",
        language="java",
        framework="spring",
        category="performance",
        kind="large_pr",
        source="human",
        path="src/main/java/com/example/OrderService.java",
        start_line=120,
        end_line=160,
        notes="Large-PR performance regression case.",
    ),
    CorpusCase(
        id="golden-javascript-npm-dependency-001",
        title="Direct dependency pin removed while lockfile still resolves it",
        language="javascript",
        framework="npm",
        category="dependency",
        kind="historical_pr",
        source="human",
        path="package.json",
        start_line=12,
        end_line=40,
        notes="Human-reviewed dependency issue.",
    ),
    CorpusCase(
        id="golden-ruby-rails-clean-001",
        title="Docs-only README wording with no behavioural diff",
        language="ruby",
        framework="rails",
        category="clean",
        kind="incremental_review",
        source="human",
        path="README.md",
        start_line=1,
        end_line=12,
        notes="Clean PR — expected empty blocker set.",
    ),
    CorpusCase(
        id="golden-python-requirements-001",
        title="Ticket requires authz check that the diff never adds",
        language="python",
        framework="fastapi",
        category="correctness",
        kind="requirements",
        source="human",
        path="docs/tickets/AUTHZ-19.md",
        start_line=1,
        end_line=30,
        notes="Requirements-to-diff mismatch.",
    ),
)

_MUTATION_CASES: Final[tuple[CorpusCase, ...]] = (
    CorpusCase(
        id="mutation-python-off-by-one-001",
        title="Synthetic off-by-one on a slice bound",
        language="python",
        framework="stdlib",
        category="correctness",
        kind="historical_pr",
        source="synthetic",
        path="src/window.py",
        start_line=10,
        end_line=12,
        notes="Mutation corpus — not mixed into golden/.",
    ),
    CorpusCase(
        id="mutation-go-nil-deref-001",
        title="Synthetic nil pointer dereference",
        language="go",
        framework="stdlib",
        category="correctness",
        kind="historical_pr",
        source="synthetic",
        path="internal/ptr.go",
        start_line=8,
        end_line=14,
        notes="Mutation corpus — not mixed into golden/.",
    ),
)

_KIND_INDEX: Final[dict[str, tuple[CorpusCase, ...]]] = {
    kind: tuple(case for case in _GOLDEN_CASES if case.kind == kind)
    for kind in sorted(BENCHMARK_CASE_KINDS)
}


def golden_languages() -> frozenset[str]:
    """Return the languages represented in the human-reviewed golden corpus."""
    return frozenset(case.language for case in _GOLDEN_CASES)


def cases_for_kind(kind: str) -> tuple[CorpusCase, ...]:
    """Return packaged cases for a benchmark kind.

    Args:
        kind: A member of :data:`BENCHMARK_CASE_KINDS`.

    Returns:
        The packaged rows for that kind (may be empty only if the kind is known
        and not yet populated).

    Raises:
        ValueError: If ``kind`` is not a known corpus kind.
    """
    key = kind.strip().casefold()
    if key not in BENCHMARK_CASE_KINDS:
        msg = f"unknown corpus kind: {kind}"
        raise ValueError(msg)
    return _KIND_INDEX[key]


def mutation_cases() -> tuple[CorpusCase, ...]:
    """Return the synthetic mutation corpus (separate from golden)."""
    return _MUTATION_CASES


def golden_cases() -> tuple[CorpusCase, ...]:
    """Return the human-reviewed golden corpus."""
    return _GOLDEN_CASES
