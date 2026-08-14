"""Live integration provider credentials and pytest path selection (W4 / D9)."""

from __future__ import annotations

import os
from typing import Final

# Provider slug → env var holding the live credential.
PROVIDER_SECRET_ENV: Final[dict[str, str]] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "codex": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "nous": "NOUS_API_KEY",
    "github": "GITHUB_TOKEN",
}

# Slugs checked when ``MERGECRAFT_LIVE_PROVIDER`` is unset (default sweep / local).
DEFAULT_CREDENTIAL_SLUGS: Final[tuple[str, ...]] = (
    "anthropic",
    "openai",
    "gemini",
    "nous",
)

# Shared contract tests run on every scheduled matrix leg.
LIVE_CONTRACT_TESTS: Final[tuple[str, ...]] = (
    "tests/integration/test_live_providers.py::test_missing_credential_fails_on_schedule",
    "tests/integration/test_live_providers.py::test_suite_is_inert_on_pull_request",
    "tests/integration/test_live_providers.py::test_response_shape_matches_stream_consumer_contract",
    "tests/integration/test_live_providers.py::test_live_request_is_token_bounded",
)

# Provider slug → provider-specific live test node id(s).
PROVIDER_LIVE_TESTS: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("tests/integration/test_live_providers.py::test_anthropic_minimal_completion",),
    "openai": ("tests/integration/test_live_providers.py::test_openai_codex_minimal_completion",),
    "codex": ("tests/integration/test_live_providers.py::test_openai_codex_minimal_completion",),
    "gemini": ("tests/integration/test_live_providers.py::test_gemini_minimal_completion",),
    "nous": ("tests/integration/test_live_providers.py::test_nous_minimal_completion",),
    "github": (
        "tests/integration/test_github_integration.py::test_checkout_and_status_check_roundtrip",
    ),
}


def missing_live_credentials(provider: str | None = None) -> list[str]:
    """Return env var names that are required but unset for ``provider``."""
    if provider:
        env_key = PROVIDER_SECRET_ENV.get(provider)
        if env_key is None:
            return [f"unknown provider {provider!r}"]
        return [] if os.environ.get(env_key) else [env_key]
    missing: list[str] = []
    for slug in DEFAULT_CREDENTIAL_SLUGS:
        env_key = PROVIDER_SECRET_ENV[slug]
        if not os.environ.get(env_key):
            missing.append(env_key)
    return missing


def live_pytest_paths(provider: str | None = None) -> list[str]:
    """Resolve pytest node ids for a matrix leg or full local run."""
    if not provider:
        return ["tests/integration"]
    extra = PROVIDER_LIVE_TESTS.get(provider, ())
    return [*LIVE_CONTRACT_TESTS, *extra]
