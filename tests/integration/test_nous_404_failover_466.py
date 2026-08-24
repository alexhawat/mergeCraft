"""#466 — Nous 404 fail-over through ``run_with_model_chain`` (D5).

Billing/generic 404 advances the chain. Unknown-model 404 (``does not exist``)
does not. Do not expand this file into post-run retry re-calling the provider.
"""

from __future__ import annotations

import json

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.utils.agent_resolve import run_with_model_chain

_NOUS_BILLING_404 = json.dumps(
    {
        "name": "APIError",
        "data": {
            "message": (
                "Not Found: Model 'deepseek/deepseek-v4-flash' requires available credits. "
                "Your account balance is too low to use paid models — add credits at "
                "https://portal.nousresearch.com or pick a free model."
            ),
            "statusCode": 404,
            "isRetryable": False,
        },
    }
)

_UNKNOWN_MODEL_404 = json.dumps(
    {
        "name": "APIError",
        "data": {
            "message": "Not Found: Model 'totally/not-a-real' does not exist in our configuration",
            "statusCode": 404,
            "isRetryable": False,
        },
    }
)

_GENERIC_404 = json.dumps(
    {
        "name": "APIError",
        "data": {"message": "Not Found", "statusCode": 404, "isRetryable": False},
    }
)

_HEAD = "nous/deepseek/deepseek-v4-flash"
_TAIL = "openai/gpt-5.3-codex"


def _settings() -> RepoSettings:
    return RepoSettings.model_validate({"models": [_HEAD, _TAIL]})


@pytest.mark.asyncio
async def test_nous_billing_404_advances_the_model_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug.startswith("nous/"):
            return AgentResult(success=False, error=_NOUS_BILLING_404)
        return AgentResult(success=True, output="ok")

    slug, result = await run_with_model_chain(settings=_settings(), run_once=run_once)
    assert attempts == [_HEAD, _TAIL]
    assert slug == _TAIL
    assert result.success is True


@pytest.mark.asyncio
async def test_generic_404_that_is_not_unknown_model_advances_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug.startswith("nous/"):
            return AgentResult(success=False, error=_GENERIC_404)
        return AgentResult(success=True, output="ok")

    slug, result = await run_with_model_chain(settings=_settings(), run_once=run_once)
    assert attempts == [_HEAD, _TAIL]
    assert slug == _TAIL
    assert result.success is True


@pytest.mark.asyncio
async def test_unknown_model_404_does_not_fail_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(success=False, error=_UNKNOWN_MODEL_404)

    _slug, result = await run_with_model_chain(settings=_settings(), run_once=run_once)
    assert attempts == [_HEAD], f"unknown-model 404 must not fail over, got {attempts}"
    assert result.success is False
    assert result.error is not None
    assert "does not exist" in result.error.lower()
    assert "schema_failure" not in result.error
    assert "set_output" not in result.error
