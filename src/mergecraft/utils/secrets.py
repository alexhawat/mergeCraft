"""Secret detection, sanitization, and subprocess env allowlist filtering."""

from __future__ import annotations

import os
import re

from loguru import logger

# Patterns for sensitive env var names (used by normalize_env / redaction).
SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"_KEY$", re.IGNORECASE),
    re.compile(r"_SECRET$", re.IGNORECASE),
    re.compile(r"_TOKEN$", re.IGNORECASE),
    re.compile(r"_PASSWORD$", re.IGNORECASE),
    re.compile(r"_CREDENTIAL$", re.IGNORECASE),
)

# Prefixes whose vars are safe to pass through (runner metadata, workflow context).
# GITHUB_TOKEN/GH_TOKEN match GITHUB_ but are still filtered via is_sensitive_env_name.
SAFE_ENV_PREFIXES: tuple[str, ...] = ("GITHUB_", "RUNNER_", "JAVA_HOME_", "GOROOT_")

SAFE_ENV_NAMES: frozenset[str] = frozenset(
    {
        "CI",
        "HOME",
        "LANG",
        "LOGNAME",
        "PATH",
        "SHELL",
        "SHLVL",
        "TERM",
        "TMPDIR",
        "TZ",
        "USER",
        "XDG_CONFIG_HOME",
        "XDG_RUNTIME_DIR",
        "DEBIAN_FRONTEND",
        "ACCEPT_EULA",
        "AGENT_TOOLSDIRECTORY",
        "ANDROID_HOME",
        "ANDROID_NDK",
        "ANDROID_NDK_HOME",
        "ANDROID_NDK_LATEST_HOME",
        "ANDROID_NDK_ROOT",
        "ANDROID_SDK_ROOT",
        "ANT_HOME",
        "AZURE_EXTENSION_DIR",
        "BOOTSTRAP_HASKELL_NONINTERACTIVE",
        "CHROME_BIN",
        "CHROMEWEBDRIVER",
        "CONDA",
        "DOTNET_MULTILEVEL_LOOKUP",
        "DOTNET_NOLOGO",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE",
        "EDGEWEBDRIVER",
        "GECKOWEBDRIVER",
        "GHCUP_INSTALL_BASE_PREFIX",
        "GRADLE_HOME",
        "JAVA_HOME",
        "HOMEBREW_CLEANUP_PERIODIC_FULL_DAYS",
        "HOMEBREW_NO_AUTO_UPDATE",
        "ImageOS",
        "ImageVersion",
        "NVM_DIR",
        "PIPX_BIN_DIR",
        "PIPX_HOME",
        "PSModulePath",
        "SELENIUM_JAR_PATH",
        "SGX_AESM_ADDR",
        "SWIFT_PATH",
        "VCPKG_INSTALLATION_ROOT",
    }
)

_user_allowlist: set[str] | None = None


def is_sensitive_env_name(key: str) -> bool:
    """Return whether ``key`` looks like a secret-bearing environment variable."""
    return any(pattern.search(key) for pattern in SENSITIVE_PATTERNS)


def sanitize_secret(key: str, value: str) -> str | None:
    """Trim surrounding whitespace from a secret value.

    Returns the trimmed value, or ``None`` when the input was whitespace-only —
    callers must leave ``os.environ`` untouched in that case.
    """
    trimmed = value.strip()
    if len(trimmed) == 0:
        logger.warning(
            "» {} is whitespace-only — leaving env var unchanged. check your secret value.",
            key,
        )
        return None
    if trimmed != value:
        logger.warning(
            "» stripped whitespace from {} "
            "(whitespace in secret values breaks GitHub Actions log masking)",
            key,
        )
    return trimmed


def set_env_allowlist(raw: str) -> None:
    """Set the user allowlist from a newline-separated string (repo ``envAllowlist``)."""
    global _user_allowlist
    names = {line.strip() for line in raw.splitlines() if line.strip()}
    _user_allowlist = names


def clear_env_allowlist() -> None:
    """Reset the user allowlist (primarily for tests)."""
    global _user_allowlist
    _user_allowlist = None


def is_safe_env_var(key: str) -> bool:
    """Return whether ``key`` is in the default-safe set/prefixes."""
    if key in SAFE_ENV_NAMES:
        return True
    return any(key.startswith(prefix) for prefix in SAFE_ENV_PREFIXES)


