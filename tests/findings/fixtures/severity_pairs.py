"""Matched-paraphrase severity corpus (RA1.6, D15).

The r2 audit earned its N4 escalation with *pairs*: the same asserted impact
with and without an incidental word. The claim under test is that the pair
agrees, so the corpus lives here as data rather than as inline strings
duplicated across test modules.

``impact_message`` carries the asserted impact and the severity the reviewing
model assigned. ``incidental_message`` is the same impact wearing a word that
belongs to the maintainability/docs vocabulary (``readme``, ``comment``,
``style``, ``naming``, ``typo``). The cap is only reachable when the inferred
category lands on ``Maintainability & Code Quality``, which is exactly the
lexical inference N4/N20 exploit.

Source of truth: ``plans/audit-2026-09-10-r2.md`` §4, reproduced verbatim in
``.ignorelocal/waves/evidence/ra0-baseline.txt``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class SeverityPair:
    """One asserted impact and the same impact with an incidental word."""

    case_id: str
    asserted_severity: str
    impact_message: str
    incidental_message: str


SECURITY_IMPACT: Final[str] = "Authentication bypass in the session check"
CORRECTNESS_IMPACT: Final[str] = "The retry loop never sets a timeout"

#: The seven r2 rows: six incidental cases and their controls.
SEVERITY_PAIRS: Final[tuple[SeverityPair, ...]] = (
    SeverityPair(
        case_id="critical-security-readme",
        asserted_severity="Critical",
        impact_message=SECURITY_IMPACT,
        incidental_message=f"{SECURITY_IMPACT}; see README",
    ),
    SeverityPair(
        case_id="critical-security-comment",
        asserted_severity="Critical",
        impact_message=SECURITY_IMPACT,
        incidental_message=f"{SECURITY_IMPACT}; see the comment",
    ),
    SeverityPair(
        case_id="critical-security-style",
        asserted_severity="Critical",
        impact_message=SECURITY_IMPACT,
        incidental_message=f"{SECURITY_IMPACT}; style",
    ),
    SeverityPair(
        case_id="critical-security-naming",
        asserted_severity="Critical",
        impact_message=SECURITY_IMPACT,
        incidental_message=f"{SECURITY_IMPACT}; naming",
    ),
    SeverityPair(
        case_id="critical-security-typo",
        asserted_severity="Critical",
        impact_message=SECURITY_IMPACT,
        incidental_message=f"{SECURITY_IMPACT}; typo",
    ),
    SeverityPair(
        case_id="major-correctness-comment",
        asserted_severity="Major",
        impact_message=CORRECTNESS_IMPACT,
        incidental_message=f"{CORRECTNESS_IMPACT}; see the comment",
    ),
)

#: The six incidental rows only (the seven controls are ``impact_message``).
INCIDENTAL_PAIRS: Final[tuple[SeverityPair, ...]] = SEVERITY_PAIRS


# ---------------------------------------------------------------------------
# Author-family corpus (RA3 regression): a prose word that begins with ``auth``
# must not be read as a security signal. An incidental ``authors`` /
# ``authoritative`` in a style or docs finding must not lift it across a
# blocking boundary; a genuine correctness impact must keep its asserted grade.
# ---------------------------------------------------------------------------

STYLE_NIT_IMPACT: Final[str] = "Prefer f-string over percent formatting"
DOCS_NIT_IMPACT: Final[str] = "Update the comment in this module"


@dataclass(frozen=True, slots=True)
class AuthorFamilyPair:
    """A prose finding with and without an incidental author-family word.

    ``control_message`` omits the word; ``incidental_message`` carries it. The
    word does not change the asserted impact, so the pair must agree on the
    severity that reaches the gate.
    """

    case_id: str
    asserted_severity: str
    control_message: str
    incidental_message: str


AUTHOR_FAMILY_PAIRS: Final[tuple[AuthorFamilyPair, ...]] = (
    AuthorFamilyPair(
        case_id="critical-style-authors-tail",
        asserted_severity="Critical",
        control_message=STYLE_NIT_IMPACT,
        incidental_message=f"{STYLE_NIT_IMPACT}; the authors guide documents this",
    ),
    AuthorFamilyPair(
        case_id="critical-style-authorship-core",
        asserted_severity="Critical",
        control_message=STYLE_NIT_IMPACT,
        incidental_message="The authorship rules say prefer f-string over percent formatting",
    ),
    AuthorFamilyPair(
        case_id="critical-docs-authoritative-tail",
        asserted_severity="Critical",
        control_message=DOCS_NIT_IMPACT,
        incidental_message=f"{DOCS_NIT_IMPACT}; this is authoritative",
    ),
    AuthorFamilyPair(
        case_id="critical-correctness-authors-tail",
        asserted_severity="Critical",
        control_message=CORRECTNESS_IMPACT,
        incidental_message=f"{CORRECTNESS_IMPACT}; the authors guide documents this",
    ),
)

# ---------------------------------------------------------------------------
# Property-test corpus (RA1.2): impact statements x incidental tokens.
# ---------------------------------------------------------------------------

#: Asserted impacts, each paired with the severity the model assigned.
IMPACT_STATEMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("Critical", "Authentication bypass in the session check"),
    ("Critical", "Authorization check missing on the admin route"),
    ("Critical", "Unauthenticated users can reach the admin endpoint"),
    ("Critical", "Hardcoded secret committed in the settings module"),
    ("Critical", "SQL injection in the query builder"),
    ("Critical", "Server-side request forgery via a user-supplied URL"),
    ("Major", "The retry loop never sets a timeout"),
    ("Major", "Missing validation on the request body"),
)

#: Incidental tokens that belong to the docs / style vocabulary, plus the
#: ``author`` word family — ordinary prose that must not read as a security
#: signal (RA3 regression).
INCIDENTAL_TOKENS: Final[tuple[str, ...]] = (
    "see README",
    "see the comment",
    "style",
    "naming",
    "typo",
    "docstring",
    "authors",
    "authoring",
    "authored",
    "authorship",
    "authoritative",
    "authority",
    "authorities",
)


def incidental_message(impact: str, incidental: str) -> str:
    """Append one incidental token to an asserted impact statement."""
    return f"{impact}; {incidental}"


__all__ = [
    "AUTHOR_FAMILY_PAIRS",
    "CORRECTNESS_IMPACT",
    "DOCS_NIT_IMPACT",
    "IMPACT_STATEMENTS",
    "INCIDENTAL_PAIRS",
    "INCIDENTAL_TOKENS",
    "SECURITY_IMPACT",
    "SEVERITY_PAIRS",
    "STYLE_NIT_IMPACT",
    "AuthorFamilyPair",
    "SeverityPair",
    "incidental_message",
]
