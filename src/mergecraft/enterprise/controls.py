"""Enterprise runtime settings parsed from ``.mergecraft/config.yaml`` (#381).

Defaults are inert: telemetry stays on, proxy/CA are unset, and an empty
residency allow-list means *no extra policy* (existing reviews keep working).
A non-empty ``allowed_regions`` fails closed via :func:`enforce_data_residency`.

Exports:
    EnterpriseSettings: Nested ``enterprise:`` block on :class:`RepoSettings`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["EnterpriseSettings"]


class EnterpriseSettings(BaseModel):
    """Repo-config block that drives enterprise runtime enforcement."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    telemetry: str = "on"
    https_proxy: str = Field(default="", alias="httpsProxy")
    no_proxy: str = Field(default="", alias="noProxy")
    ca_file: str | None = Field(default=None, alias="caFile")
    allowed_regions: tuple[str, ...] = Field(default=(), alias="allowedRegions")
    retention_days: int | None = Field(default=None, alias="retentionDays")
