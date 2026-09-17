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

_SECURITY_RULE_ID: Final[str] = "security-signal"
_ASSERTED_BLOCKING_SEVERITIES: Final[frozenset[str]] = frozenset({"Critical", "Major"})

_RULES_BY_ID: Final[dict[str, _RubricRule]] = {str(rule["id"]): rule for rule in SEVERITY_RUBRIC}
_SECURITY_RULE: Final[_RubricRule] = _RULES_BY_ID[_SECURITY_RULE_ID]


def _compile_patterns(rule: _RubricRule) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in rule["patterns"])


_SECURITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = _compile_patterns(_SECURITY_RULE)
#: Every category rule except the security lane. Security is handled explicitly
#: first (D5), so its position in ``SEVERITY_RUBRIC`` is no longer load-bearing.
_NON_SECURITY_RULES: Final[tuple[tuple[_RubricRule, tuple[re.Pattern[str], ...]], ...]] = tuple(
    (rule, _compile_patterns(rule))
    for rule in SEVERITY_RUBRIC
    if str(rule["id"]) != _SECURITY_RULE_ID
)


def _matches_any(message: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(message) for pattern in patterns)


def _matches_security_signal(message: str) -> bool:
    return _matches_any(message, _SECURITY_PATTERNS)


def _core_impact_message(message: str) -> str:
    """Return the asserted impact, excluding incidental prose after a semicolon.

    Reviewers append incidental notes (``; see README``, ``; typo``) after the
    impact they are describing. The core is what carries the claim, so the
    capping vocabulary is evaluated against it, not against the whole message.
    """
    return message.split(";", maxsplit=1)[0].strip()


def _core_is_genuine_style_or_docs_nit(message: str) -> bool:
    """Whether the asserted impact itself is a maintainability/docs nit."""
    core = _core_impact_message(message)
    return any(_matches_any(core, patterns) for _, patterns in _NON_SECURITY_RULES)


def _cap_inapplicable(message: str, asserted_severity: str) -> bool:
    """Whether D5 forbids deflating this finding.

    A security signal anywhere makes every capping rule inapplicable (the
    security lane is non-capping in both directions). Otherwise, a
    Critical/Major assertion with a non-nit core impact is impact evidence and
    is not lowered by a stray maintainability or docs word.
    """
    if _matches_security_signal(message):
        return True
    if asserted_severity not in _ASSERTED_BLOCKING_SEVERITIES:
        return False
    return not _core_is_genuine_style_or_docs_nit(message)


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
    if _cap_inapplicable(message, severity):
        if severity == finding.severity:
            return finding
        return finding.model_copy(update={"severity": severity})
    for rule, patterns in _NON_SECURITY_RULES:
        categories = rule.get("categories")
        if categories and finding.category not in categories:
            continue
        if _matches_any(message, patterns):
            max_severity = rule.get("max_severity")
            if max_severity is not None:
                severity = _cap_severity(severity, str(max_severity))
    if severity == finding.severity:
        return finding
    return finding.model_copy(update={"severity": severity})


def infer_category_from_message(body: str) -> str:
    """Infer a taxonomy category from message text using rubric patterns.

    The security lane is checked first as a deliberate precedent (D5), not by
    virtue of its position in ``SEVERITY_RUBRIC``.
    """
    if _matches_security_signal(body):
        categories = _SECURITY_RULE.get("categories")
        if categories:
            return str(categories[0])
    for rule, patterns in _NON_SECURITY_RULES:
        categories = rule.get("categories")
        if not categories:
            continue
        if _matches_any(body, patterns):
            return str(categories[0])
    return "Functional Correctness"


__all__ = [
    "SEVERITY_RUBRIC",
    "SEVERITY_RUBRIC_VERSION",
    "apply_severity_rubric",
    "infer_category_from_message",
]
