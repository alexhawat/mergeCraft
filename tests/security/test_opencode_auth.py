"""OpenCode Zen auth.json helpers."""

from __future__ import annotations

from mergecraft.security.opencode_auth import (
    build_opencode_zen_auth_json,
    opencode_api_key_from_auth_json,
    opencode_auth_usable,
)


def test_opencode_auth_usable_accepts_zen_shape() -> None:
    raw = build_opencode_zen_auth_json("zen-key-placeholder")
    assert opencode_auth_usable(raw)


def test_opencode_auth_usable_rejects_garbage() -> None:
    assert not opencode_auth_usable("not-json")
    assert not opencode_auth_usable('{"other": {"type": "api", "key": "x"}}')


def test_opencode_api_key_from_auth_json_prefers_opencode_entry() -> None:
    raw = build_opencode_zen_auth_json("primary-key")
    assert opencode_api_key_from_auth_json(raw) == "primary-key"
