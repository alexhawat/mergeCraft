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


def test_opencode_go_flat_env_bridges_to_opencode_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``opencode-go``'s flat workflow secret reaches the harness name the CLI reads.

    ``provider auth opencode-go`` stores ``LLM_PROVIDER_10_API_KEY`` but the
    generated workflow wires the *flat* ``OPENCODE_GO_API_KEY``. The runtime must
    bridge that flat value to ``OPENCODE_API_KEY``, which is what the OpenCode CLI
    reads — otherwise ``build_agent_env`` strips the credential and re-injects
    nothing.
    """
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="opencode-go",
        harness="opencode",
        env_index=10,
        auth_kind="api_key",
    )
    monkeypatch.delenv("LLM_PROVIDER_10_API_KEY", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "flat-opencode-go-key")
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)

    slug = "opencode-go/deepseek-v4.1-flash"
    assert harness_env_for_active_provider(slug, "opencode") == {
        "OPENCODE_API_KEY": "flat-opencode-go-key"
    }

    env = build_agent_env("opencode", model=slug)
    assert env.get("OPENCODE_API_KEY") == "flat-opencode-go-key"
    assert "OPENCODE_GO_API_KEY" not in env


def test_mapping_site_fallback_bridges_flat_name_independently(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """The mapping-site fallback still bridges the flat name if the registry reader misses.

    Guards the hardening in ``harness_env_for_active_provider`` itself: even with
    the registry-side flat lookup neutralized, the flat ``OPENCODE_GO_API_KEY``
    must still reach ``OPENCODE_API_KEY``.
    """
    from mergecraft.config import runtime_provider_registry as registry

    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label="opencode-go",
        harness="opencode",
        env_index=10,
        auth_kind="api_key",
    )
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "flat-opencode-go-key")
    monkeypatch.setattr(registry, "_read_indexed_credential_value", lambda _entry, _suffix: None)

    assert registry.harness_env_for_active_provider(
        "opencode-go/deepseek-v4.1-flash", "opencode"
    ) == {"OPENCODE_API_KEY": "flat-opencode-go-key"}


@pytest.mark.parametrize(
    ("label", "harness", "flat_key"),
    [
        ("anthropic", "claude", "ANTHROPIC_API_KEY"),
        ("google", "gemini", "GEMINI_API_KEY"),
        ("openai", "codex", "OPENAI_API_KEY"),
    ],
)
def test_flat_credential_maps_identically_for_builtin_providers(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    label: str,
    harness: str,
    flat_key: str,
) -> None:
    """Providers whose flat name equals the harness name keep an identity mapping."""
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_registry_provider_row(
        tmp_path,
        label=label,
        harness=harness,
        env_index=1,
        auth_kind="api_key",
    )
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    monkeypatch.setenv(flat_key, "flat-builtin-key")

    slug = f"{label}/demo-model"
    assert harness_env_for_active_provider(slug, harness) == {flat_key: "flat-builtin-key"}
    assert build_agent_env(harness, model=slug).get(flat_key) == "flat-builtin-key"


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


# ---------------------------------------------------------------------------
# PR #498 review — registry credentials outrank legacy env when both are set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "harness", "suffix", "legacy_key", "indexed_value", "legacy_value"),
    [
        ("openai", "codex", "API_KEY", "OPENAI_API_KEY", "sk-openai-indexed", "sk-openai-legacy"),
        ("google", "gemini", "API_KEY", "GEMINI_API_KEY", "gemini-indexed", "gemini-legacy"),
        ("cursor", "cursor", "API_KEY", "CURSOR_API_KEY", "cursor-indexed", "cursor-legacy"),
        ("anthropic", "claude", "API_KEY", "ANTHROPIC_API_KEY", "sk-ant-indexed", "sk-ant-legacy"),
    ],
)
def test_indexed_api_key_wins_over_legacy_when_both_present(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    label: str,
    harness: str,
    suffix: str,
    legacy_key: str,
    indexed_value: str,
    legacy_value: str,
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
        api_key=indexed_value,
    )
    monkeypatch.setenv(f"LLM_PROVIDER_1_{suffix}", indexed_value)
    monkeypatch.setenv(legacy_key, legacy_value)

    env = build_agent_env(harness, model=f"{label}/demo-model")
    assert env.get(legacy_key) == indexed_value, (
        f"registry credential must outrank legacy {legacy_key}; got {env.get(legacy_key)!r}"
    )


def test_indexed_oauth_wins_over_legacy_when_both_present(
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
    monkeypatch.setenv("LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oauth-indexed")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oauth-legacy")

    env = build_agent_env("claude", model="anthropic/claude-sonnet")
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oauth-indexed"


def test_indexed_cloud_chain_wins_over_legacy_when_both_present(
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
    monkeypatch.setenv("LLM_PROVIDER_1_AWS_ACCESS_KEY_ID", "AKIA-indexed")
    monkeypatch.setenv("LLM_PROVIDER_1_AWS_SECRET_ACCESS_KEY", "secret-indexed")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-legacy")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-legacy")
    # Without this flag the legacy re-injection loop never runs at all.
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")

    env = build_agent_env("claude", model="bedrock/us.anthropic.claude-sonnet")
    assert env.get("AWS_ACCESS_KEY_ID") == "AKIA-indexed"
    assert env.get("AWS_SECRET_ACCESS_KEY") == "secret-indexed"
