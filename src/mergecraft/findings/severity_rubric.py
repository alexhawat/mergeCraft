"""Code-defined severity rubric applied at the judge seam (DG1, G2)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

SEVERITY_RUBRIC_VERSION: Final[str] = "1.0.0"

_RubricRule = dict[str, Any]

SEVERITY_RUBRIC: Final[tuple[_RubricRule, ...]] = (
    {
        "id": "maint-style-nit",
        "categories": ("Maintainability & Code Quality",),
        "patterns": (
            r"f-?string",
            r"percent formatting",
            r"typo",
            r"spelling",
            r"prefer .* over",
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
            severity = _cap_severity(severity, str(rule["max_severity"]))
    if severity == finding.severity:
        return finding
    return finding.model_copy(update={"severity": severity})


__all__ = [
    "SEVERITY_RUBRIC",
    "SEVERITY_RUBRIC_VERSION",
    "apply_severity_rubric",
]
