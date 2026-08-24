"""Registry indexed credentials mapped into native harness env names."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mergecraft.config.runtime_provider_registry import harness_env_for_active_provider
from mergecraft.utils.secrets import build_agent_env
from tests.cli.support_provider_registry import (
    scaffold_mergecraft_home,
    write_indexed_provider_secret,
    write_registry_provider_row,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


@pytest.mark.parametrize(
    ("label", "harness", "suffix", "legacy_key", "secret_value"),
    [
        ("openai", "codex", "API_KEY", "OPENAI_API_KEY", "sk-openai-indexed"),
        ("google", "gemini", "API_KEY", "GEMINI_API_KEY", "gemini-indexed"),
        ("cursor", "cursor", "API_KEY", "CURSOR_API_KEY", "cursor-indexed"),
        ("anthropic", "claude", "API_KEY", "ANTHROPIC_API_KEY", "sk-ant-indexed"),
    ],
)
def test_indexed_api_key_maps_to_native_harness_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    label: str,
    harness: str,
    suffix: str,
    legacy_key: str,
    secret_value: str,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label=label,
        harness=harness,
        env_index=1,
        auth_kind="api_key",
    )
    write_indexed_provider_secret(
        tmp_path,
        env_index=1,
        label=label,
        api_key=secret_value,
    )
    monkeypatch.setenv(f"LLM_PROVIDER_{1}_{suffix}", secret_value)
    monkeypatch.delenv(legacy_key, raising=False)

    slug = f"{label}/demo-model"
    mapped = harness_env_for_active_provider(slug, harness)
    assert mapped == {legacy_key: secret_value}

    env = build_agent_env(harness, model=slug)
    assert env.get(legacy_key) == secret_value
    assert f"LLM_PROVIDER_1_{suffix}" not in env


def test_indexed_oauth_maps_to_claude_code_oauth_token(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="anthropic",
        harness="claude",
        env_index=1,
        auth_kind="oauth",
    )
    token = "sk-ant-oauth-at-indexed"
    monkeypatch.setenv("LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN", token)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    slug = "anthropic/claude-sonnet"
    env = build_agent_env("claude", model=slug)
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == token


def test_indexed_device_code_maps_to_codex_auth_json(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="openai",
        harness="codex",
        env_index=1,
        auth_kind="device_code",
    )
    auth_json = json.dumps({"access_token": "device-token"})
    monkeypatch.setenv("LLM_PROVIDER_1_CODEX_AUTH_JSON", auth_json)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    slug = "openai/gpt-5.3-codex"
    env = build_agent_env("codex", model=slug)
    assert env.get("CODEX_AUTH_JSON") == auth_json


def test_cloud_chain_maps_bedrock_suffixes_only(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="bedrock",
        harness="claude",
        env_index=1,
        auth_kind="cloud_chain",
    )
    monkeypatch.setenv("LLM_PROVIDER_1_AWS_ACCESS_KEY_ID", "AKIA...")
    monkeypatch.setenv("LLM_PROVIDER_1_AWS_SECRET_ACCESS_KEY", "secret...")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    slug = "bedrock/us.anthropic.claude-sonnet"
    env = build_agent_env("claude", model=slug)
    assert env.get("AWS_ACCESS_KEY_ID") == "AKIA..."
    assert env.get("AWS_SECRET_ACCESS_KEY") == "secret..."


def test_harness_env_maps_only_active_provider(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(tmp_path, label="openai", harness="codex", env_index=1)
    write_registry_provider_row(
        tmp_path,
        label="google",
        harness="gemini",
        env_index=2,
        url=None,
    )
    monkeypatch.setenv("LLM_PROVIDER_1_API_KEY", "openai-only")
    monkeypatch.setenv("LLM_PROVIDER_2_API_KEY", "google-should-not-leak")

    env = build_agent_env("codex", model="openai/gpt-5.3-codex")
    assert env.get("OPENAI_API_KEY") == "openai-only"
    assert "GEMINI_API_KEY" not in env
