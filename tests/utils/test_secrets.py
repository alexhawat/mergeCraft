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


@pytest.mark.parametrize("agent_id", ["claude", "codex", "gemini", "opencode"])
def test_build_agent_env_propagates_bound_proxy_and_ca(
    agent_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider children receive enterprise proxy/CA that filter_env would drop."""
    clear_env_allowlist()
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/enterprise-ca.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/enterprise-ca.pem")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    env = build_agent_env(agent_id)
    assert env["HTTPS_PROXY"] == "http://proxy.example:8080"
    assert env["HTTP_PROXY"] == "http://proxy.example:8080"
    assert env["NO_PROXY"] == "localhost"
    assert env["SSL_CERT_FILE"] == "/tmp/enterprise-ca.pem"
    assert env["REQUESTS_CA_BUNDLE"] == "/tmp/enterprise-ca.pem"


# ── GitHub / runner passthrough is an explicit name list ─────────────────────

#: Credential-shaped names that only share a *prefix* with documented runner
#: variables; they must not ride the passthrough.
_PREFIX_LOOKALIKE_CREDENTIALS = ("GITHUB_PAT", "GITHUB_APP_PEM", "RUNNER_BLOB")

#: Documented runner/workflow variables and versioned toolchain homes that must
#: still reach child processes.
_DOCUMENTED_PASSTHROUGH = (
    "GITHUB_WORKSPACE",
    "GITHUB_REPOSITORY",
    "GITHUB_EVENT_PATH",
    "RUNNER_TEMP",
    "JAVA_HOME_17_X64",
)

#: Writable GitHub Actions command-file channels. They are parent-only plumbing:
#: a child that inherits one can append ``KEY=VALUE`` lines to alter later steps'
#: environment or ``PATH``, or overwrite this action's outputs/summary. They are
#: not metadata a child process needs.
_ACTIONS_COMMAND_FILES = (
    "GITHUB_ENV",
    "GITHUB_PATH",
    "GITHUB_OUTPUT",
    "GITHUB_STEP_SUMMARY",
)


@pytest.mark.parametrize("name", _PREFIX_LOOKALIKE_CREDENTIALS)
def test_prefix_lookalike_credentials_are_not_passed_through(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A name that merely starts with ``GITHUB_``/``RUNNER_`` is not safe."""
    clear_env_allowlist()
    monkeypatch.setenv(name, "planted-secret")
    assert name not in filter_env({name: "planted-secret", "PATH": "/bin"})
    assert name not in resolve_env("restricted")
    assert name not in build_agent_env("claude")


@pytest.mark.parametrize("name", _DOCUMENTED_PASSTHROUGH)
def test_documented_runner_names_stay_passed_through(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Documented runner variables and versioned toolchain homes are kept."""
    clear_env_allowlist()
    monkeypatch.setenv(name, "kept-value")
    assert filter_env({name: "kept-value", "PATH": "/bin"})[name] == "kept-value"
    assert resolve_env("restricted")[name] == "kept-value"
    assert build_agent_env("claude")[name] == "kept-value"


def test_actions_command_file_channels_are_not_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Writable Actions command-file paths are not child-env metadata."""
    clear_env_allowlist()
    for command_file in _ACTIONS_COMMAND_FILES:
        monkeypatch.setenv(command_file, f"/runner/_temp/{command_file.lower()}")

    surfaces = (
        ("filter_env", filter_env()),
        ("resolve_env", resolve_env("restricted")),
        ("build_agent_env", build_agent_env("claude")),
    )
    for surface, env in surfaces:
        for command_file in _ACTIONS_COMMAND_FILES:
            assert command_file not in env, f"{command_file} leaked through {surface}"

    # Contrast: documented child metadata still passes.
    monkeypatch.setenv("GITHUB_WORKSPACE", "/runner/workspace")
    assert filter_env()["GITHUB_WORKSPACE"] == "/runner/workspace"
    assert resolve_env("restricted")["GITHUB_WORKSPACE"] == "/runner/workspace"
    assert build_agent_env("claude")["GITHUB_WORKSPACE"] == "/runner/workspace"


def test_env_allowlist_readmits_a_prefix_lookalike_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``set_env_allowlist`` stays the operator escape hatch for one name."""
    clear_env_allowlist()
    try:
        set_env_allowlist("GITHUB_PAT")
        monkeypatch.setenv("GITHUB_PAT", "planted-secret")
        assert filter_env({"GITHUB_PAT": "planted-secret"})["GITHUB_PAT"] == "planted-secret"
        assert resolve_env("restricted")["GITHUB_PAT"] == "planted-secret"
    finally:
        clear_env_allowlist()


def test_active_provider_key_reinjection_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active agent's provider key is still re-injected after the strip."""
    clear_env_allowlist()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-planted")
    env = build_agent_env("claude")
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-planted"


def test_bedrock_and_vertex_reinjection_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud BYOK vars are re-injected only when their USE flag selects them."""
    clear_env_allowlist()
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-planted")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-planted")
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "planted-project")

    env = build_agent_env("claude")

    assert env["AWS_ACCESS_KEY_ID"] == "AKIA-planted"
    assert env["AWS_SECRET_ACCESS_KEY"] == "aws-secret-planted"
    assert env["VERTEX_SERVICE_ACCOUNT_JSON"] == '{"type":"service_account"}'
    assert env["GOOGLE_CLOUD_PROJECT"] == "planted-project"
