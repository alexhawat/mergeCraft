"""Live Agents SDK smoke (skipped without credentials)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("agents")

from mergecraft.agents_sdk.model import resolve_model_config


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_resolve_model_config_has_endpoint() -> None:
    custom_key = os.environ.get("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "").strip()
    custom_base = os.environ.get("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "").strip()
    if custom_key and custom_base and not os.environ.get("MERGECRAFT_AGENTS_SDK_MODEL", "").strip():
        pytest.skip("MERGECRAFT_AGENTS_SDK_MODEL required with custom provider env")
    if not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENCODE_GO_API_KEY")
        or (custom_key and custom_base and os.environ.get("MERGECRAFT_AGENTS_SDK_MODEL"))
    ):
        pytest.skip("no live model credentials")
    cfg = resolve_model_config()
    assert cfg.api_key
    assert cfg.model
