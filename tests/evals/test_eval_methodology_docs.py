"""W10.1 — published eval methodology page (#384, D10).

Numbers go to a ``docs/`` page registered in ``docs/manifest.yaml``, never
``README.md``. Never close #140 (precision/recall/F1 publication).
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from tests.ci.workflow_support import REPO_ROOT, read_text

_METHODOLOGY_PATH = "docs/eval-methodology.md"
_EVAL_SCORE_TERMS = re.compile(r"\b(?:precision|recall|F1)\b", re.IGNORECASE)
_BENCHMARK_NUMBER = re.compile(
    r"(?:\b\d+(?:\.\d+)?%|\b\d+\.\d+\b|\b\d+\s*/\s*\d+\b)",
)
_SUPERIORITY = re.compile(r"\b(?:better than|outperforms|superior to)\b", re.IGNORECASE)


def _pages() -> list[dict[str, Any]]:
    data = yaml.safe_load((REPO_ROOT / "docs" / "manifest.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    pages = data.get("pages")
    assert isinstance(pages, list)
    return [row for row in pages if isinstance(row, dict)]


def test_no_eval_scores_on_landing_readme_d10() -> None:
    """GREEN (D10): landing README must not publish precision/recall/F1 scores.

    Mirrors ``tests/docs/test_docs_gate.py::test_no_eval_scores_on_landing_readme``.
    """
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    offenders: list[str] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not _EVAL_SCORE_TERMS.search(line):
            continue
        if _BENCHMARK_NUMBER.search(line):
            offenders.append(f"line {index}: {line.strip()}")
    assert not offenders, (
        "README must not publish precision/recall/F1 benchmark numbers:\n" + "\n".join(offenders)
    )


def test_eval_methodology_is_not_readme() -> None:
    """GREEN (D10): the methodology path is a docs/ page, never the landing README."""
    assert _METHODOLOGY_PATH != "README.md"
    assert _METHODOLOGY_PATH.startswith("docs/")


def test_eval_methodology_registered_in_manifest() -> None:
    """Happy: methodology is a manifest row (append-only, D17/D18)."""
    row = next((item for item in _pages() if item.get("path") == _METHODOLOGY_PATH), None)
    assert row is not None, f"docs/manifest.yaml missing {_METHODOLOGY_PATH}"


def test_eval_methodology_page_exists_and_names_metrics() -> None:
    """Happy: the docs page describes the metric set without living on README."""
    text = read_text(_METHODOLOGY_PATH)
    lowered = text.casefold()
    for term in ("blocker precision", "latency", "cost per review", "ablation"):
        assert term in lowered, f"{_METHODOLOGY_PATH} missing {term!r}"


def test_eval_methodology_does_not_claim_superiority_without_numbers() -> None:
    """Error: do not claim superiority until benchmark results support it."""
    text = read_text(_METHODOLOGY_PATH)
    for match in _SUPERIORITY.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end]
        assert _BENCHMARK_NUMBER.search(line), (
            "methodology must not claim superiority without a number on the same line: "
            f"{line.strip()}"
        )


def test_eval_methodology_does_not_steal_issue_140_publication() -> None:
    """#140 owns publishing precision/recall/F1; this page must not claim that job."""
    text = read_text(_METHODOLOGY_PATH).casefold()
    assert "issue 140" in text or "#140" in text or "does not replace" in text
