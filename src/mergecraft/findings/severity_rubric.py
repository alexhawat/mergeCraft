"""Code-defined severity rubric applied at the judge seam (DG1, G2).

Rules may include ``max_severity`` to cap inflated model severity (maint/style/docs).
Rules with ``categories`` only — e.g. ``security-signal`` — participate in
``infer_category_from_message`` but do not alter severity.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from mergecraft.review_policy.security_tokens import SECURITY_MESSAGE_PATTERNS

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

SEVERITY_RUBRIC_VERSION: Final[str] = "1.0.0"

_RubricRule = dict[str, Any]

SEVERITY_RUBRIC: Final[tuple[_RubricRule, ...]] = (
    {
        "id": "security-signal",
        "categories": ("Security & Privacy",),
        "patterns": SECURITY_MESSAGE_PATTERNS,
    },
    {
        "id": "maint-style-nit",
        "categories": ("Maintainability & Code Quality",),
        "patterns": (
            r"f-?string",
            r"percent formatting",
            r"typo",
            r"spelling",
            r"prefer .* over",
            r"style",
            r"naming",
        ),
        "max_severity": "Minor",
    },
    {
        "id": "docs-only-nit",
        "categories": ("Maintainability & Code Quality",),
        "patterns": (r"comment", r"docstring", r"readme"),
        "max_severity": "Trivial",
    },
)

_COMPILED: Final[tuple[tuple[_RubricRule, tuple[re.Pattern[str], ...]], ...]] = tuple(
    (rule, tuple(re.compile(pattern, re.IGNORECASE) for pattern in rule["patterns"]))
    for rule in SEVERITY_RUBRIC
)


def _cap_severity(current: str, maximum: str) -> str:
    from mergecraft.review_taxonomy import FINDING_SEVERITIES

    try:
        return (
            current
            if FINDING_SEVERITIES.index(current) >= FINDING_SEVERITIES.index(maximum)
            else maximum
        )
    except ValueError:
        return maximum


def apply_severity_rubric(
    finding: Finding,
    *,
    model_assigned_severity: str | None = None,
) -> Finding:
    """Normalize inflated model severity using the code-defined rubric."""
    severity = model_assigned_severity or finding.severity
    message = finding.message
    for rule, patterns in _COMPILED:
        categories = rule.get("categories")
        if categories and finding.category not in categories:
            continue
        if any(pattern.search(message) for pattern in patterns):
            max_severity = rule.get("max_severity")
            if max_severity is not None:
                severity = _cap_severity(severity, str(max_severity))
    if severity == finding.severity:
        return finding
    return finding.model_copy(update={"severity": severity})


def infer_category_from_message(body: str) -> str:
    """Infer a taxonomy category from message text using rubric patterns."""
    for rule, patterns in _COMPILED:
        categories = rule.get("categories")
        if not categories:
            continue
        if any(pattern.search(body) for pattern in patterns):
            return str(categories[0])
    return "Functional Correctness"


__all__ = [
    "SEVERITY_RUBRIC",
    "SEVERITY_RUBRIC_VERSION",
    "apply_severity_rubric",
    "infer_category_from_message",
]
