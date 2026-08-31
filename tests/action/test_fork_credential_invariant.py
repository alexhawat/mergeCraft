"""W1.1 / D2b — action-side fork + credential invariant (wave 15, green after W2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT
from tests.trust_credentials.support import W2_XFAIL, import_action_symbol

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


_PROVIDER_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    "CODEX_AUTH_JSON",
)


@W2_XFAIL
@pytest.mark.parametrize("env_key", _PROVIDER_ENV_KEYS)
def test_fork_head_with_provider_credential_refuses_run(
    monkeypatch: MonkeyPatch, env_key: str
) -> None:
    """D2b — fork head + any provider credential in env refuses before review starts."""
    validate = import_action_symbol("validate_fork_credential_invariant")
    monkeypatch.setenv(env_key, "test-credential-value")
    with pytest.raises(Exception, match=r"fork|credential|refus|skip"):
        validate(event=FORK_PULL_REQUEST_EVENT, env=dict(__import__("os").environ))


@W2_XFAIL
def test_fork_invariant_is_independent_of_agent_sandbox_tier(monkeypatch: MonkeyPatch) -> None:
    """The fork floor applies regardless of trust.agentSandbox configuration."""
    validate = import_action_symbol("validate_fork_credential_invariant")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(Exception, match=r"fork|credential|refus|skip"):
        validate(
            event=FORK_PULL_REQUEST_EVENT,
            env={"ANTHROPIC_API_KEY": "sk-test"},
            agent_sandbox_tier="same-repo",
        )
