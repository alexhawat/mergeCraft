"""Tests for secret sanitization and allowlist filtering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.utils.secrets import (
    clear_env_allowlist,
    filter_env,
    is_sensitive_env_name,
    resolve_env,
    sanitize_secret,
    set_env_allowlist,
)

if TYPE_CHECKING:
    import pytest


def test_is_sensitive_env_name() -> None:
    assert is_sensitive_env_name("ANTHROPIC_API_KEY")
    assert is_sensitive_env_name("GITHUB_TOKEN")
    assert is_sensitive_env_name("db_password")
    assert not is_sensitive_env_name("PATH")
    assert not is_sensitive_env_name("GITHUB_REPOSITORY")


def test_sanitize_secret() -> None:
    assert sanitize_secret("ANTHROPIC_API_KEY", "sk-ant-secret\n") == "sk-ant-secret"
    assert sanitize_secret("ANTHROPIC_API_KEY", "sk-ant-clean") == "sk-ant-clean"
    assert sanitize_secret("ANTHROPIC_API_KEY", "   \n") is None


def test_filter_env_default_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env_allowlist()
    env = {
        "PATH": "/usr/bin",
        "HOME": "/home/runner",
        "GITHUB_REPOSITORY": "acme/repo",
        "GITHUB_TOKEN": "ghs_secret",
        "ANTHROPIC_API_KEY": "sk-ant",
        "MY_CUSTOM": "nope",
    }
    filtered = filter_env(env)
    assert filtered["PATH"] == "/usr/bin"
    assert filtered["GITHUB_REPOSITORY"] == "acme/repo"
    assert "GITHUB_TOKEN" not in filtered
    assert "ANTHROPIC_API_KEY" not in filtered
    assert "MY_CUSTOM" not in filtered


def test_filter_env_user_allowlist() -> None:
    clear_env_allowlist()
    set_env_allowlist("ANTHROPIC_API_KEY\nMY_CUSTOM\n")
    env = {
        "PATH": "/usr/bin",
        "ANTHROPIC_API_KEY": "sk-ant",
        "MY_CUSTOM": "yes",
        "OPENAI_API_KEY": "sk-openai",
    }
    filtered = filter_env(env)
    assert filtered["ANTHROPIC_API_KEY"] == "sk-ant"
    assert filtered["MY_CUSTOM"] == "yes"
    assert "OPENAI_API_KEY" not in filtered
    clear_env_allowlist()


def test_resolve_env_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env_allowlist()
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    restricted = resolve_env("restricted")
    assert "PATH" in restricted
    assert "ANTHROPIC_API_KEY" not in restricted
    inherited = resolve_env("inherit")
    assert inherited.get("ANTHROPIC_API_KEY") == "sk"
    custom = resolve_env({"FOO": "bar"})
    assert custom["FOO"] == "bar"
    assert "PATH" in custom
