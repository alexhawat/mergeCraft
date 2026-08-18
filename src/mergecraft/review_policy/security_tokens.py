"""Shared security vocabulary for dedup and severity rubric (DG1)."""

from __future__ import annotations

from typing import Final

DOMAIN_HINT_GROUPS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"sql", "query", "injection", "unsanitized", "binding"}),
    frozenset({"timeout", "retry", "loop"}),
    frozenset({"secret", "token", "credential", "password"}),
)

SECURITY_MESSAGE_PATTERNS: Final[tuple[str, ...]] = (
    r"secret",
    r"token",
    r"credential",
    r"password",
    r"injection",
    r"\bauth\b",
    r"\bsql\b",
    r"xss",
)

__all__ = ["DOMAIN_HINT_GROUPS", "SECURITY_MESSAGE_PATTERNS"]
