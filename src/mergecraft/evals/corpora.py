"""Golden, mutation, and extra benchmark corpora (#384).

The human-reviewed golden PR corpus and the synthetic mutation corpus live
in **separate directories**. Adversarial corpora stay in
:mod:`mergecraft.evals.adversarial` / :mod:`mergecraft.evals.adversarial_corpora`
and are not mixed in here.

No I/O at import time: on-disk paths are constants. Call
:func:`cases_for_kind` / :func:`golden_languages` / :func:`golden_cases` to
load JSON from packaged module resources (the wheel catalog), falling back
to a checkout ``evals/cases/`` tree when present.

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

import json
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable
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

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


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


def _cases_from_path(directory: Path) -> tuple[CorpusCase, ...]:
    """Load every ``*.json`` row from a filesystem directory."""
    cases: list[CorpusCase] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases.append(CorpusCase.model_validate(payload))
    return tuple(cases)


def _cases_from_traversable(directory: Traversable) -> tuple[CorpusCase, ...]:
    """Load every ``*.json`` row from a packaged resource directory."""
    cases: list[CorpusCase] = []
    for item in sorted(directory.iterdir(), key=lambda entry: entry.name):
        if not item.name.endswith(".json") or not item.is_file():
            continue
        payload = json.loads(item.read_text(encoding="utf-8"))
        cases.append(CorpusCase.model_validate(payload))
    return tuple(cases)


def _packaged_cases(kind: str) -> tuple[CorpusCase, ...]:
    """Load *kind* (``golden`` / ``mutation``) from wheel/package resources."""
    packaged = files("mergecraft.evals").joinpath("cases", kind)
    if not packaged.is_dir():
        return ()
    return _cases_from_traversable(packaged)


def _resolved_dir(declared: Path) -> Path:
    """Prefer *declared* when it exists (cwd), else the checkout-relative path."""
    if declared.is_dir():
        return declared
    return _REPO_ROOT / declared


def _load_cases(declared: Path) -> tuple[CorpusCase, ...]:
    """Load every ``*.json`` row for *declared* (cwd, package, or checkout)."""
    if declared.is_dir():
        return _cases_from_path(declared)
    packaged = _packaged_cases(declared.name)
    if packaged:
        return packaged
    checkout = _resolved_dir(declared)
    if checkout.is_dir() and checkout != declared:
        return _cases_from_path(checkout)
    msg = f"corpus directory does not exist: {declared}"
    raise FileNotFoundError(msg)


def golden_languages() -> frozenset[str]:
    """Return the languages represented in the human-reviewed golden corpus."""
    return frozenset(case.language for case in golden_cases())


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
    return tuple(case for case in golden_cases() if case.kind == key)


def mutation_cases() -> tuple[CorpusCase, ...]:
    """Return the synthetic mutation corpus (separate from golden)."""
    return _load_cases(MUTATION_CORPUS_DIR)


def golden_cases() -> tuple[CorpusCase, ...]:
    """Return the human-reviewed golden corpus."""
    return _load_cases(GOLDEN_CORPUS_DIR)
