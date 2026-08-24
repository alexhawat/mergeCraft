"""Plan W9.3 — bounded, jittered, classification-driven retries (``#34``).

Contracts:

- Retryable-vs-permanent classification is explicit: 429 / 5xx / transport
  errors retry; 4xx and unknown exceptions pass through immediately.
- The wait strategy is bounded exponential backoff **with jitter** — not a
  fixed sleep (``utils/github.py``).
- Mutations (POST/PATCH/DELETE) are never retried blindly: a 5xx from a
  mutation attempt surfaces after one try; reads stay retried.
- ``CursorCloudClient`` gains the same policy (it has none today).
"""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest
import tenacity

from mergecraft.utils.github import GitHubClient, _is_transient_http_error


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.github.com/x")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"status {status}", request=request, response=response)


class TestTransientClassification:
    """W9.3 — the retryable-vs-permanent boundary (already true; pinned plain)."""

    @pytest.mark.parametrize("status", [429, 500, 502, 503], ids=["429", "500", "502", "503"])
    def test_retryable_statuses(self, status: int) -> None:
        assert _is_transient_http_error(_status_error(status)) is True

    def test_transport_error_retries(self) -> None:
        exc = httpx.TransportError("connection reset")
        assert _is_transient_http_error(exc) is True

    @pytest.mark.parametrize(
        "status", [400, 401, 403, 404, 422], ids=["400", "401", "403", "404", "422"]
    )
    def test_permanent_statuses_do_not_retry(self, status: int) -> None:
        assert _is_transient_http_error(_status_error(status)) is False

    def test_unrelated_exception_is_permanent(self) -> None:
        assert _is_transient_http_error(ValueError("boom")) is False


class _FlakyTransport:
    """AsyncClient.request replacement: always fails, counts attempts."""

    def __init__(self, status: int = 500) -> None:
        self.calls = 0
        self.status = status

    async def __call__(self, method: str, url: str, **_kwargs: Any) -> httpx.Response:
        self.calls += 1
        request = httpx.Request(method, url)
        response = httpx.Response(self.status, request=request)
        raise httpx.HTTPStatusError(f"status {self.status}", request=request, response=response)


