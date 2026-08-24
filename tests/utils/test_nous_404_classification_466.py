"""#466 — Nous HTTP 404 must be classified, not needle-matched and not schema-masked.

Locked D5 (open-issues-sweep-2026-08-24-a):

- HTTP 404 + billing/credit/balance prose is a *different class* from unknown-model
  404 (``does not exist``). Do not grow ``_RETRYABLE_CLI_NEEDLES`` as the only fix.
- A 404 that is not ``does not exist`` is retryable / fail-over for the model chain.
- Unknown-model 404 does not fail over the same way.
- When the agent never ran, the surfaced error is the provider's — never
  ``schema_failure`` / ``set_output``.

These assertions fail until the AD implementation wave. Do not xfail. Do not
edit ``src/mergecraft/``. Do not require post-run retry to re-call the provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.main import RunContext, _promote_and_finalize_agent_result
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.agent_resolve import _is_retryable_failure
from mergecraft.utils.github import GitHubClient

# Verbatim Nous Portal shape from #466 (billing prose was factually false).
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
            "metadata": {
                "url": "https://inference-api.nousresearch.com/v1/chat/completions",
            },
        },
    }
)

_UNKNOWN_MODEL_404 = json.dumps(
    {
        "name": "APIError",
        "data": {
            "message": (
                "Not Found: Model 'totally/not-a-real' does not exist in our configuration"
            ),
            "statusCode": 404,
            "isRetryable": False,
        },
    }
)

# Structured 404 with neither billing needles nor "does not exist" — needle-list
# growth cannot classify this; HTTP 404 that is not unknown-model must fail over.
_GENERIC_404 = json.dumps(
    {
        "name": "APIError",
        "data": {
            "message": "Not Found",
            "statusCode": 404,
            "isRetryable": False,
        },
    }
)

_SCHEMA_MARKERS = ("schema_failure", "set_output")


def _classify(stderr: str, *, status_code: int | None = None) -> object:
    """D5 public classifier — must exist; needle-list-only is not the fix."""
    from mergecraft.utils.provider_failure import classify_provider_failure

    try:
        return classify_provider_failure(stderr=stderr, status_code=status_code)
    except TypeError:
        return classify_provider_failure(stderr)


def _failed(stderr: str) -> AgentResult:
    return AgentResult(success=False, error=stderr)


def _tool_context(tmp_path: Path) -> ToolContext:
    github = GitHubClient(token="")
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


class TestNous404ClassesAreDistinct:
    """HTTP 404 + billing/credit/balance is not the same class as unknown-model."""

    def test_billing_404_and_unknown_model_404_are_classified_separately(self) -> None:
        billing = _classify(_NOUS_BILLING_404, status_code=404)
        unknown = _classify(_UNKNOWN_MODEL_404, status_code=404)
        assert billing != unknown, (
            "D5: billing/credit/balance 404 and unknown-model 404 must be "
            "distinct classes, not one boolean '4xx'"
        )

    def test_generic_404_is_not_classified_as_unknown_model(self) -> None:
        generic = _classify(_GENERIC_404, status_code=404)
        unknown = _classify(_UNKNOWN_MODEL_404, status_code=404)
        assert generic != unknown


class TestNous404Failover:
    """A 404 that is not ``does not exist`` advances the chain; unknown-model does not."""

    def test_nous_billing_404_is_retryable_for_failover(self) -> None:
        """#466 — credits/balance 404 with ``isRetryable: false`` still fails over."""
        assert _is_retryable_failure(_failed(_NOUS_BILLING_404)) is True

    def test_unrelated_asset_404_is_not_retryable_for_model_failover(self) -> None:
        stderr = "GET https://cdn.example/models/weights.bin HTTP/1.1 404 Not Found"
        assert _is_retryable_failure(_failed(stderr)) is False

    def test_banner_prefixed_json_404_is_classified(self) -> None:
        bannered = "Nous CLI v1.2\n" + _GENERIC_404
        generic = _classify(bannered, status_code=404)
        unknown = _classify(_UNKNOWN_MODEL_404, status_code=404)
        assert generic != unknown
        assert _is_retryable_failure(_failed(bannered)) is True

    def test_unknown_model_404_does_not_fail_over(self) -> None:
        assert _is_retryable_failure(_failed(_UNKNOWN_MODEL_404)) is False

    def test_plain_does_not_exist_prose_is_not_retryable(self) -> None:
        stderr = "HTTP 404: model 'foo/bar' does not exist"
        assert _is_retryable_failure(_failed(stderr)) is False

    @pytest.mark.parametrize(
        "stderr",
        [
            "requires available credits. Your account balance is too low",
            "HTTP 404 billing refusal: add credits at the portal",
        ],
        ids=["credits-balance", "404-billing"],
    )
    def test_billing_prose_404_is_retryable_even_as_bare_text(self, stderr: str) -> None:
        assert _is_retryable_failure(_failed(stderr)) is True

    def test_load_balancer_prose_is_not_billing_or_failover(self) -> None:
        stderr = "GET https://cdn.example/v1/upstream HTTP/1.1 404 from the load balancer"
        billing = _classify(_NOUS_BILLING_404, status_code=404)
        assert _classify(stderr, status_code=404) != billing
        assert _is_retryable_failure(_failed(stderr)) is False

    def test_accreditation_credit_substring_is_not_billing(self) -> None:
        stderr = "HTTP 404: accreditation document is missing"
        billing = _classify(_NOUS_BILLING_404, status_code=404)
        assert _classify(stderr, status_code=404) != billing


