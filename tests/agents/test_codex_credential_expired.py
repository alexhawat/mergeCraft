"""An expired Codex reviewer credential is named, not buried in a log (#922).

``CODEX_AUTH_JSON`` holds a ChatGPT-subscription login whose refresh token
rotates on use. Once another consumer refreshes it, the stored copy is dead and
every later run stops with "refresh token was already used". Until now that read
as a generic run failure: a red check nobody requires, with the cause only in
the run log. Three PRs merged in that window with no review.

The fix names the failure where it is first seen (the Codex driver), carries it
as an infrastructure outcome, and puts the reason in the check summary and the
run result without opening the log. There is deliberately **no scheduled
canary**: exercising the credential on a schedule refreshes it and spends the
stored refresh token, which is the failure #970 describes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context
from tests.agents.test_cov_codex_paths import _FakeProcess, _run_once
from tests.support.run_main_harness import FakeAgent, run_main_for_test

from mergecraft.agents.shared import AgentResult
from mergecraft.main_outcome import _classify_outcome
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from pathlib import Path

NAMED_REASON = (
    "reviewer credential expired — re-authenticate "
    "(mergecraft auth codex, then gh secret set CODEX_AUTH_JSON)"
)

_REFRESH_USED = (
    "Your access token could not be refreshed because your refresh token was already used. "
    "Please log out and sign in again."
)


def _error_event(message: str) -> str:
    return json.dumps({"type": "error", "message": message})


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        (_error_event(_REFRESH_USED), "Reading additional input from stdin..."),
        ("", _REFRESH_USED),
        (_error_event("refresh token has already been used"), ""),
        (_error_event("Your access token could not be refreshed"), ""),
    ],
    ids=["stream-event", "stderr", "already-been-used", "could-not-be-refreshed"],
)
def test_driver_names_the_expired_credential(
    stdout: str,
    stderr: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout=stdout, stderr=stderr, returncode=1),
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith(NAMED_REASON)
    assert result.metadata.get("infra_reason") == "reviewer_credential_expired"


def test_driver_keeps_the_providers_own_message_after_the_named_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout=_error_event(_REFRESH_USED), returncode=1),
    )

    assert result.error is not None
    assert _REFRESH_USED in result.error


def test_an_expired_credential_is_not_retried_against_the_same_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-issuing the call cannot help: the stored refresh token is already spent."""
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout=_error_event(_REFRESH_USED), returncode=1),
    )

    assert "retryable" not in result.metadata


@pytest.mark.parametrize(
    ("stdout", "stderr", "retryable"),
    [
        ("", "429 Too Many Requests", True),
        (_error_event("You've hit your usage limit."), "", True),
        ("", "something exploded", False),
    ],
    ids=["rate-limit", "usage-limit", "plain-failure"],
)
def test_other_codex_failures_are_unchanged(
    stdout: str,
    stderr: str,
    retryable: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout=stdout, stderr=stderr, returncode=1),
    )

    assert result.success is False
    assert result.error is not None
    assert NAMED_REASON not in result.error
    assert "infra_reason" not in result.metadata
    assert result.metadata.get("retryable", False) is retryable


def test_a_successful_run_that_mentions_the_phrase_is_not_an_expired_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer quoting this very error in its review is not the driver failing."""
    message = {
        "type": "message.completed",
        "message": {"content": f"The doc says: {_REFRESH_USED}"},
    }
    result, _ = _run_once(
        make_agent_run_context(tmp_path, resolved_model=None),
        monkeypatch,
        _FakeProcess(stdout=json.dumps(message), returncode=0),
    )

    assert result.success is True
    assert "infra_reason" not in result.metadata


def _failed(metadata: dict[str, Any]) -> AgentResult:
    return AgentResult(success=False, error=NAMED_REASON, metadata=metadata)


def test_an_expired_credential_classifies_as_infra_error() -> None:
    outcome, reason = _classify_outcome(
        result=_failed({"infra_reason": "reviewer_credential_expired"}),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
    )

    assert outcome is RunOutcome.infra_error
    assert reason == NAMED_REASON


def test_an_ordinary_agent_failure_still_classifies_as_failed() -> None:
    outcome, _ = _classify_outcome(
        result=_failed({}),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
    )

    assert outcome is RunOutcome.failed


async def test_the_named_reason_reaches_the_check_summary_and_the_run_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = FakeAgent(result=_failed({"infra_reason": "reviewer_credential_expired"}))

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent=agent,
        capture_status_checks=True,
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
    )

    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.result.outcome is RunOutcome.infra_error
    assert rec.result.error is not None
    assert NAMED_REASON in rec.result.error
    completion = [run for run in rec.status_check_runs if run["name"] == "mergecraft"]
    for run in completion:
        assert NAMED_REASON in run["summary"], run
        assert run["conclusion"] == "neutral", run
