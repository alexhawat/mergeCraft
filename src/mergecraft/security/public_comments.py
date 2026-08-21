"""Redact secret material before it can reach a public review comment (#362).

Exports:
    redact_secrets_for_public_comment: Strip tokens from publication bodies.
"""

from __future__ import annotations

from mergecraft.analyzers.redact import redact_secrets


def redact_secrets_for_public_comment(body: str) -> str:
    """Return ``body`` with secret-like values removed for public publication."""
    return redact_secrets(body)
