"""One credential authority: the fork invariant and the agent-env filter (RA1.1, D2/N21).

``action/inputs._PROVIDER_CREDENTIAL_ENV_KEYS`` and
``utils/secrets.PROVIDER_KEY_ENV_VARS`` are two hand-maintained literals that
disagree with each other and with the provider registry. These tests derive the
registry's credential names from the registry itself, so adding a provider to
one consumer and not the other fails here rather than re-drifting silently.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from mergecraft.config.runtime_provider_registry import (
    _credential_suffixes_for_entry,
    _harness_env_name_for_suffix,
    indexed_env_key,
)
from mergecraft.config.settings import ProviderRegistryEntry
from mergecraft.utils.secrets import (
    PROVIDER_KEY_ENV_VARS,
    build_agent_env,
)
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT
from tests.trust_credentials.support import import_action_symbol

_RA2_XFAIL = pytest.mark.xfail(
    reason="green after RA2: both credential sets derive from the provider registry",
    strict=False,
)

_ENTRIES: tuple[ProviderRegistryEntry, ...] = tuple(
    ProviderRegistryEntry.model_validate(row)
    for row in (
        {"label": "anthropic", "harness": "claude", "envIndex": 1, "authKind": "oauth"},
        {"label": "openai", "harness": "codex", "envIndex": 2, "authKind": "device_code"},
        {"label": "bedrock", "harness": "claude", "envIndex": 3, "authKind": "cloud_chain"},
        {"label": "vertex", "harness": "claude", "envIndex": 4, "authKind": "cloud_chain"},
        {"label": "google", "harness": "gemini", "envIndex": 5, "authKind": "api_key"},
        {"label": "cursor", "harness": "cursor", "envIndex": 6, "authKind": "api_key"},
    )
)


def _indexed_names() -> frozenset[str]:
    names: set[str] = set()
    for entry in _ENTRIES:
        for suffix in _credential_suffixes_for_entry(entry):
            names.add(indexed_env_key(entry.env_index, suffix))
    return frozenset(names)


def _flat_names() -> frozenset[str]:
    names: set[str] = set()
    for entry in _ENTRIES:
        for suffix in _credential_suffixes_for_entry(entry):
            harness_name = _harness_env_name_for_suffix(entry.label, suffix)
            if harness_name is not None:
                names.add(harness_name)
    return frozenset(names)


def _registry_names() -> frozenset[str]:
    return _indexed_names() | _flat_names()


def _invariant_rejects(name: str) -> bool:
    validate = import_action_symbol("validate_fork_credential_invariant")
    from mergecraft.action.inputs import ForkCredentialInvariantError

    try:
        validate(event=FORK_PULL_REQUEST_EVENT, env={name: "planted-credential"})
    except ForkCredentialInvariantError:
        return True
    return False


@_RA2_XFAIL
def test_fork_invariant_covers_every_registry_credential_name() -> None:
    """Every registry credential name — indexed and flat — fires the invariant."""
    missing = sorted(name for name in _registry_names() if not _invariant_rejects(name))
    assert not missing, f"fork invariant misses registry credential names: {missing}"


@_RA2_XFAIL
def test_agent_env_filter_covers_every_registry_credential_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declared strip set names every registry credential, and strips it."""
    flat = _flat_names()
    missing = sorted(flat - PROVIDER_KEY_ENV_VARS)
    assert not missing, f"agent-env strip set is missing registry credentials: {missing}"

    for name in sorted(flat):
        monkeypatch.setenv(name, "planted-credential")
    env = build_agent_env("opencode")
    leaked = sorted(name for name in flat if name in env)
    assert not leaked, f"build_agent_env kept registry credentials: {leaked}"


@_RA2_XFAIL
def test_google_api_key_is_present_in_both_sets() -> None:
    """N21's named drift, pinned: ``GOOGLE_API_KEY`` is a credential in both sets."""
    from mergecraft.action.inputs import _PROVIDER_CREDENTIAL_ENV_KEYS

    assert "GOOGLE_API_KEY" in _PROVIDER_CREDENTIAL_ENV_KEYS
    assert "GOOGLE_API_KEY" in PROVIDER_KEY_ENV_VARS


def _validate_fork(env: Mapping[str, str]) -> None:
    validate = import_action_symbol("validate_fork_credential_invariant")
    validate(event=FORK_PULL_REQUEST_EVENT, env=dict(env))


@_RA2_XFAIL
@pytest.mark.parametrize(
    "env_key",
    [
        "LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN",
        "LLM_PROVIDER_2_CODEX_AUTH_JSON",
        "LLM_PROVIDER_3_AWS_ACCESS_KEY_ID",
        "LLM_PROVIDER_3_AWS_SECRET_ACCESS_KEY",
        "LLM_PROVIDER_4_GOOGLE_APPLICATION_CREDENTIALS",
    ],
)
def test_indexed_registry_credential_is_rejected_on_fork_head(env_key: str) -> None:
    from mergecraft.action.inputs import ForkCredentialInvariantError

    with pytest.raises(ForkCredentialInvariantError):
        _validate_fork({env_key: "planted-credential"})
