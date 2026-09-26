"""N20 / C8 / C13 — REVIEW-DOCTRINE agrees with code and pyproject (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decision **PD-D5** — the verifier cap is ``review.verificationBudget``
(default 24, ``0`` = no cap), scaled per round by ``review.roundBudgets``, and
is independent of ``analyzers.inlineBudget``. **C13** — the doctrine's Python
floor must agree with ``pyproject.toml``'s ``requires-python``.

The floor test derives the expected version from ``pyproject.toml`` rather than
hardcoding ``3.11`` so the pair cannot drift. These assertions fail until PD3;
do not xfail: RED is the point.

PD3 refinement (2026-09-26): § *Verification covers every source* must be **able
to name** ``analyzers.inlineBudget`` in order to say it is *not* the cap (PD-D5 /
P-8). The guard therefore forbids only the **claim** — whenever the key is named
(any markdown shape), its sentence must decouple it from the cap via one of
``independent`` / ``placement`` / ``governs only``.
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT

_DOCTRINE = REPO_ROOT / "docs" / "REVIEW-DOCTRINE.md"
_PYPROJECT = REPO_ROOT / "pyproject.toml"
_FLOOR_DOC = "docs/dev/python-version-floor.md"
_VERIFICATION_HEADING = "## Verification covers every source"

# The inline-budget key in any markdown shape: `analyzers.inlineBudget`,
# `analyzers inlineBudget`, or the split `` `analyzers` `inlineBudget` ``.
_INLINE_BUDGET_KEY = re.compile(r"analyzers[ \t.`]{0,4}inlinebudget", re.IGNORECASE)
# A sentence naming that key must say it is not the cap.
_DECOUPLING_TERMS = ("independent", "placement", "governs only")


def _doctrine_text() -> str:
    assert _DOCTRINE.is_file(), f"missing {_DOCTRINE.relative_to(REPO_ROOT)}"
    return _DOCTRINE.read_text(encoding="utf-8")


def _verification_section() -> str:
    text = _doctrine_text()
    start = text.index(_VERIFICATION_HEADING)
    rest = text[start:]
    end = rest.find("\n## ", 1)
    return rest if end == -1 else rest[:end]


def _inline_budget_sentences(section: str) -> list[str]:
    """Split *section* into sentences and return those naming the inline-budget key."""
    return [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", section)
        if _INLINE_BUDGET_KEY.search(sentence)
    ]


def _requires_python_floor() -> str:
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*">=\s*([0-9]+\.[0-9]+)"', text, re.MULTILINE)
    assert match, 'pyproject.toml has no `requires-python = ">=X.Y"`'
    return match.group(1)


def test_verification_section_names_the_real_budget_keys() -> None:
    section = _verification_section()
    assert "review.verificationBudget" in section, (
        "the verifier-cap section must name review.verificationBudget (PD-D5)"
    )
    assert "roundBudgets" in section, (
        "the verifier-cap section must name the per-round scaler review.roundBudgets (PD-D5)"
    )


def test_verification_section_does_not_claim_the_inline_budget_caps_it() -> None:
    section = _verification_section()
    lowered = section.lower()
    # The legacy claim itself is forbidden outright.
    assert "the cap is the inline budget" not in lowered, (
        "doctrine still says the inline budget caps verification (N20 / PD-D5)"
    )
    # Naming the key is allowed — *only* to say it is not the cap. Every sentence
    # that names `analyzers.inlineBudget` (in any markdown shape, incl. the split
    # `analyzers` `inlineBudget` workaround) must also decouple it from
    # verification: it is the placement control, not the cap (PD-D5 / P-8).
    for sentence in _inline_budget_sentences(lowered):
        assert any(term in sentence for term in _DECOUPLING_TERMS), (
            "the doctrine may name `analyzers.inlineBudget` only to say it is not the "
            "verification cap; the sentence naming it must also decouple it from the "
            "cap (one of: independent / placement / governs only) (N20 / PD-D5)"
        )


def test_python_floor_agrees_with_pyproject() -> None:
    text = _doctrine_text()
    floor = _requires_python_floor()
    assert f"Python {floor}" in text, (
        f"doctrine must state the pyproject floor Python {floor} (C13 / PD3.2)"
    )
    assert _FLOOR_DOC in text, (
        f"doctrine must cross-link {_FLOOR_DOC} for the lowered floor (PD3.2)"
    )
    stale = re.search(r"3\.14[\s\S]{0,80}this project\s+requires", text)
    assert stale is None, "doctrine still claims this project requires Python 3.14 (C13 / PD3.2)"
