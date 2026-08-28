"""Canonical redaction placeholder shared by tracing and analyzer redactors (MCB-30).

Leaf module: must not import from :mod:`mergecraft.tracing.redaction` or
:mod:`mergecraft.analyzers.redact` to avoid import cycles.

Exports:
    REDACTION_SENTINEL -- single literal emitted wherever a secret value is removed.
"""

from __future__ import annotations

REDACTION_SENTINEL = "<redacted>"

__all__ = ["REDACTION_SENTINEL"]
