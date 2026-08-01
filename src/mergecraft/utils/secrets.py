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
