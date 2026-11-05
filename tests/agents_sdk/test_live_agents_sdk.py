"""Live Agents SDK smoke (skipped without credentials)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("agents")

from mergecraft.agents_sdk.model import resolve_model_config


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_resolve_model_config_has_endpoint() -> None:
    if not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENCODE_GO_API_KEY")
        or os.environ.get("MERGECRAFT_CUSTOM_PROVIDER_API_KEY")
    ):
        pytest.skip("no live model credentials")
    cfg = resolve_model_config()
    assert cfg.api_key
    assert cfg.model