def filter_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Filter env vars using default-deny allowlist: safe set + user allowlist."""
    source: dict[str, str] = dict(os.environ) if environ is None else environ
    filtered: dict[str, str] = {}
    for key, value in source.items():
        user_allowed = bool(_user_allowlist and key in _user_allowlist)
        if is_sensitive_env_name(key) and not user_allowed:
            continue
        if is_safe_env_var(key) or user_allowed:
            filtered[key] = value
    return filtered


EnvMode = str | dict[str, str]  # "restricted" | "inherit" | custom mapping


# Names that must never appear in an agent subprocess environment (D2 / W2.1).
ALWAYS_STRIP_FROM_AGENT_ENV: frozenset[str] = frozenset(
    {
        "GIT_ASKPASS",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    }
)

# Provider credential env vars — only the active agent's key is re-injected.
PROVIDER_KEY_ENV_VARS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "CURSOR_API_KEY",
        "NOUS_API_KEY",
        "TOKENHUB_API_KEY",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CODEX_AUTH_JSON",
    }
)

ACTIVE_PROVIDER_KEY_BY_AGENT: dict[str, str | None] = {
    "claude": "ANTHROPIC_API_KEY",
    "codex": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "opencode": None,
}

# Cloud BYOK env vars for Claude Code Bedrock / Vertex routing. Re-injected only
# when the corresponding CLAUDE_CODE_USE_* flag (or model slug) selects that path.
_BEDROCK_AGENT_ENV_VARS: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "BEDROCK_MODEL_ID",
)
_VERTEX_AGENT_ENV_VARS: tuple[str, ...] = (
    "GOOGLE_APPLICATION_CREDENTIALS",
    "VERTEX_SERVICE_ACCOUNT_JSON",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUD_ML_PROJECT_ID",
    "VERTEX_LOCATION",
    "VERTEX_MODEL_ID",
)


CLOUD_BYOK_ENV_VARS_BY_LABEL: dict[str, tuple[str, ...]] = {
    "bedrock": _BEDROCK_AGENT_ENV_VARS,
    "vertex": _VERTEX_AGENT_ENV_VARS,
}
"""Cloud BYOK credentials keyed by provider label.

The same tuples ``build_agent_env`` strips, published so a consumer that must
clear a provider's credentials cannot miss the cloud half. ``models.PROVIDERS``
carries a *different* subset for these two providers — it lists
``AWS_BEARER_TOKEN_BEDROCK`` but not ``AWS_ACCESS_KEY_ID``, and
``VERTEX_SERVICE_ACCOUNT_JSON`` but not ``GOOGLE_APPLICATION_CREDENTIALS`` — so
either registry alone leaves a live credential behind. Consolidating the two is
worth doing; until then, a consumer clearing credentials must union them.
"""


def build_agent_env(
    agent_id: str,
    extras: dict[str, str] | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Build an explicit allowlist env for agent CLI subprocesses (D2 / W2.1).

    Starts from :func:`filter_env` (default-deny), strips credential-shaped
    names, then re-injects only the active provider key for ``agent_id``.
    When *model* is set, indexed registry credentials for that slug are mapped
    into the legacy harness env names the native CLI consumes.
    """
    env = filter_env()
    for key in ALWAYS_STRIP_FROM_AGENT_ENV:
        env.pop(key, None)
    for key in PROVIDER_KEY_ENV_VARS:
        env.pop(key, None)
    for key in (*_BEDROCK_AGENT_ENV_VARS, *_VERTEX_AGENT_ENV_VARS):
        env.pop(key, None)

    # Keys the indexed registry supplied. Registry credentials outrank the
    # legacy env vars, so the reinjection below must not overwrite them when
    # both are present.
    registry_mapped: set[str] = set()
    if model:
        from mergecraft.config.runtime_provider_registry import harness_env_for_active_provider

        for key, value in harness_env_for_active_provider(model, agent_id).items():
            if value.strip():
                env[key] = value.strip()
                registry_mapped.add(key)

    active_key = ACTIVE_PROVIDER_KEY_BY_AGENT.get(agent_id)
    if active_key and active_key not in registry_mapped:
        raw = os.environ.get(active_key, "").strip()
        if raw:
            env[active_key] = raw
        if agent_id == "gemini":
            alt = os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", "").strip()
            if alt and not env.get("GEMINI_API_KEY"):
                env["GEMINI_API_KEY"] = alt
    # Claude accepts either an API key or a Claude Code OAuth token (README
    # ``mergecraft auth claude`` path). Both are stripped above; restore OAuth
    # when present so OAuth-only operators are not left with an empty child env.
    if agent_id == "claude" and "CLAUDE_CODE_OAUTH_TOKEN" not in registry_mapped:
        oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
        if oauth:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth
    # Bedrock / Vertex BYOK for Claude *or* OpenCode: reinject when the USE
    # flags are set (callers set them from model id / BEDROCK_MODEL_ID match).
    use_bedrock = bool(
        (extras or {}).get("CLAUDE_CODE_USE_BEDROCK")
        or os.environ.get("CLAUDE_CODE_USE_BEDROCK", "").strip()
    )
    use_vertex = bool(
        (extras or {}).get("CLAUDE_CODE_USE_VERTEX")
        or os.environ.get("CLAUDE_CODE_USE_VERTEX", "").strip()
    )
    if use_bedrock:
        for key in _BEDROCK_AGENT_ENV_VARS:
            if key in registry_mapped:
                continue
            raw = os.environ.get(key, "").strip()
            if raw:
                env[key] = raw
    if use_vertex:
        for key in _VERTEX_AGENT_ENV_VARS:
            if key in registry_mapped:
                continue
            raw = os.environ.get(key, "").strip()
            if raw:
                env[key] = raw
    if extras:
        env.update(extras)
    from mergecraft.enterprise.runtime import agent_network_env

    env.update(agent_network_env())
    return env


def resolve_env(mode: EnvMode | None = None) -> dict[str, str]:
    """Resolve env mode to an actual env mapping.

    - ``\"restricted\"`` / ``None``: ``filter_env()``
    - ``\"inherit\"``: full ``os.environ``
    - mapping: custom env merged onto the restricted base
    """
    if mode == "inherit":
        return dict(os.environ)
    if mode == "restricted" or mode is None:
        return filter_env()
    if isinstance(mode, dict):
        return {**filter_env(), **mode}
    msg = f"invalid env mode: {mode!r}"
    raise ValueError(msg)
