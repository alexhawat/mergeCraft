"""SCM provider errors."""

from __future__ import annotations


class UnsupportedScmCapability(RuntimeError):
    """Raised when a provider does not implement a requested capability."""

    def __init__(self, capability: str, *, provider: str = "scm") -> None:
        self.capability = capability
        self.provider = provider
        if "GitLab" in provider:
            msg = (
                f"GitLab support is not available in this release"
                f" (capability {capability!r} was requested)"
            )
        else:
            msg = (
                f"{provider} does not support capability {capability!r}; operation was not emulated"
            )
        super().__init__(msg)
