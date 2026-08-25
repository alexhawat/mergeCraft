"""``build_custom_provider`` reads workflow ``LLM_PROVIDER_<N>_API_KEY`` env."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.cli.support_provider_registry import bootstrap_nous_registry

from mergecraft.agents.opencode import build_custom_provider

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

NOUS_MODEL = "nous/deepseek/deepseek-v4-flash"
NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"


@pytest.fixture(autouse=True)
def _clear_custom_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for n in range(1, 4):
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}", raising=False)
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}", raising=False)
        monkeypatch.delenv(f"LLM_PROVIDER_{n}_API_KEY", raising=False)


def test_build_custom_provider_reads_llm_provider_workflow_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    bootstrap_nous_registry(
        tmp_path,
        monkeypatch,
        model_id="deepseek/deepseek-v4-flash",
        api_key="workflow-registry-key",
        url=NOUS_BASE_URL,
    )
    monkeypatch.setenv("LLM_PROVIDER_1_API_KEY", "workflow-registry-key")
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", raising=False)
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1",
        NOUS_BASE_URL,
    )

    emitted = build_custom_provider(NOUS_MODEL)
    assert emitted is not None
    nous_block = emitted["nous"]
    assert nous_block["options"]["baseURL"] == NOUS_BASE_URL
    assert nous_block["options"]["apiKey"] == "workflow-registry-key"
