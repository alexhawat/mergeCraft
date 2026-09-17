"""Pinned async Jev client: retry, trace, cost, kill-switch (J2).

Wraps TypeSafe's ``AsyncTypeSafeClient``. Tests drive this module against
recorded transport fixtures — CI makes zero live TypeSafe calls (D14).

Exports:
    PINNED_MODEL: Versioned Jev model id (D8).
    TYPESAFE_API_KEY_ENV: Credential environment variable.
    TypeSafeAPIError: HTTP/API failure with ``status_code`` and ``code``.
    AsyncJevClient: Public async client.
    RecordedTransport: Replay a recorded TypeSafe envelope.
    FlakyRecordedTransport: Transient-then-success recorded transport.
    map_typesafe_error: Map ``TypeSafeAPIError`` onto ``ProviderFailureClass``.
    mapped_retry_policy: TypeSafe ``RetryPolicy`` using repo retry conventions.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger
from tenacity import AsyncRetrying, retry_if_exception

from mergecraft.jev.cost import TokenBudget, compute_cost
from mergecraft.jev.types import (
    PINNED_MODEL,
    JevCallResult,
    JevError,
    SystemOneResponse,
    parse_system_one_response,
)
from mergecraft.tracing.genai import (
    request_attrs,
    response_attrs,
    usage_attrs,
    usage_unavailable_attrs,
)
from mergecraft.utils.provider_failure import ProviderFailureClass
from mergecraft.utils.retry_policy import DEFAULT_STOP, DEFAULT_WAIT

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.config.settings import JevSettings
    from mergecraft.tracing import Tracer

TYPESAFE_API_KEY_ENV: str = "TYPESAFE_API_KEY"

# TypeSafe RetryPolicy.max_retries is "retries after the first attempt".
# DEFAULT_STOP is stop_after_attempt(3) → 2 retries.
_TYPESAFE_MAX_RETRIES: int = 2
_TYPESAFE_BACKOFF_INITIAL: float = 0.5
_TYPESAFE_BACKOFF_MAX: float = 8.0
_TYPESAFE_RETRY_TIMEOUT: float = 30.0


class TypeSafeAPIError(Exception):
    """TypeSafe HTTP/API failure with the fields the provider-failure path needs.

    The SDK class uses ``status`` and has no ``code``. This wrapper is the
    seam tests and ``map_typesafe_error`` share; live SDK errors are adapted
    into it before they leave the client.
    """

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int,
        code: str,
        body: object | None = None,
    ) -> None:
        super().__init__(message or code)
        self.status_code = status_code
        self.code = code
        self.body = body


class JevTransport(Protocol):
    """Async ``system_one`` seam — recorded in CI, live TypeSafe in production."""

    calls: int
    last_model: str | None

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> SystemOneResponse: ...


def map_typesafe_error(exc: TypeSafeAPIError) -> ProviderFailureClass:
    """Map a TypeSafe HTTP error onto the repo provider-failure taxonomy.

    Args:
        exc: Structured TypeSafe failure.

    Returns:
        ProviderFailureClass: ``RETRYABLE`` for 429 / 5xx (repo retry
        convention); ``PERMANENT`` for other 4xx.
    """
    if exc.status_code == 429 or exc.status_code >= 500:
        return ProviderFailureClass.RETRYABLE
    return ProviderFailureClass.PERMANENT


def mapped_retry_policy() -> Any:
    """Build a TypeSafe ``RetryPolicy`` from ``utils.retry_policy`` conventions.

    Returns:
        typesafe_sdk.RetryPolicy: 3 attempts, 429+5xx, backoff max 8s.
    """
    from typesafe_sdk import RetryPolicy

    return RetryPolicy(
        max_retries=_TYPESAFE_MAX_RETRIES,
        backoff_initial=_TYPESAFE_BACKOFF_INITIAL,
        backoff_max=_TYPESAFE_BACKOFF_MAX,
        http_statuses={429, *range(500, 600)},
        timeout=_TYPESAFE_RETRY_TIMEOUT,
    )


def _is_retryable_typesafe(exc: BaseException) -> bool:
    return isinstance(exc, TypeSafeAPIError) and (exc.status_code == 429 or exc.status_code >= 500)


def _raise_from_envelope(error: dict[str, Any], http: dict[str, Any] | None) -> None:
    status = error.get("status_code")
    if not isinstance(status, int):
        raw_http = http or {}
        raw_status = raw_http.get("status")
        status = raw_status if isinstance(raw_status, int) else 500
    code = error.get("code")
    if not isinstance(code, str) or not code:
        code = "typesafe_error"
    raise TypeSafeAPIError(code, status_code=status, code=code, body=error)


class RecordedTransport:
    """Replay one recorded TypeSafe envelope. Never opens a network socket."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0
        self.last_model: str | None = None

    @classmethod
    def from_fixture(cls, path: Path) -> RecordedTransport:
        """Load a recorded envelope from disk.

        Args:
            path: JSON fixture path under ``tests/jev/fixtures/transport/``.

        Returns:
            RecordedTransport: Ready to replay the envelope.
        """
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = f"transport fixture must be a JSON object: {path}"
            raise TypeError(msg)
        return cls(raw)

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> SystemOneResponse:
        del state, questions
        self.calls += 1
        self.last_model = model
        error = self._payload.get("error")
        if isinstance(error, dict):
            http = self._payload.get("http")
            _raise_from_envelope(error, http if isinstance(http, dict) else None)
        body = self._payload.get("body", self._payload)
        if not isinstance(body, dict):
            raise JevError("recorded transport body is not an object", code="invalid_response")
        return parse_system_one_response(body)


