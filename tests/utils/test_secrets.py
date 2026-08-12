"""Tests for secret sanitization and allowlist filtering."""

from __future__ import annotations

import pytest

from mergecraft.utils.secrets import (
    ACTIVE_PROVIDER_KEY_BY_AGENT,
    ALWAYS_STRIP_FROM_AGENT_ENV,
    build_agent_env,
    clear_env_allowlist,
    filter_env,
    is_sensitive_env_name,
    resolve_env,
    sanitize_secret,
    set_env_allowlist,
)


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


def test_always_strip_from_agent_env_names() -> None:
    """Direct ``ALWAYS_STRIP_FROM_AGENT_ENV`` — D2 credential names must be listed.

    Fails if the frozenset is emptied: agent env can re-admit ambient tokens.
    """
    required = {
        "GIT_ASKPASS",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    }
    assert required <= set(ALWAYS_STRIP_FROM_AGENT_ENV)


def test_active_provider_key_by_agent_mapping() -> None:
    """Direct ``ACTIVE_PROVIDER_KEY_BY_AGENT`` — only the active provider key is named."""
    assert ACTIVE_PROVIDER_KEY_BY_AGENT["claude"] == "ANTHROPIC_API_KEY"
    assert ACTIVE_PROVIDER_KEY_BY_AGENT["codex"] == "OPENAI_API_KEY"
    assert ACTIVE_PROVIDER_KEY_BY_AGENT["gemini"] == "GEMINI_API_KEY"
    assert ACTIVE_PROVIDER_KEY_BY_AGENT["opencode"] is None


@pytest.mark.parametrize(
    ("agent_id", "active_key"),
    [
        ("claude", "ANTHROPIC_API_KEY"),
        ("codex", "OPENAI_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
    ],
)
def test_build_agent_env_strips_credentials_keeps_active_key(
    agent_id: str, active_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct ``build_agent_env`` — allowlist strips secrets; re-injects active key only.

    Fails if ``build_agent_env`` is deleted or falls back to ``dict(os.environ)``.
    """
    clear_env_allowlist()
    planted = {
        "PATH": "/usr/bin",
        "HOME": "/home/runner",
        "GIT_ASKPASS": "/run/secrets/git-askpass.sh",
        "GITHUB_TOKEN": "gho_planted",
        "GH_TOKEN": "gho_gh",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example/abc",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-token",
        "ANTHROPIC_API_KEY": "sk-ant-planted",
        "OPENAI_API_KEY": "sk-openai-planted",
        "GEMINI_API_KEY": "gemini-planted",
        "CURSOR_API_KEY": "cursor-planted",
    }
    for key, value in planted.items():
        monkeypatch.setenv(key, value)

    env = build_agent_env(agent_id)

    for name in ALWAYS_STRIP_FROM_AGENT_ENV:
        assert name not in env, f"build_agent_env leaked {name}"
    assert env.get(active_key) == planted[active_key]
    for other in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "CURSOR_API_KEY"):
        if other == active_key:
            continue
        assert other not in env, f"build_agent_env leaked non-active key {other}"


def test_build_agent_env_opencode_keeps_no_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """opencode has no active provider key — none of the planted keys may remain."""
    clear_env_allowlist()
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("GITHUB_TOKEN", "gho_token")

    env = build_agent_env("opencode")

    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "PATH" in env
