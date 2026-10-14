"""Credential detection for OpenCode Zen catalog models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.security.opencode_auth import build_opencode_zen_auth_json

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
from mergecraft.utils import agent_resolve as ar


def test_has_opencode_zen_auth_via_auth_json(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_AUTH_JSON", build_opencode_zen_auth_json("k"))
    assert ar._has_opencode_zen_auth()


def test_has_opencode_zen_auth_via_api_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_AUTH_JSON", raising=False)
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    assert ar._has_opencode_zen_auth()


def test_cli_auth_available_for_opencode_provider(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_AUTH_JSON", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    assert not ar._cli_auth_available("opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    assert ar._cli_auth_available("opencode-go")
