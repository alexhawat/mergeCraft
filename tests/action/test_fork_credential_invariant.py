"""W1.1 / D2b — action-side fork + credential invariant (wave 15, green after W2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT
from tests.trust_credentials.support import import_action_symbol

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


_PROVIDER_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    "CODEX_AUTH_JSON",
)


@pytest.mark.parametrize("env_key", _PROVIDER_ENV_KEYS)
def test_fork_head_with_provider_credential_refuses_run(
    monkeypatch: MonkeyPatch, env_key: str
) -> None:
    """D2b — fork head + any provider credential in env refuses before review starts."""
    validate = import_action_symbol("validate_fork_credential_invariant")
    monkeypatch.setenv(env_key, "test-credential-value")
    with pytest.raises(Exception, match=r"fork|credential|refus|skip"):
        validate(event=FORK_PULL_REQUEST_EVENT, env=dict(__import__("os").environ))


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


# ── S4 (TB1): comment-on-PR events and the unbound message ───────────────────


def _comment_on_pr_event(*, number: int = 7) -> dict[str, object]:
    return {
        "action": "created",
        "issue": {
            "number": number,
            "pull_request": {"url": f"https://api.github.com/repos/acme/demo/pulls/{number}"},
        },
        "comment": {"author_association": "OWNER", "body": "@mergecraft review"},
    }


def test_comment_on_pr_with_credentials_is_refused() -> None:
    """S4 — a maintainer comment on a PR is a fork floor until bound.

    A credentialed run must refuse before the credential is used; the message
    names the PR that could not be bound.
    """
    validate = import_action_symbol("validate_fork_credential_invariant")
    with pytest.raises(Exception, match=r"unbound|could not be bound") as excinfo:
        validate(
            event=_comment_on_pr_event(),
            env={"ANTHROPIC_API_KEY": "sk-test"},
        )
    message = str(excinfo.value).lower()
    assert "unbound" in message or "could not be bound" in message, str(excinfo.value)


def test_comment_on_pr_without_credentials_is_allowed() -> None:
    """Guard — the floor refuses only a credentialed run."""
    validate = import_action_symbol("validate_fork_credential_invariant")
    validate(event=_comment_on_pr_event(), env={})


def test_bound_fork_refusal_message_names_the_fork() -> None:
    """Guard — a bound fork keeps the fork-specific message."""
    validate = import_action_symbol("validate_fork_credential_invariant")
    with pytest.raises(Exception, match=r"fork"):
        validate(event=FORK_PULL_REQUEST_EVENT, env={"ANTHROPIC_API_KEY": "sk-test"})
