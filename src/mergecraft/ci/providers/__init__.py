"""Pipeline provider protocol (K1.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mergecraft.ci.types import ProviderContext, RawFailure


class PipelineProvider(Protocol):
    """Read-only CI pipeline adapter (K-table K1).

    ``detect`` decides whether this provider applies to the current context.
    ``fetch_failures`` returns raw failures for a pull request.
    """

    supports_retry_state: bool
    skip_reason: str | None

    def detect(self, context: ProviderContext) -> bool:
        """Return True when this provider can serve the given runtime context."""
        ...

    def fetch_failures(self, pr: dict[str, object]) -> list[RawFailure]:
        """Fetch raw failures for a PR."""
        ...


__all__ = [
    "PipelineProvider",
]
