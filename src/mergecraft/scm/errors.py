"""SCM provider errors."""

from __future__ import annotations


class UnsupportedScmCapability(RuntimeError):
    """Raised when a provider does not implement a requested capability."""

    def __init__(self, capability: str, *, provider: str = "scm") -> None:
        self.capability = capability
        self.provider = provider
        super().__init__(
            f"{provider} does not support capability {capability!r}; operation was not emulated"
        )
