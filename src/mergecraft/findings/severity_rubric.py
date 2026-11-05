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

SEVERITY_RUBRIC_VERSION: Final[str] = "1.1.0"

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
            r"\bprefer\s+f-?strings?\s+(?:over|to)\s+percent formatting\b",
            r"\b(?:prefer|use)\s+(?:snake_case|camelCase|PascalCase)\b",
            r"\b(?:cosmetic|stylistic|formatting-only|style-only)\s+(?:change|issue|nit)\b",
            r"^(?:a\s+)?(?:typo|spelling mistake|spelling error)[.!]?$",
        ),
        "max_severity": "Minor",
    },
    {
        "id": "docs-only-nit",
        "categories": ("Maintainability & Code Quality",),
        "patterns": (
            r"\b(?:update|clarify|reword|correct|fix|improve)\s+(?:(?:the|this|a)\s+)?"
            r"(?:comment|docstring|readme|documentation)\b"
            r"(?!\s+(?:handler|api|endpoint|function|method|route|request|service)\b)",
            r"\b(?:typo|spelling(?: mistake| error)?)\s+in\s+(?:the\s+)?"
            r"(?:comment|docstring|readme|documentation|prose|heading|text)\b",
        ),
        "max_severity": "Trivial",
    },
)

_SECURITY_RULE_ID: Final[str] = "security-signal"

_RULES_BY_ID: Final[dict[str, _RubricRule]] = {str(rule["id"]): rule for rule in SEVERITY_RUBRIC}
_SECURITY_RULE: Final[_RubricRule] = _RULES_BY_ID[_SECURITY_RULE_ID]


def _compile_patterns(rule: _RubricRule) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in rule["patterns"])


_SECURITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = _compile_patterns(_SECURITY_RULE)
#: Cosmetic intent rules. Security vocabulary alone is not an impact claim;
#: a positive cosmetic request can mention the module's security domain.
_NON_SECURITY_RULES: Final[tuple[tuple[_RubricRule, tuple[re.Pattern[str], ...]], ...]] = tuple(
    (rule, _compile_patterns(rule))
    for rule in SEVERITY_RUBRIC
    if str(rule["id"]) != _SECURITY_RULE_ID
)

# These describe consequences, unlike vocabulary such as "comment", "typo"
# or "token". Look across the entire finding: an impact after a punctuation
# boundary is still impact. Unknown claims keep their asserted severity; only
# positively recognized cosmetic requests are eligible for a cap.
_IMPACT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:rais(?:e[sd]?|ing)|throw\w*|crash\w*|fail\w*|break\w*|hang\w*|"
        r"deadlock\w*|corrupt\w*|leak\w*|bypass\w*|drop\w*|los(?:e[sd]?|ing)|"
        r"delet\w*|allow\w*|permit\w*|expos\w*|emit\w*|return\w*|caus\w*|"
        r"prevent\w*|block\w*|malformed|broken|regression|unhandled|unsafe|"
        r"cannot|can't|doesn't|does not|no longer)\b",
        r"\b(?:injection|vulnerabilit\w*|exploit\w*|request forgery|path traversal|"
        r"remote code execution|privilege escalation|data loss)\b",
        r"\b(?:missing|lacks?|without|never)\b[^.;!?\n]*\b"
        r"(?:validation|authorization|authentication|timeout|permission check|sanitization)\b",
        r"\b(?:incorrect|wrong|invalid|empty)\b[^.;!?\n]*\b"
        r"(?:result|return|output|response|value|data|request|query|command|status code)\b",
    )
)


def _matches_any(message: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(message) for pattern in patterns)


def _matches_security_signal(message: str) -> bool:
    return _matches_any(message, _SECURITY_PATTERNS)


def _core_impact_message(message: str) -> str:
    """Return the leading claim used to establish positive cosmetic intent.

    A trailing style suggestion does not turn an earlier defect into a nit.
    Functional impact is checked separately across the complete message.
    """
    return message.split(";", maxsplit=1)[0].strip()


def _core_is_genuine_style_or_docs_nit(message: str) -> bool:
    """Recognize a cosmetic request only when no contrary impact is asserted."""
    if _matches_any(message, _IMPACT_PATTERNS):
        return False
    core = _core_impact_message(message)
    return any(_matches_any(core, patterns) for _, patterns in _NON_SECURITY_RULES)


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
    if not _core_is_genuine_style_or_docs_nit(message):
        if severity == finding.severity:
            return finding
        return finding.model_copy(update={"severity": severity})
    for rule, patterns in _NON_SECURITY_RULES:
        categories = rule.get("categories")
        if categories and finding.category not in categories:
            continue
        if _matches_any(_core_impact_message(message), patterns):
            max_severity = rule.get("max_severity")
            if max_severity is not None:
                severity = _cap_severity(severity, str(max_severity))
    if severity == finding.severity:
        return finding
    return finding.model_copy(update={"severity": severity})


def infer_category_from_message(body: str) -> str:
    """Infer a taxonomy category from message text using rubric patterns.

    Explicit cosmetic intent takes precedence over incidental vocabulary:
    updating a comment in an authentication module is still documentation.
    Functional/security impact prevents that cosmetic inference.
    """
    if _core_is_genuine_style_or_docs_nit(body):
        return "Maintainability & Code Quality"
    if _matches_security_signal(body):
        categories = _SECURITY_RULE.get("categories")
        if categories:
            return str(categories[0])
    return "Functional Correctness"


__all__ = [
    "SEVERITY_RUBRIC",
    "SEVERITY_RUBRIC_VERSION",
    "apply_severity_rubric",
    "infer_category_from_message",
]
