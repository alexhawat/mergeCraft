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

_SECURITY_RULE: Final[_RubricRule] = SEVERITY_RUBRIC[0]
_SECURITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = _COMPILED[0][1]
_CAPPING_RULES: Final[tuple[tuple[_RubricRule, tuple[re.Pattern[str], ...]], ...]] = _COMPILED[1:]

_BLOCKING_ASSERTED_SEVERITIES: Final[frozenset[str]] = frozenset({"Critical", "Major"})


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


def _core_impact_message(message: str) -> str:
    """Return the asserted impact before incidental prose after a semicolon."""
    return message.split(";", maxsplit=1)[0].strip()


def _matches_patterns(message: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(message) for pattern in patterns)


def _matches_security_signal(message: str) -> bool:
    return _matches_patterns(message, _SECURITY_PATTERNS)


def _core_is_genuine_style_or_docs_nit(message: str) -> bool:
    core = _core_impact_message(message)
    for rule, patterns in _CAPPING_RULES:
        if rule.get("max_severity") is None:
            continue
        if _matches_patterns(core, patterns):
            return True
    return False


def _cap_inapplicable(message: str, model_assigned_severity: str | None) -> bool:
    """Return whether capping rules must not alter this finding (D5)."""
    if _matches_security_signal(message):
        return True
    if model_assigned_severity not in _BLOCKING_ASSERTED_SEVERITIES:
        return False
    if _matches_security_signal(_core_impact_message(message)):
        return True
    return not _core_is_genuine_style_or_docs_nit(message)


def apply_severity_rubric(
    finding: Finding,
    *,
    model_assigned_severity: str | None = None,
) -> Finding:
    """Normalize inflated model severity using the code-defined rubric."""
    severity = model_assigned_severity or finding.severity
    message = finding.message
    if _cap_inapplicable(message, model_assigned_severity):
        if severity == finding.severity:
            return finding
        return finding.model_copy(update={"severity": severity})
    for rule, patterns in _CAPPING_RULES:
        categories = rule.get("categories")
        if categories and finding.category not in categories:
            continue
        if _matches_patterns(message, patterns):
            max_severity = rule.get("max_severity")
            if max_severity is not None:
                severity = _cap_severity(severity, str(max_severity))
    if severity == finding.severity:
        return finding
    return finding.model_copy(update={"severity": severity})


def infer_category_from_message(body: str) -> str:
    """Infer a taxonomy category from message text using rubric patterns."""
    if _matches_security_signal(body):
        categories = _SECURITY_RULE.get("categories")
        if categories:
            return str(categories[0])
    for rule, patterns in _CAPPING_RULES:
        categories = rule.get("categories")
        if not categories:
            continue
        if _matches_patterns(body, patterns):
            return str(categories[0])
    return "Functional Correctness"


__all__ = [
    "SEVERITY_RUBRIC",
    "SEVERITY_RUBRIC_VERSION",
    "apply_severity_rubric",
    "infer_category_from_message",
]
