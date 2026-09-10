"""Shared security vocabulary for dedup and severity rubric (DG1)."""

from __future__ import annotations

from typing import Final

DOMAIN_HINT_GROUPS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"sql", "query", "injection", "unsanitized", "binding"}),
    frozenset({"timeout", "retry", "loop"}),
    frozenset({"secret", "token", "credential", "password", "hardcoded", "key"}),
    frozenset({"deserializ", "pickle", "unpickle"}),
    frozenset({"traversal", "ssrf", "csrf", "xxe"}),
    frozenset({"privilege", "escalation", "pollution", "redirect"}),
    frozenset({"execution", "rce", "eval", "unsafe"}),
)

SECURITY_MESSAGE_PATTERNS: Final[tuple[str, ...]] = (
    r"\bsecret\b",
    r"\btoken\b",
    r"\bcredential\b",
    r"\bpassword\b",
    r"\binjection\b",
    r"\bauth\b",
    r"\bauthentication\b",
    r"\bauthorization\b",
    r"\bunauthenticated\b",
    r"\bauthoriz(?:e|es|ed|ing)\b",
    r"\bunauth\w*\b",
    r"\bsql\b",
    r"\bxss\b",
    r"\b(?:remote code execution|rce)\b",
    r"\bdeserializ\w*\b",
    r"\bpickle\b",
    r"\bpath traversal\b",
    r"\bssrf\b",
    r"\bcsrf\b",
    r"\bxxe\b",
    r"\bprivilege escalation\b",
    r"\bprototype pollution\b",
    r"\bopen redirect\b",
    r"\bhardcoded key\b",
)

__all__ = ["DOMAIN_HINT_GROUPS", "SECURITY_MESSAGE_PATTERNS"]