class FlakyRecordedTransport:
    """Fail ``fail_times`` times from a recorded error, then succeed."""

    def __init__(
        self,
        *,
        failures: dict[str, Any],
        success: Path,
        fail_times: int,
    ) -> None:
        self._failures = failures
        self._success = RecordedTransport.from_fixture(success)
        self._fail_times = fail_times
        self.calls = 0
        self.last_model: str | None = None

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> SystemOneResponse:
        self.calls += 1
        self.last_model = model
        if self.calls <= self._fail_times:
            error = self._failures.get("error")
            http = self._failures.get("http")
            if isinstance(error, dict):
                _raise_from_envelope(error, http if isinstance(http, dict) else None)
            raise TypeSafeAPIError("server_error", status_code=500, code="server_error")
        return await self._success.system_one(state=state, questions=questions, model=model)


class LiveTypeSafeTransport:
    """Dispatch through ``AsyncTypeSafeClient``. Unused in CI (D14)."""

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key
        self.calls = 0
        self.last_model: str | None = None

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> SystemOneResponse:
        from typesafe_sdk import AsyncTypeSafeClient

        self.calls += 1
        self.last_model = model
        try:
            async with AsyncTypeSafeClient(
                api_key=self._api_key,
                model=PINNED_MODEL,
                retry=mapped_retry_policy(),
            ) as sdk:
                response = await sdk.system_one(
                    state=state,
                    questions=questions,
                    model=model,
                )
        except Exception as exc:
            raise _adapt_sdk_error(exc) from exc
        return _response_from_sdk(response)


def _adapt_sdk_error(exc: BaseException) -> TypeSafeAPIError | BaseException:
    status = getattr(exc, "status", None)
    if not isinstance(status, int):
        status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        return exc
    body = getattr(exc, "body", None)
    code = _code_from_sdk_body(body) or type(exc).__name__
    return TypeSafeAPIError(str(exc), status_code=status, code=code, body=body)


