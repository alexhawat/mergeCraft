"""RED unit tests for provider registry helpers (#477 / BA).

Pins index allocation, built-in harness defaults, and registry module contracts
that back ``mergecraft provider`` verbs.
"""

from __future__ import annotations

import pytest
from tests.cli.support_provider_registry import (
    BUILTIN_HARNESS_DEFAULTS,
    EXPECTED_BUILTIN_PROVIDER_COUNT,
    import_provider_registry,
)

from mergecraft.models import PROVIDERS
from mergecraft.utils import agent_resolve as ar

_XFAIL = pytest.mark.xfail(reason="green after BA impl", strict=False)


def test_providers_catalog_has_fourteen_builtin_entries() -> None:
    """Seed source ``PROVIDERS`` must expose exactly 14 built-in catalog rows."""
    assert len(PROVIDERS) == EXPECTED_BUILTIN_PROVIDER_COUNT


@pytest.mark.parametrize(
    ("label", "expected_harness"),
    sorted(BUILTIN_HARNESS_DEFAULTS.items()),
)
@_XFAIL
def test_builtin_harness_defaults_match_agent_resolve_table(
    label: str,
    expected_harness: str,
) -> None:
    registry = import_provider_registry()
    defaults = getattr(registry, "BUILTIN_HARNESS_DEFAULTS", None)
    if defaults is None:
        pytest.fail("provider_registry.BUILTIN_HARNESS_DEFAULTS is not defined")
    assert defaults[label] == expected_harness
    assert ar._harness_supports_provider(expected_harness, label)


@_XFAIL
def test_allocate_env_index_returns_max_plus_one() -> None:
    registry = import_provider_registry()
    allocate = getattr(registry, "allocate_env_index", None)
    if allocate is None:
        pytest.fail("provider_registry.allocate_env_index is not implemented")

    assert allocate([{"envIndex": 1}, {"envIndex": 3}]) == 4
    assert allocate([{"envIndex": 7}]) == 8
    assert allocate([]) == 1


@_XFAIL
def test_allocate_env_index_never_reuses_gaps() -> None:
    registry = import_provider_registry()
    allocate = getattr(registry, "allocate_env_index", None)
    if allocate is None:
        pytest.fail("provider_registry.allocate_env_index is not implemented")

    # Gap at 2 must not be recycled — always max + 1.
    assert allocate([{"envIndex": 1}, {"envIndex": 5}]) == 6


@_XFAIL
def test_harness_support_predicate_is_reused_not_duplicated() -> None:
    registry = import_provider_registry()
    supports = getattr(registry, "harness_supports_provider", None)
    if supports is None:
        pytest.fail("provider_registry.harness_supports_provider is not implemented")
    assert supports is ar._harness_supports_provider


@_XFAIL
def test_list_supported_harnesses_is_generated_from_code() -> None:
    registry = import_provider_registry()
    list_fn = getattr(registry, "list_supported_harnesses", None)
    if list_fn is None:
        pytest.fail("provider_registry.list_supported_harnesses is not implemented")

    names = {row[0] if isinstance(row, (tuple, list)) else row.name for row in list_fn()}
    assert names == {"opencode", "codex", "claude", "gemini", "cursor"}
