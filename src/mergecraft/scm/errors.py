"""SCM provider errors."""

from __future__ import annotations


class UnsupportedScmCapability(RuntimeError):
    """Raised when a provider does not implement a requested capability."""

    def __init__(
        self,
        capability: str,
        *,
        provider: str = "scm",
        message: str | None = None,
    ) -> None:
        self.capability = capability
        self.provider = provider
        msg = message or (
            f"{provider} does not support capability {capability!r}; operation was not emulated"
        )
        super().__init__(msg)