class TestRetryBehavior:
    # Wall-clock note: today's wait_fixed(0.5) costs ~1s per retried case —
    # acceptable, and no fake clock can see a wait strategy that does not
    # exist yet.

    async def test_reads_retry_to_a_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """W9.3 — a retryable GET is retried, but bounded (never a hot loop)."""
        client = GitHubClient(token="x")
        flaky = _FlakyTransport(500)
        monkeypatch.setattr(client._client, "request", flaky)
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/repos/acme/demo")
        assert 2 <= flaky.calls <= 5, f"GET attempts unbounded or absent: {flaky.calls}"

    async def test_permanent_error_passes_through_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W9.3 — a 422 is not retried (classification, not blanket retry)."""
        client = GitHubClient(token="x")
        flaky = _FlakyTransport(422)
        monkeypatch.setattr(client._client, "request", flaky)
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/repos/acme/demo")
        assert flaky.calls == 1

    async def test_mutation_5xx_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """W9.3 — a POST that fails with 5xx may have landed; retrying is unsafe.

        Fails if the guard is deleted: the blind-retry policy re-issues the
        mutation and the attempt counter climbs past 1.
        """
        client = GitHubClient(token="x")
        flaky = _FlakyTransport(500)
        monkeypatch.setattr(client._client, "request", flaky)
        with pytest.raises(httpx.HTTPStatusError):
            await client.post("/repos/acme/demo/issues", json={"title": "x"})
        assert flaky.calls == 1, f"mutation retried {flaky.calls - 1} extra time(s)"


class TestRetryShape:
    """Structural pins on the retry policy objects (no wall-clock asserts)."""

    def test_github_client_wait_is_exponential_with_jitter(self) -> None:
        retrying = getattr(GitHubClient._send, "retry", None)
        assert retrying is not None, "GitHubClient._send lost its retry decorator"
        wait = retrying.wait
        assert not isinstance(wait, tenacity.wait_fixed), (
            "wait_fixed does not backoff — 429/5xx bursts hammer the API"
        )
        text = repr(type(wait)) + repr(getattr(wait, "__dict__", {}))
        assert "exponential" in type(wait).__name__.lower() or isinstance(
            wait, (tenacity.wait_exponential, tenacity.wait_combine)
        ), f"unexpected wait strategy {text}"
        flattened = repr(wait)
        assert "random" in flattened.lower() or "jitter" in flattened.lower(), (
            f"backoff without jitter synchronizes retry storms: {flattened}"
        )

    def test_github_client_stop_is_bounded(self) -> None:
        retrying = getattr(GitHubClient._send, "retry", None)
        assert retrying is not None, "GitHubClient._send lost its retry decorator"
        assert isinstance(retrying.stop, tenacity.stop_after_attempt)
        assert retrying.stop.max_attempt_number <= 5

    def test_cursor_cloud_client_has_retry_policy(self) -> None:
        from mergecraft.integrations.cursor_cloud import client as cursor_client

        source = inspect.getsource(cursor_client)
        assert "retry" in source, (
            "CursorCloudClient has no retry policy — transient 429/5xx fail the run"
        )


class TestRetryableCliFailure:
    """Direct ``is_retryable_cli_failure`` — rate-limit exit / stderr needles."""

    @pytest.mark.parametrize("code", [429, 498], ids=["429", "498"])
    def test_rate_limit_exit_codes_are_retryable(self, code: int) -> None:
        from mergecraft.utils.provider_failure import is_retryable_cli_failure

        assert is_retryable_cli_failure(returncode=code) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            "Error: rate limit exceeded",
            "RATE_LIMIT hit",
            "too many requests — slow down",
            "model overloaded, try again",
            "HTTP 429 from provider",
        ],
        ids=["rate-limit", "rate_limit", "too-many", "overloaded", "429-text"],
    )
    def test_stderr_needles_are_retryable(self, stderr: str) -> None:
        from mergecraft.utils.provider_failure import is_retryable_cli_failure

        assert is_retryable_cli_failure(returncode=1, stderr=stderr) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            "You've hit your usage limit. Upgrade to Pro or try again at Aug 27th.",
            "insufficient_quota: you exceeded your current quota",
            "Quota exceeded for this billing period",
        ],
        ids=["codex-usage-limit", "insufficient_quota", "quota-exceeded"],
    )
    def test_quota_exhaustion_is_retryable_for_failover(self, stderr: str) -> None:
        """#446 — quota wording matches none of the rate-limit needles.

        Retrying the same provider cannot succeed until the quota resets, but
        the next entry in the chain is unaffected, so this must still advance
        rather than terminate the run. The first case is the verbatim Codex
        message that killed PR #443's review.
        """
        from mergecraft.utils.provider_failure import is_retryable_cli_failure

        assert is_retryable_cli_failure(returncode=1, stderr=stderr) is True

    def test_benign_cli_chatter_is_not_retryable(self) -> None:
        """Guard the other direction: the stderr line PR #443 actually reported
        is not a provider refusal and must not be read as one.
        """
        from mergecraft.utils.provider_failure import is_retryable_cli_failure

        assert (
            is_retryable_cli_failure(returncode=1, stderr="Reading additional input from stdin...")
            is False
        )

    def test_ordinary_failure_is_not_retryable(self) -> None:
        from mergecraft.utils.provider_failure import is_retryable_cli_failure

        assert is_retryable_cli_failure(returncode=1, stderr="syntax error") is False
        assert is_retryable_cli_failure(returncode=None, stderr="") is False


class TestRetryTransientSafeMethods:
    """Direct ``retry_transient_safe_methods`` — safe+transient only.

    Guard-deletion anchor: if mutations were ever retried, POST+5xx would
    return True here and ``test_mutation_5xx_is_not_retried`` would also climb.
    """

    def _state(
        self,
        *,
        method: str,
        exc: BaseException | None,
        via: str = "args",
    ) -> Any:
        from tenacity import Future, RetryCallState, Retrying

        retrying = Retrying()
        if via == "kwargs":
            state = RetryCallState(retrying, None, (), {"method": method})
        else:
            # Mirror a bound ``request(self, method, path, ...)`` call shape.
            state = RetryCallState(retrying, None, (object(), method, "/x"), {})
        fut = Future(1)
        if exc is None:
            fut.set_result({"ok": True})
        else:
            fut.set_exception(exc)
        state.outcome = fut
        return state

    def test_retries_safe_method_on_5xx(self) -> None:
        from mergecraft.utils.retry_policy import retry_transient_safe_methods

        policy = retry_transient_safe_methods()
        assert policy(self._state(method="GET", exc=_status_error(500))) is True

    def test_retries_safe_method_via_keyword(self) -> None:
        from mergecraft.utils.retry_policy import retry_transient_safe_methods

        policy = retry_transient_safe_methods()
        assert policy(self._state(method="HEAD", exc=_status_error(429), via="kwargs")) is True

    def test_does_not_retry_mutation_on_5xx(self) -> None:
        from mergecraft.utils.retry_policy import retry_transient_safe_methods

        policy = retry_transient_safe_methods()
        assert policy(self._state(method="POST", exc=_status_error(500))) is False
        assert policy(self._state(method="DELETE", exc=_status_error(503), via="kwargs")) is False

    def test_does_not_retry_permanent_4xx(self) -> None:
        from mergecraft.utils.retry_policy import retry_transient_safe_methods

        policy = retry_transient_safe_methods()
        assert policy(self._state(method="GET", exc=_status_error(404))) is False

    def test_does_not_retry_on_success(self) -> None:
        from mergecraft.utils.retry_policy import retry_transient_safe_methods

        policy = retry_transient_safe_methods()
        assert policy(self._state(method="GET", exc=None)) is False
