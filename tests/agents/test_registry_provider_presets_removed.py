"""RED tests for BE #481 — remove Nous/TokenHub/MiniMax gateway presets.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BE — test-creator. Pins removal of named presets, env constants, and
``_OPENCODE_NATIVE_PROVIDERS`` / ``_KNOWN_CATALOG_PROVIDERS`` special-casing.
"""

from __future__ import annotations

import inspect

import pytest
from tests.cli.support_provider_registry import (
    REMOVED_GATEWAY_MODULE_SYMBOLS,
    REMOVED_GATEWAY_PRESET_LABELS,
)

from mergecraft.agents import openai_compatible_gateways as gateways
from mergecraft.utils import agent_resolve as ar

BE_XFAIL = pytest.mark.xfail(reason="green after BE impl", strict=False)


@BE_XFAIL
def test_gateway_presets_exclude_nous_tokenhub_minimax() -> None:
    """``GATEWAY_PRESETS`` must not carry named Nous/TokenHub/MiniMax rows."""
    preset_labels = {str(key).lower() for key in gateways.GATEWAY_PRESETS}
    overlap = REMOVED_GATEWAY_PRESET_LABELS & preset_labels
    assert not overlap, f"named gateway presets still present: {sorted(overlap)}"


@BE_XFAIL
@pytest.mark.parametrize("symbol", REMOVED_GATEWAY_MODULE_SYMBOLS)
def test_named_gateway_env_constants_removed(symbol: str) -> None:
    """Preset-specific env/base-url constants are deleted from the gateways module."""
    assert not hasattr(gateways, symbol), (
        f"openai_compatible_gateways.{symbol} must be removed in BE (#481)"
    )


@BE_XFAIL
def test_opencode_native_providers_exclude_gateway_preset_labels() -> None:
    """``_OPENCODE_NATIVE_PROVIDERS`` must not special-case nous/tokenhub/minimax."""
    overlap = REMOVED_GATEWAY_PRESET_LABELS & set(ar._OPENCODE_NATIVE_PROVIDERS)
    assert not overlap, f"_OPENCODE_NATIVE_PROVIDERS still special-cases: {sorted(overlap)}"


@BE_XFAIL
def test_known_catalog_providers_exclude_gateway_preset_labels() -> None:
    """``_KNOWN_CATALOG_PROVIDERS`` must not list removed preset provider ids."""
    overlap = REMOVED_GATEWAY_PRESET_LABELS & set(ar._KNOWN_CATALOG_PROVIDERS)
    assert not overlap, f"_KNOWN_CATALOG_PROVIDERS still lists preset providers: {sorted(overlap)}"


@BE_XFAIL
def test_agent_resolve_has_no_nous_tokenhub_minimax_branches() -> None:
    """Runtime resolver must not branch on hardcoded nous/tokenhub/minimax ids."""
    source = inspect.getsource(ar)
    forbidden_snippets = (
        'provider in {"nous", "tokenhub"}',
        '"nous", "tokenhub"',
        'provider == "minimax"',
        '"nous", "tokenhub", "minimax"',
    )
    hits = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not hits, f"agent_resolve still contains preset branches: {hits}"
