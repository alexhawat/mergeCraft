"""Tests for environment normalization."""

from __future__ import annotations

from mergecraft.utils.normalize_env import normalize_env
from mergecraft.utils.secrets import sanitize_secret


def test_normalize_env_trims_sensitive() -> None:
    env = {"ANTHROPIC_API_KEY": "sk-ant-secret-value\n", "NODE_ENV": "production\n"}
    normalize_env(env)
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-secret-value"
    assert env["NODE_ENV"] == "production\n"


def test_normalize_env_canonicalises_case() -> None:
    env = {"anthropic_api_key": "sk-ant-lowercase\n"}
    normalize_env(env)
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-lowercase"
    assert "anthropic_api_key" not in env


def test_normalize_env_preserves_whitespace_only() -> None:
    env = {"ANTHROPIC_API_KEY": "   \n  "}
    normalize_env(env)
    assert env["ANTHROPIC_API_KEY"] == "   \n  "


def test_normalize_env_conflict_keeps_uppercase() -> None:
    env = {"FOO": "upper", "foo": "lower"}
    normalize_env(env)
    assert env["FOO"] == "upper"
    assert "foo" not in env


def test_normalize_env_keeps_lowercase_proxy_variables() -> None:
    env = {"http_proxy": "http://p:3128", "no_proxy": "localhost,.corp"}
    normalize_env(env)
    assert env["http_proxy"] == "http://p:3128"
    assert env["no_proxy"] == "localhost,.corp"
    assert env["HTTP_PROXY"] == "http://p:3128"
    assert env["NO_PROXY"] == "localhost,.corp"


def test_normalize_env_lowercase_proxy_does_not_override_uppercase() -> None:
    env = {"HTTPS_PROXY": "http://upper:1", "https_proxy": "http://lower:2"}
    normalize_env(env)
    assert env["HTTPS_PROXY"] == "http://upper:1"
    assert env["https_proxy"] == "http://lower:2"


def test_sanitize_secret_return_contract() -> None:
    assert sanitize_secret("K", "  a  ") == "a"
    assert sanitize_secret("K", "\n\t") is None
