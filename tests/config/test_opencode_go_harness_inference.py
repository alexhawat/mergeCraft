"""``opencode-go`` resolves like ``provider status`` when Zen credentials exist."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.runtime_provider_registry import infer_harness_for_slug

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_infer_harness_for_opencode_go_without_registry_row(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "zen-test-key")
    assert infer_harness_for_slug("opencode-go/deepseek-v4-pro") == "opencode"
