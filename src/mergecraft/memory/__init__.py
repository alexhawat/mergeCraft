"""Dismissal-signal eligibility for repository memory.

Durable negative-memory storage and filtering live in mergecraft.utils.memory.
"""

from __future__ import annotations

from mergecraft.memory.store import ingest_dismissal_signal

__all__ = [
    "ingest_dismissal_signal",
]
