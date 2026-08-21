"""Enterprise runtime settings parsed from ``.mergecraft/config.yaml`` (#381).

Defaults are inert: telemetry stays on, proxy/CA are unset, and an empty
residency allow-list means *no extra policy* (existing reviews keep working).
A non-empty ``allowed_regions`` fails closed via :func:`enforce_data_residency`.
Model regions come from :data:`mergecraft.models.PROVIDERS` (per-provider
``data_residency``; unset means unknown and is refused). Vertex BYOK is
``eu-west-1``. Gateway models (OpenCode, OpenRouter, TokenHub, MiniMax, Nous)
have no declared region.

Exports:
    EnterpriseSettings: Nested ``enterprise:`` block on :class:`RepoSettings`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.enterprise.telemetry import TelemetryMode, resolve_telemetry_mode

__all__ = ["EnterpriseSettings"]

TelemetryConfigName = Literal["on", "opt-out", "off"]


class EnterpriseSettings(BaseModel):
    """Repo-config block that drives enterprise runtime enforcement."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    telemetry: TelemetryConfigName = "on"
    https_proxy: str = Field(default="", alias="httpsProxy")
    no_proxy: str = Field(default="", alias="noProxy")
    ca_file: str | None = Field(default=None, alias="caFile")
    allowed_regions: tuple[str, ...] = Field(default=(), alias="allowedRegions")
    retention_days: int | None = Field(default=None, alias="retentionDays", gt=0)

    @field_validator("telemetry", mode="before")
    @classmethod
    def _coerce_telemetry(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            mode = resolve_telemetry_mode(explicit=value)
        except ValueError as exc:
            msg = f"enterprise.telemetry: {exc}"
            raise ValueError(msg) from exc
        if mode is TelemetryMode.ON:
            return "on"
        if mode is TelemetryMode.OPT_OUT:
            return "opt-out"
        return "off"
