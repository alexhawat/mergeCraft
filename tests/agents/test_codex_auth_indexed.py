"""Indexed Codex credentials reach the isolated run home's ``auth.json`` (RA1.1, N19/D4).

An indexed-only ``device_code`` setup maps ``LLM_PROVIDER_1_CODEX_AUTH_JSON``
into the resolved child environment, but the baseline ``_setup_codex_auth``
reads ``os.environ`` instead — so the file is never written. The observable is
the file on disk in the isolated run home, not the child env.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from tests.agents.conftest import make_agent_run_context
from tests.cli.support_provider_registry import (
    scaffold_mergecraft_home,
    write_registry_provider_row,
)

if TYPE_CHECKING:
    import pytest

_INDEXED_AUTH = json.dumps(
    {"tokens": {"access_token": "indexed-access", "refresh_token": "indexed-refresh"}}
)
_FLAT_AUTH = json.dumps(
    {"tokens": {"access_token": "flat-access", "refresh_token": "flat-refresh"}}
)


def _codex() -> Any:
    import importlib

    return importlib.import_module("mergecraft.agents.codex")


def _ctx(tmp_path: Any) -> Any:
    return make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")


def _register_indexed_device_code(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="openai",
        harness="codex",
        env_index=1,
        auth_kind="device_code",
    )


def _auth_path(codex: Any, ctx: Any) -> Any:
    return codex._codex_home(ctx) / "auth.json"


def test_indexed_codex_auth_json_writes_run_home_auth_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex = _codex()
    _register_indexed_device_code(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_1_CODEX_AUTH_JSON", _INDEXED_AUTH)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _ctx(tmp_path)

    codex._build_env(ctx)

    auth_path = _auth_path(codex, ctx)
    assert auth_path.is_file(), "indexed device_code credential wrote no auth.json"
    assert auth_path.read_text(encoding="utf-8") == _INDEXED_AUTH


def test_flat_codex_auth_json_still_writes_auth_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control — the ambient flat spelling keeps working."""
    codex = _codex()
    monkeypatch.setenv("CODEX_AUTH_JSON", _FLAT_AUTH)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _ctx(tmp_path)

    codex._build_env(ctx)

    auth_path = _auth_path(codex, ctx)
    assert auth_path.is_file()
    assert auth_path.read_text(encoding="utf-8") == _FLAT_AUTH


def test_indexed_and_flat_conflict_resolves_to_the_registry_credential(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex = _codex()
    _register_indexed_device_code(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_1_CODEX_AUTH_JSON", _INDEXED_AUTH)
    monkeypatch.setenv("CODEX_AUTH_JSON", _FLAT_AUTH)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _ctx(tmp_path)

    codex._build_env(ctx)

    auth_path = _auth_path(codex, ctx)
    assert auth_path.is_file()
    assert auth_path.read_text(encoding="utf-8") == _INDEXED_AUTH


def test_mixed_indexed_api_key_and_flat_auth_prefers_registry_api_key(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolved registry credential outranks the ambient flat ``CODEX_AUTH_JSON``.

    Post-review regression from PR #711: when the active ``openai`` registry row
    is ``api_key`` based, ``_with_flat_codex_auth`` still re-inserted an ambient
    flat ``CODEX_AUTH_JSON`` whenever the resolved mapping lacked that *different*
    credential. ``resolve_codex_broker_posture`` then preferred subscription over
    the API key, so the stale flat subscription silently overrode the selected
    registry key (broker skipped; the flat ``auth.json`` written). The contract
    is that the resolved registry credential wins.
    """
    codex = _codex()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="openai",
        harness="codex",
        env_index=1,
        auth_kind="api_key",
    )
    monkeypatch.setenv("LLM_PROVIDER_1_API_KEY", "indexed-api-key")
    monkeypatch.setenv("CODEX_AUTH_JSON", _FLAT_AUTH)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _ctx(tmp_path)

    resolved = codex._resolved_parent_credentials(ctx)

    assert resolved.get("OPENAI_API_KEY") == "indexed-api-key"
    assert codex.CODEX_AUTH_ENV not in resolved, (
        "the ambient flat CODEX_AUTH_JSON overrode a resolved registry API key"
    )

    posture = codex.resolve_codex_broker_posture(
        codex_auth_json=resolved.get(codex.CODEX_AUTH_ENV, ""),
        openai_api_key=resolved.get("OPENAI_API_KEY", ""),
    )
    assert posture.active is True
    assert posture.auth_mode == "api_key"

    codex._build_env(ctx)

    auth_path = _auth_path(codex, ctx)
    assert not auth_path.is_file() or auth_path.read_text(encoding="utf-8") != _FLAT_AUTH, (
        "the stale flat subscription payload was written as the run home's auth.json"
    )


def test_flat_codex_auth_json_fallback_survives_empty_codex_registry(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control — with no registry credential for Codex the flat fallback still applies.

    Hermetic counterpart to ``test_flat_codex_auth_json_still_writes_auth_file``:
    the mergeCraft home is scaffolded and the CWD moved to it, so the assertion
    cannot be satisfied by the developer's own repo config. Nothing resolves for
    ``openai``/``codex`` (no registry row), so the ambient flat ``CODEX_AUTH_JSON``
    must still be threaded through ``_build_env`` into the run home's ``auth.json``.
    """
    codex = _codex()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_AUTH_JSON", _FLAT_AUTH)
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _ctx(tmp_path)

    resolved = codex._resolved_parent_credentials(ctx)
    assert resolved.get(codex.CODEX_AUTH_ENV) == _FLAT_AUTH
    assert "OPENAI_API_KEY" not in resolved

    codex._build_env(ctx)

    auth_path = _auth_path(codex, ctx)
    assert auth_path.is_file()
    assert auth_path.read_text(encoding="utf-8") == _FLAT_AUTH


def test_setup_codex_auth_does_not_read_ambient_os_environ(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4 — patch the real seam: the resolved mapping is what was consumed."""
    codex = _codex()
    _register_indexed_device_code(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_1_CODEX_AUTH_JSON", _INDEXED_AUTH)
    monkeypatch.setenv("CODEX_AUTH_JSON", _FLAT_AUTH)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    captured: dict[str, Any] = {}

    def _spy(ctx: Any, *args: Any, **kwargs: Any) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(codex, "_setup_codex_auth", _spy)
    ctx = _ctx(tmp_path)

    codex._build_env(ctx)

    values = [*captured.get("args", ()), *captured.get("kwargs", {}).values()]
    candidates = [value for value in values if isinstance(value, Mapping)]
    assert any(mapping.get("CODEX_AUTH_JSON") == _INDEXED_AUTH for mapping in candidates), (
        "the resolved credential mapping was not threaded into _setup_codex_auth"
    )
    assert all(mapping.get("CODEX_AUTH_JSON") != _FLAT_AUTH for mapping in candidates), (
        "the ambient flat credential was consumed instead of the resolved mapping"
    )
