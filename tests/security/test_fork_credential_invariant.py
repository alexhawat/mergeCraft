"""Fork-head credential invariant: every auth kind, both spellings (RA1.1, N1/N21).

The invariant is a **presence** check before dispatch (D3). The baseline only
recognises the flat spellings plus the ``LLM_PROVIDER_*_API_KEY`` suffix rule,
so indexed OAuth, device-code and cloud-chain credentials sail past a fork
event. Each case here drives the real ``validate_fork_credential_invariant``
entry point with a genuine fork payload.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from mergecraft.utils.secrets import filter_env
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT, SAME_REPO_PULL_REQUEST_EVENT
from tests.trust_credentials.support import import_action_symbol

_FORK = FORK_PULL_REQUEST_EVENT
_SAME_REPO = SAME_REPO_PULL_REQUEST_EVENT


def _validate(env: Mapping[str, str]) -> None:
    validate = import_action_symbol("validate_fork_credential_invariant")
    validate(event=_FORK, env=dict(env))


def _assert_rejected(env: Mapping[str, str]) -> None:
    from mergecraft.action.inputs import ForkCredentialInvariantError

    with pytest.raises(ForkCredentialInvariantError):
        _validate(env)


def test_indexed_oauth_credential_is_rejected_on_fork_head() -> None:
    _assert_rejected({"LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-indexed-oauth"})


def test_indexed_device_code_credential_is_rejected_on_fork_head() -> None:
    _assert_rejected({"LLM_PROVIDER_1_CODEX_AUTH_JSON": '{"tokens": {"access_token": "x"}}'})


@pytest.mark.parametrize(
    ("env_key", "value"),
    [
        ("LLM_PROVIDER_1_AWS_ACCESS_KEY_ID", "AKIA-INDEXED"),
        ("LLM_PROVIDER_1_AWS_SECRET_ACCESS_KEY", "indexed-secret"),
        ("LLM_PROVIDER_1_GOOGLE_APPLICATION_CREDENTIALS", "/run/vertex/indexed.json"),
    ],
)
def test_indexed_cloud_chain_credentials_are_rejected_on_fork_head(
    env_key: str, value: str
) -> None:
    _assert_rejected({env_key: value})


@pytest.mark.parametrize(
    "env_key",
    [
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CODEX_AUTH_JSON",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "NOUS_API_KEY",
        "CURSOR_API_KEY",
    ],
)
def test_flat_legacy_spellings_stay_rejected(env_key: str) -> None:
    """Guard — the flat spellings already fire on trunk and must not regress."""
    _assert_rejected({env_key: "planted-credential"})


def test_same_repo_event_with_every_auth_kind_is_permitted() -> None:
    """The fail-closed rule must not become fail-always."""
    validate = import_action_symbol("validate_fork_credential_invariant")
    env = {
        "ANTHROPIC_API_KEY": "sk-ant",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oauth",
        "OPENAI_API_KEY": "sk-openai",
        "CODEX_AUTH_JSON": '{"tokens": {"access_token": "x"}}',
        "GEMINI_API_KEY": "gemini",
        "CURSOR_API_KEY": "cursor",
        "AWS_ACCESS_KEY_ID": "AKIA",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "GOOGLE_APPLICATION_CREDENTIALS": "/run/vertex/sa.json",
        "LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-indexed-oauth",
        "LLM_PROVIDER_2_CODEX_AUTH_JSON": '{"tokens": {"access_token": "x"}}',
        "LLM_PROVIDER_3_AWS_ACCESS_KEY_ID": "AKIA-INDEXED",
    }

    validate(event=_SAME_REPO, env=env)


def test_untrusted_tier_filtering_does_not_reintroduce_the_credential() -> None:
    """The audit's reproduction path: agent-env filtering must not be the guard.

    ``filter_env`` drops the indexed credential from the *child* environment,
    but the invariant runs before dispatch on the process environment. If the
    filter were the protection, the credential would be invisible to the
    invariant and the fork run would start.
    """
    raw = {"PATH": "/usr/bin", "LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-indexed"}
    filtered = filter_env(raw)
    assert "LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN" not in filtered

    validate = import_action_symbol("validate_fork_credential_invariant")
    from mergecraft.action.inputs import ForkCredentialInvariantError

    with pytest.raises(ForkCredentialInvariantError):
        validate(event=_FORK, env=raw, agent_sandbox_tier="never")
