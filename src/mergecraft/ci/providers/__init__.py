"""Pipeline provider protocol and registry (K1.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from mergecraft.ci.types import ProviderContext, RawFailure


class PipelineProvider(Protocol):
    """Read-only CI pipeline adapter (K-table K1).

    ``detect`` decides whether this provider applies to the current context.
    ``fetch_failures`` returns raw failures for a pull request; stub providers
    return an empty list and expose a non-empty ``skip_reason``.
    """

    supports_retry_state: bool
    skip_reason: str | None

    def detect(self, context: ProviderContext) -> bool:
        """Return True when this provider can serve the given runtime context."""
        ...

    def fetch_failures(self, pr: dict[str, object]) -> list[RawFailure]:
        """Fetch raw failures for a PR; stubs return ``[]`` with ``skip_reason`` set."""
        ...


def _build_registry() -> dict[str, PipelineProvider]:
    from mergecraft.ci.providers.azure import AzurePipelinesProvider
    from mergecraft.ci.providers.circleci import CircleCIProvider
    from mergecraft.ci.providers.github_actions import GitHubActionsProvider
    from mergecraft.ci.providers.gitlab import GitLabCIProvider

    return {
        "github_actions": cast("PipelineProvider", GitHubActionsProvider()),
        "circleci": cast("PipelineProvider", CircleCIProvider()),
        "gitlab": cast("PipelineProvider", GitLabCIProvider()),
        "azure": cast("PipelineProvider", AzurePipelinesProvider()),
    }


_PROVIDER_REGISTRY = _build_registry()


def get_provider(provider_id: str) -> PipelineProvider:
    """Return a registered provider by id."""
    try:
        return _PROVIDER_REGISTRY[provider_id]
    except KeyError as err:
        msg = f"unknown CI provider: {provider_id}"
        raise KeyError(msg) from err


__all__ = [
    "PipelineProvider",
    "get_provider",
]