def _code_from_sdk_body(body: object) -> str | None:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("code", "type"):
                value = error.get(key)
                if isinstance(value, str) and value:
                    return value
        for key in ("code", "type"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _response_from_sdk(response: object) -> SystemOneResponse:
    usage = getattr(response, "usage", None)
    answers_obj = getattr(response, "answers", {}) or {}
    raw: dict[str, Any] = {
        "request_id": getattr(response, "request_id", None),
        "model": getattr(response, "model", PINNED_MODEL),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
        "answers": {
            str(name): _answer_to_mapping(answer) for name, answer in dict(answers_obj).items()
        },
    }
    return parse_system_one_response(raw)


def _answer_to_mapping(answer: object) -> dict[str, Any]:
    if isinstance(answer, dict):
        return {str(key): value for key, value in answer.items()}
    dump = getattr(answer, "model_dump", None)
    dumped = dump() if callable(dump) else None
    if isinstance(dumped, dict):
        return {str(key): value for key, value in dumped.items()}
    mapped: dict[str, Any] = {}
    for key in ("noul", "choice", "confidence", "score", "probabilities", "legend"):
        if hasattr(answer, key):
            mapped[key] = getattr(answer, key)
    return mapped


def _resolve_api_key(explicit: str | None) -> str | None:
    if explicit is not None and explicit.strip():
        return explicit.strip()
    env = os.environ.get(TYPESAFE_API_KEY_ENV, "").strip()
    return env or None


class AsyncJevClient:
    """Pinned async Jev client. Disabled / no-credential paths skip, never fail."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: JevTransport | None = None,
        settings: JevSettings | None = None,
        budget: TokenBudget | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._settings = settings
        self._api_key = _resolve_api_key(api_key)
        self.transport = transport
        self._budget = (
            budget if budget is not None else TokenBudget(max_tokens=_budget_tokens(settings))
        )
        self._tracer = tracer
        self._model = settings.model if settings is not None else PINNED_MODEL

    def availability_skip(self, *, pack_id: str | None = None) -> JevCallResult | None:
        """Return an honest skip when this client must not dispatch (D4).

        Args:
            pack_id: Optional pack to honor ``JevSettings.packs``.

        Returns:
            JevCallResult | None: A skip result, or ``None`` when a call may proceed.
        """
        if self._settings is not None and not self._settings.enabled:
            return _skip("disabled")
        if pack_id is not None and not _pack_enabled(self._settings, pack_id):
            return _skip("disabled")
        if self._api_key is None:
            return _skip("credential_absent")
        if self._budget.should_stop():
            return _skip("kill_switch")
        return None

    async def call(
        self,
        *,
        state: dict[str, Any] | None,
        pack_id: str,
        unit_id: str,
        trust_tier: str = "trusted",
        ratchet_applied: bool = False,
        questions: dict[str, Any] | None = None,
    ) -> JevCallResult:
        """Ask Jev one question pack about ``state``.

        Args:
            state: Structured unit payload. ``None`` is ``invalid_state``.
            pack_id: Versioned question-pack id recorded on the span.
            unit_id: Stable unit id recorded on the span.
            trust_tier: ``trusted`` or ``untrusted`` (D5 / D9).
            ratchet_applied: Whether the one-way ratchet is in force (D9).
            questions: Optional question dict; recorded transport ignores it.

        Returns:
            JevCallResult: A completed call or an honest skip.
        """
        skipped = self.availability_skip(pack_id=pack_id)
        if skipped is not None:
            return skipped
        if state is None:
            raise JevError("system_one state must be a mapping", code="invalid_state")

        transport = self._require_transport()
        started = time.perf_counter()
        call_questions = questions or {}
        if isinstance(transport, LiveTypeSafeTransport):
            response = await transport.system_one(
                state=state, questions=call_questions, model=self._model
            )
        else:
            response = await self._dispatch(
                transport, state=state, questions=call_questions, model=self._model
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        usage = response.usage
        assessment = compute_cost(
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        accepted = self._budget.record_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        if not accepted:
            logger.warning(
                "jev kill-switch armed after call unit_id={} pack_id={}", unit_id, pack_id
            )
        self._emit_span(
            pack_id=pack_id,
            unit_id=unit_id,
            trust_tier=trust_tier,
            ratchet_applied=ratchet_applied,
            response=response,
            cost_usd=assessment.cost_usd,
        )
        return JevCallResult(
            skipped=False,
            available=True,
            incomplete=False,
            model=response.model,
            response=response,
            latency_ms=latency_ms,
            cost_known=assessment.cost_known,
            cost_usd=assessment.cost_usd,
        )

    async def _dispatch(
        self,
        transport: JevTransport,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> SystemOneResponse:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_retryable_typesafe),
            wait=DEFAULT_WAIT,
            stop=DEFAULT_STOP,
            reraise=True,
        ):
            with attempt:
                return await transport.system_one(
                    state=state,
                    questions=questions,
                    model=model,
                )
        raise TypeSafeAPIError("retry exhausted", status_code=500, code="server_error")

    def _require_transport(self) -> JevTransport:
        if self.transport is not None:
            return self.transport
        if self._api_key is None:
            raise JevError("jev transport missing and credential absent", code="credential_absent")
        live = LiveTypeSafeTransport(api_key=self._api_key)
        self.transport = live
        return live

    def _emit_span(
        self,
        *,
        pack_id: str,
        unit_id: str,
        trust_tier: str,
        ratchet_applied: bool,
        response: SystemOneResponse,
        cost_usd: float | None,
    ) -> None:
        tracer = self._tracer
        if tracer is None:
            return
        attrs: dict[str, Any] = {}
        attrs.update(request_attrs(model=self._model))
        attrs.update(response_attrs(model=response.model))
        if response.usage.input_tokens is None or response.usage.output_tokens is None:
            attrs.update(usage_unavailable_attrs())
        attrs.update(
            usage_attrs(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=cost_usd,
            )
        )
        attrs["mergecraft.jev.unit_id"] = unit_id
        attrs["mergecraft.jev.pack_id"] = pack_id
        attrs["mergecraft.jev.trust_tier"] = trust_tier
        attrs["mergecraft.jev.ratchet_applied"] = ratchet_applied
        with tracer.start_span("llm.call") as span:
            for key, value in attrs.items():
                span.set_attribute(key, value)


def _pack_enabled(settings: JevSettings | None, pack_id: str) -> bool:
    from mergecraft.config.settings import default_settings

    packs = settings.packs if settings is not None else default_settings().jev.packs
    return bool(packs.get(pack_id, True))


def _budget_tokens(settings: JevSettings | None) -> int:
    if settings is not None:
        return settings.budget_tokens
    return 250_000


def _skip(reason: str) -> JevCallResult:
    logger.info("jev skip reason={}", reason)
    return JevCallResult(
        skipped=True,
        available=False,
        incomplete=False,
        reason=reason,
    )


__all__ = [
    "PINNED_MODEL",
    "TYPESAFE_API_KEY_ENV",
    "AsyncJevClient",
    "FlakyRecordedTransport",
    "JevError",
    "JevTransport",
    "LiveTypeSafeTransport",
    "RecordedTransport",
    "TypeSafeAPIError",
    "map_typesafe_error",
    "mapped_retry_policy",
]
