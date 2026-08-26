"""Run-scope binding errors for review publication (MCB-05, D3)."""

from __future__ import annotations


class PublicationScopeError(ValueError):
    """A review mutation targeted a PR or commit outside the bound run scope."""


__all__ = ["PublicationScopeError"]
