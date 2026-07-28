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


def test_sanitize_secret_return_contract() -> None:
    assert sanitize_secret("K", "  a  ") == "a"
    assert sanitize_secret("K", "\n\t") is None
