"""DQ1 RED — fail-closed ``cloud_chain`` for unsupported labels (#497, DQ3)."""

from __future__ import annotations

import pytest
import typer
from tests.cli.support_provider_registry import (
    AUTH_KIND_CLOUD_CHAIN,
    BEDROCK_INDEXED_KEYS,
    VERTEX_INDEXED_KEYS,
    import_provider_cmd,
    indexed_env_key,
)


def _keys_for(label: str, env_index: int = 7) -> list[str]:
    module = import_provider_cmd()
    entry = {"label": label, "envIndex": env_index, "authKind": AUTH_KIND_CLOUD_CHAIN}
    return list(module.indexed_credential_keys(entry))


@pytest.mark.xfail(reason="green after DQ3: cloud_chain fail-closed label guard", strict=False)
def test_custom_label_does_not_return_bedrock_suffixes() -> None:
    """Unsupported labels must not silently inherit Bedrock suffix mapping."""
    try:
        keys = _keys_for("mycloud")
    except (ValueError, typer.Exit):
        return
    for suffix in BEDROCK_INDEXED_KEYS:
        assert indexed_env_key(7, suffix) not in keys


@pytest.mark.xfail(reason="green after DQ3: cloud_chain error message contract", strict=False)
def test_error_names_the_label_and_the_supported_set() -> None:
    """Failure must name the offending label and the supported provider set (D10)."""
    label = "mycloud"
    with pytest.raises((ValueError, typer.Exit)) as exc_info:
        _keys_for(label)
    detail = str(exc_info.value)
    if isinstance(exc_info.value, typer.Exit):
        detail = f"exit {exc_info.value.exit_code}"
    combined = detail.casefold()
    assert label in combined
    assert "bedrock" in combined
    assert "vertex" in combined


def test_bedrock_cloud_chain_unchanged() -> None:
    """Bedrock ``cloud_chain`` mapping stays on AWS indexed suffixes."""
    keys = _keys_for("bedrock", env_index=3)
    for suffix in BEDROCK_INDEXED_KEYS:
        assert indexed_env_key(3, suffix) in keys
    assert indexed_env_key(3, "API_KEY") not in keys


def test_vertex_cloud_chain_unchanged() -> None:
    """Vertex ``cloud_chain`` mapping stays on credentials-path suffixes."""
    keys = _keys_for("vertex", env_index=4)
    for suffix in VERTEX_INDEXED_KEYS:
        assert indexed_env_key(4, suffix) in keys
    assert indexed_env_key(4, "API_KEY") not in keys