class TestProviderErrorNotSchemaFailure:
    """Agent never ran → surface the provider error, not a missing ``set_output``."""

    def test_failed_provider_404_is_not_rewritten_as_schema_failure(self, tmp_path: Path) -> None:
        tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
        ctx = RunContext(
            tool_state=tool_state,
            tool_context=_tool_context(tmp_path),
            output_schema={"type": "object"},
            payload={},
        )
        failed = _failed(_NOUS_BILLING_404)
        try:
            out = _promote_and_finalize_agent_result(ctx, None, failed)
        except RuntimeError as exc:
            text = str(exc)
            assert not any(marker in text for marker in _SCHEMA_MARKERS), (
                f"agent never ran; must not surface schema_failure/set_output (got {text!r})"
            )
            assert "credits" in text.lower() or "404" in text or "APIError" in text
            return
        err = out.error or ""
        combined = f"{err} {out.output or ''}"
        assert not any(marker in combined for marker in _SCHEMA_MARKERS), (
            f"final error must be the provider refusal, not schema_failure (got {combined!r})"
        )
        assert "credits" in err.lower() or "APIError" in err or "404" in err

    def test_successful_run_without_set_output_still_requires_schema(self, tmp_path: Path) -> None:
        """Pin: D5 must not delete the schema check for a run that actually executed."""
        tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
        ctx = RunContext(
            tool_state=tool_state,
            tool_context=_tool_context(tmp_path),
            output_schema={"type": "object"},
            payload={},
        )
        ok = AgentResult(success=True, output="review text")
        with pytest.raises(RuntimeError, match="set_output"):
            _promote_and_finalize_agent_result(ctx, None, ok)


def test_provider_failure_class_is_not_owned_by_http_retry_module() -> None:
    """HTTP retry stays 429/5xx; model-chain taxonomy lives in provider_failure."""
    from mergecraft.utils import retry_policy as rp
    from mergecraft.utils.provider_failure import ProviderFailureClass, classify_provider_failure

    assert not hasattr(rp, "ProviderFailureClass")
    assert not hasattr(rp, "classify_provider_failure")
    assert not hasattr(rp, "is_retryable_cli_failure")
    assert not hasattr(rp, "RATE_LIMIT_EXIT_CODES")
    assert classify_provider_failure is not getattr(rp, "ProviderFailureClass", None)
    assert ProviderFailureClass.BILLING.value == "billing"


def test_provider_failure_reuses_try_load_json() -> None:
    from mergecraft.utils.json_load import try_load_json
    from mergecraft.utils.provider_failure import ProviderFailureClass, classify_provider_failure

    parsed = try_load_json('prefix {"error":{"message":"out of credits"}}')
    assert parsed == {"error": {"message": "out of credits"}}
    classified = classify_provider_failure(
        'HTTP 404 {"error":{"message":"Your account balance is too low"}}',
        status_code=404,
    )
    assert classified == ProviderFailureClass.BILLING
