"""Azure Pipelines provider stub (K1.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.ci.types import ProviderContext, RawFailure


class AzurePipelinesProvider:
    """Declared shape only — Azure Pipelines integration is not implemented in K1."""

    supports_retry_state = False
    skip_reason = "Azure Pipelines reads are not supported yet"

    def detect(self, context: ProviderContext) -> bool:
        return bool(context.get("azure_devops_token"))

    def fetch_failures(self, pr: dict[str, object]) -> list[RawFailure]:
        _ = pr
        return []


__all__ = ["AzurePipelinesProvider"]
