"""RED unit tests for provider auth strategy helpers (#478 / BB).

Pins indexed secret naming, auth-kind dispatch, and seeded ``authKind`` defaults
that back ``mergecraft provider auth``.
"""

from __future__ import annotations

import pytest
from tests.cli.support_provider_registry import (
    AUTH_KIND_API_KEY,
    AUTH_KIND_CLOUD_CHAIN,
    AUTH_KIND_DEVICE_CODE,
    AUTH_KIND_OAUTH,
    AUTH_KIND_PRIMARY_SUFFIX,
    BB_XFAIL,
    BEDROCK_INDEXED_KEYS,
    EXPECTED_SEEDED_AUTH_KINDS,
    VERTEX_INDEXED_KEYS,
    import_provider_cmd,
    import_provider_registry,
    indexed_env_key,
    require_provider_auth_symbols,
)


@pytest.mark.parametrize(
    ("auth_kind", "suffix"),
    sorted(AUTH_KIND_PRIMARY_SUFFIX.items()),
)
@BB_XFAIL
def test_indexed_credential_keys_for_auth_kind(auth_kind: str, suffix: str) -> None:
    module = require_provider_auth_symbols()
    keys_fn = module.indexed_credential_keys
    entry = {"label": "demo", "envIndex": 2, "authKind": auth_kind}
    keys = keys_fn(entry)
    assert indexed_env_key(2, suffix) in keys


@BB_XFAIL
def test_cloud_chain_bedrock_keys_exclude_api_key_suffix() -> None:
    module = require_provider_auth_symbols()
    keys_fn = module.indexed_credential_keys
    entry = {"label": "bedrock", "envIndex": 3, "authKind": AUTH_KIND_CLOUD_CHAIN}
    keys = keys_fn(entry)
    for suffix in BEDROCK_INDEXED_KEYS:
        assert indexed_env_key(3, suffix) in keys
    assert indexed_env_key(3, "API_KEY") not in keys


@BB_XFAIL
def test_cloud_chain_vertex_keys_prefer_credentials_path() -> None:
    module = require_provider_auth_symbols()
    keys_fn = module.indexed_credential_keys
    entry = {"label": "vertex", "envIndex": 4, "authKind": AUTH_KIND_CLOUD_CHAIN}
    keys = keys_fn(entry)
    for suffix in VERTEX_INDEXED_KEYS:
        assert indexed_env_key(4, suffix) in keys
    assert indexed_env_key(4, "API_KEY") not in keys


@pytest.mark.parametrize(
    "auth_kind",
    [AUTH_KIND_API_KEY, AUTH_KIND_OAUTH, AUTH_KIND_DEVICE_CODE, AUTH_KIND_CLOUD_CHAIN],
)
@BB_XFAIL
def test_resolve_auth_strategy_returns_handler_per_kind(auth_kind: str) -> None:
    module = require_provider_auth_symbols()
    strategy = module.resolve_auth_strategy(auth_kind)
    assert callable(getattr(strategy, "run", None)) or callable(strategy)


@pytest.mark.parametrize(
    ("label", "expected_kind"),
    sorted(EXPECTED_SEEDED_AUTH_KINDS.items()),
)
@BB_XFAIL
def test_seeded_builtin_auth_kind_defaults(label: str, expected_kind: str) -> None:
    registry = import_provider_registry()
    kind_fn = getattr(registry, "default_auth_kind_for_label", None)
    if kind_fn is None:
        pytest.fail("provider_registry.default_auth_kind_for_label is not implemented")
    assert kind_fn(label) == expected_kind


@BB_XFAIL
def test_provider_auth_cmd_registered_on_provider_app() -> None:
    module = import_provider_cmd()
    app = module.app
    registered = {cmd.name for cmd in app.registered_commands}
    assert "auth" in registered
