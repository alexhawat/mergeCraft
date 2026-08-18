"""Backward-compatible re-export — canonical implementation is ``analyzers.dedup``."""

from __future__ import annotations

from mergecraft.analyzers.dedup import dedupe_findings

__all__ = ["dedupe_findings"]
