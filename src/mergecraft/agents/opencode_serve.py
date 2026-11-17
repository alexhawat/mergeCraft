"""Manage OpenCode's serve subprocess and HTTP prompt sessions.

Module: mergecraft.agents.opencode_serve
Depends: httpx, loguru, mergecraft.agents.{opencode_config,opencode_tool_parts,shared}

Exports:
    ProviderTimeoutError — controlled failure when the provider times out.
    SERVER_LOG_TAIL_LINES — size of the bounded diagnostic tail.
    ServerHandle — child lifecycle, output drains and listening address.
    boot_opencode_server — start the server and wait for its listening URL.
    opencode_provider_http_timeout_s — resolve the provider request timeout.
    prompt_session — send a prompt and capture tracing when it is enabled.
    prompt_session_http — send the HTTP turn and interpret the response.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import replace
from typing import TYPE_CHECKING, Final

import httpx
from loguru import logger

from mergecraft.agents.opencode_config import opencode_applied_model_params
from mergecraft.agents.opencode_tool_parts import record_opencode_part
from mergecraft.agents.shared import (
    AgentResult,
    AgentUsage,
    log_token_table,
    resolve_cache_read,
    spawn_agent_cli,
    with_prompt,
)
from mergecraft.tracing import current_tracer
from mergecraft.tracing.genai import (
    input_messages_attrs,
    output_messages_attrs,
    request_attrs,
    usage_attrs_from_agent_usage,
    usage_unavailable_attrs,
)
from mergecraft.tracing.http import instrument_httpx
from mergecraft.utils.process_group import (
    kill_process_group,
    register_process_group,
    unregister_process_group,
)

if TYPE_CHECKING:
    from typing import IO

    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.tracing.content import ContentCapture


# OpenCode provider HTTP reads can outlast the generic 600s external-op default
# (Nous inference hung ~10min in PR #442). Match the workflow action timeout
# (25m) so httpx does not abort before the Action's own budget.
_OPENCODE_PROVIDER_HTTP_TIMEOUT_DEFAULT_S: Final[float] = 1500.0

# Ring-buffer depth for `opencode serve` output. Bounded because the buffer is
# a diagnostic tail, not a log sink: enough to explain a stall, never enough to
# grow without limit on a long run.
SERVER_LOG_TAIL_LINES: Final[int] = 50

# ``opencode serve`` boot budget and wait granularity. Boot waits on the URL
# event in short slices so a cancel request, an early exit and the deadline are
# all observed promptly; the wait itself is never a blocking ``readline()``.
_BOOT_DEADLINE_S: Final[float] = 30.0
_BOOT_POLL_S: Final[float] = 0.1

# The listening URL the server prints on stdout once it is ready.
_URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://[^\s]+")


def opencode_provider_http_timeout_s() -> float:
    """Return the httpx timeout for OpenCode provider HTTP session calls."""
    from mergecraft.config.env import RunBoundsEnv

    timeout = RunBoundsEnv().external_operation_timeout_s
    if timeout is None:
        return _OPENCODE_PROVIDER_HTTP_TIMEOUT_DEFAULT_S
    return timeout


class ProviderTimeoutError(RuntimeError):
    """Raised when the opencode provider endpoint times out.

    This is a controlled domain error so callers (``shared.run`` /
    ``review.offline_agent.run_offline_agent_review``) treat the attempt as a clean failure
    instead of letting a raw ``httpx.ReadTimeout`` traceback abort the whole
    review.
    """


class ServerHandle:
    """Own the serve child, its output drains and its listening address."""

    def __init__(
        self,
        proc: subprocess.Popen[str] | subprocess.Popen[bytes],
        *,
        base_url: str = "",
        url_event: threading.Event | None = None,
    ) -> None:
        self.proc = proc
        self.base_url = base_url
        self._closed = False
        self._recent: deque[str] = deque(maxlen=SERVER_LOG_TAIL_LINES)
        self._recent_lock = threading.Lock()
        self._drains: list[threading.Thread] = []
        # Set by the stdout drain when the server prints its listening URL.
        self._url_event = url_event

    def start_draining(self) -> None:
        """Consume the child's pipes from spawn for the rest of its life (#449).

        Boot waits for the listening URL on an event this stdout drain sets, so
        both pipes are read from the moment the child exists — not only after
        the URL appears. Without a reader the child blocks in ``write()`` as
        soon as it fills the platform pipe buffer and stops answering HTTP — a
        hang with no output, which is exactly what an unexplained provider
        timeout looks like.
        """
        for stream, label in ((self.proc.stdout, "out"), (self.proc.stderr, "err")):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._drain,
                args=(stream, label),
                name=f"opencode-serve-{label}",
                daemon=True,
            )
            thread.start()
            self._drains.append(thread)

    def _drain(self, stream: IO[str] | IO[bytes], label: str) -> None:
        try:
            while raw := stream.readline():
                text = (
                    raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                ).rstrip()
                if not text:
                    continue
                # ``deque.append`` is itself atomic, but that says nothing
                # about *iteration*: joining the deque while a drain thread
                # appends raises ``RuntimeError: deque mutated during
                # iteration`` until the buffer reaches ``maxlen``. Since
                # recent_output() is called from inside the timeout handler,
                # that would replace the clean failed AgentResult with an
                # exception — so both sides take this lock.
                with self._recent_lock:
                    self._recent.append(text)
                if label == "out" and self._url_event is not None and not self.base_url:
                    match = _URL_RE.search(text)
                    if match:
                        self.base_url = match.group(0).rstrip("/")
                        self._url_event.set()
                logger.debug("[opencode serve/{}] {}", label, text)
        except (OSError, ValueError):
            # Pipe closed under us during teardown — expected, not an error.
            return

    def recent_output(self) -> str:
        """Return the buffered tail of server output, newest last."""
        with self._recent_lock:
            lines = list(self._recent)
        return "\n".join(lines)

    def close(self, *, already_exited: bool = False) -> None:
        """Kill (unless the child already exited), reap and unregister the group.

        Every boot failure path funnels here so a failed boot never leaves its
        process group registered or its child unreaped (P5, N9). Callers that
        have already observed the child exit pass ``already_exited=True`` so no
        signal is sent to a dead (and possibly recycled) process group.
        """
        if self._closed:
            return
        self._closed = True
        pid = self.proc.pid
        if already_exited:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=5)
        elif self.proc.poll() is None:
            kill_process_group(pid)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    self.proc.kill()
        unregister_process_group(pid)


def _boot_wait_slice(deadline: float) -> float:
    """Return the next bounded wait for the boot URL event.

    Never past ``deadline``: a caller's fake clock (or a real one) that has
    already blown the deadline gets ``0.0`` so the loop re-checks and raises
    instead of sleeping out the whole budget.
    """
    remaining = deadline - time.time()
    if remaining <= 0:
        return 0.0
    return min(_BOOT_POLL_S, remaining)


def boot_opencode_server(
    *,
    cli: str,
    env: dict[str, str],
    cwd: str,
    cancel: threading.Event | None = None,
) -> ServerHandle:
    """Start an OpenCode server and wait for its listening URL."""
    proc = spawn_agent_cli(
        [cli, "serve", "--port", "0", "--hostname", "127.0.0.1"],
        env=env,
        cwd=cwd,
        errors="replace",
    )
    assert proc.stdout is not None
    # Register at spawn and drain both pipes from spawn: a boot that hangs must
    # already be visible to run-level cleanup, and an unread stderr would block
    # the child in ``write()`` before it ever prints its URL (P5, N9).
    register_process_group(proc.pid)
    url_event = threading.Event()
    handle = ServerHandle(proc=proc, url_event=url_event)
    handle.start_draining()

    deadline = time.time() + _BOOT_DEADLINE_S
    exited = False
    try:
        while not url_event.wait(timeout=_boot_wait_slice(deadline)):
            if cancel is not None and cancel.is_set():
                msg = "opencode serve boot cancelled"
                raise RuntimeError(msg)
            if proc.poll() is not None:
                exited = True
                err = handle.recent_output()
                if not err and proc.stderr is not None:
                    with contextlib.suppress(OSError, ValueError):
                        raw = proc.stderr.read()
                        err = (
                            raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                        ).strip()
                msg = f"opencode serve exited early: {err}"
                raise RuntimeError(msg)
            if time.time() >= deadline:
                msg = "opencode serve did not print a listening URL"
                raise RuntimeError(msg)
    except BaseException:
        handle.close(already_exited=exited)
        raise
    return handle


async def prompt_session(
    *,
    base_url: str,
    session_id: str,
    text: str,
    model: dict[str, str] | None,
    resolved_model: str | None = None,
    capture_policy: ContentCapture | None = None,
    tool_state: ToolState | None = None,
) -> AgentResult:
    """Prompt the opencode session — the one harness path with full payload visibility.

    OB3: unlike the CLI harnesses (whose NDJSON streams surface only
    agent-level text), this HTTP path sees the actual prompt sent and the
    completion returned, so it wraps the exchange in an ``llm.call`` span
    carrying the request model, the policy-gated input/output messages
    (O5), and the token usage. The executed model is NOT stamped: the
    opencode session response does not reliably report it, and a guessed
    value would fake the D11 fallback signal (coverage recorded in
    ``agents/_stream_consumer.py``). Tracing never fails the run
    (convention 3) — every capture step degrades to missing attrs.
    """
    tracer = current_tracer()
    if tracer is None:
        return await prompt_session_http(
            base_url=base_url,
            session_id=session_id,
            text=text,
            model=model,
            tool_state=tool_state,
        )
    model_slug = f"{model['providerID']}/{model['modelID']}" if model else None
    gen_ai_system = model.get("providerID") if model else None
    with tracer.start_span("llm.call") as span:
        try:
            span.set_attribute("gen_ai.operation.name", "chat")
            if gen_ai_system:
                span.set_attribute("gen_ai.system", gen_ai_system)
            model_params = opencode_applied_model_params(resolved_model or model_slug)
            for key, value in request_attrs(model=model_slug, params=model_params).items():
                span.set_attribute(key, value)
            if capture_policy is not None:
                for key, value in input_messages_attrs(
                    [{"role": "user", "content": text}], policy=capture_policy
                ).items():
                    span.set_attribute(key, value)
        except Exception as exc:
            logger.debug("opencode llm.call request attrs failed: {}", exc)
        result = await prompt_session_http(
            base_url=base_url,
            session_id=session_id,
            text=text,
            model=model,
            tool_state=tool_state,
        )
        from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

        priced_usage = apply_catalog_cost_to_usage(
            result.usage,
            model=resolved_model or model_slug,
        )
        if priced_usage is not result.usage:
            result = replace(result, usage=priced_usage)
        try:
            if result.usage is not None:
                for key, value in usage_attrs_from_agent_usage(
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cache_read_tokens=result.usage.cache_read_tokens,
                    cache_write_tokens=result.usage.cache_write_tokens,
                    cost_usd=result.usage.cost_usd,
                ).items():
                    span.set_attribute(key, value)
            else:
                for key, value in usage_unavailable_attrs().items():
                    span.set_attribute(key, value)
            if capture_policy is not None and result.output:
                for key, value in output_messages_attrs(
                    [{"role": "assistant", "content": result.output}],
                    policy=capture_policy,
                ).items():
                    span.set_attribute(key, value)
            if not result.success and result.error:
                span.set_status("error", result.error[:200])
        except Exception as exc:
            logger.debug("opencode llm.call response attrs failed: {}", exc)
        return result


async def prompt_session_http(
    *,
    base_url: str,
    session_id: str,
    text: str,
    model: dict[str, str] | None,
    tool_state: ToolState | None = None,
) -> AgentResult:
    """Send a session turn over HTTP and return its output and usage."""
    payload: dict[str, object] = {
        "parts": [{"type": "text", "text": text}],
    }
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=opencode_provider_http_timeout_s()) as client:
        # T2 / D8 — narrow instrumentation: wrap clients mergeCraft builds
        # (the custom OpenAI-compatible provider path) so every outbound
        # ``send`` emits an ``http.client.request`` span. ``current_tracer``
        # resolves to the active mergeCraft span's tracer or ``None`` when
        # tracing is disabled — ``instrument_httpx`` no-ops in that case
        # without setting the idempotency sentinel so a later activation
        # is possible.
        instrument_httpx(client, tracer=current_tracer())
        try:
            resp = await client.post(
                f"{base_url}/session/{session_id}/message",
                json=payload,
            )
            if resp.status_code in (404, 405):
                # Fallback path for older/newer API shapes: only "no such
                # endpoint / method" means the alternate endpoint exists. Every
                # other >=400 — 429, 5xx — may mean the prompt was accepted and
                # is still executing, so reposting would start a second agent
                # turn on the same session and report the wrong status (#444).
                resp = await client.post(
                    f"{base_url}/session/{session_id}/prompt",
                    json=payload,
                )
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            logger.warning("opencode provider request timed out: {}", exc)
            raise ProviderTimeoutError(f"opencode provider request timed out: {exc}") from exc
        if resp.status_code >= 400:
            # 429 and 5xx are the gateway saying "not now", not "never" — mark
            # them retryable so the chain moves to the next entry (#444). Other
            # 4xx are request-shaped faults that the next model would repeat.
            retryable = resp.status_code == 429 or resp.status_code >= 500
            return with_prompt(
                AgentResult(
                    success=False,
                    error=f"opencode prompt failed ({resp.status_code}): {resp.text[:500]}",
                    metadata={"retryable": True} if retryable else {},
                ),
                text,
            )
        data = resp.json() if resp.content else {}

    usage: AgentUsage | None = None
    output = ""
    if isinstance(data, dict):
        for part in data.get("parts") or []:
            record_opencode_part(tool_state, part)
        output = str(
            data.get("result") or data.get("text") or data.get("output") or json.dumps(data)[:2000]
        )
        # Best-effort usage extraction
        info = data.get("info") or data.get("usage") or {}
        if isinstance(info, dict):
            inp = int(info.get("input_tokens") or info.get("input") or 0)
            out = int(info.get("output_tokens") or info.get("output") or 0)
            cache_read = resolve_cache_read(info)
            cost = info.get("cost") or info.get("costUsd")
            total_tokens = inp + out + cache_read.additive
            if total_tokens > 0:
                cost_usd = float(cost) if cost is not None else None
                usage = AgentUsage(
                    agent="opencode",
                    input_tokens=inp + cache_read.additive,
                    output_tokens=out,
                    cache_read_tokens=cache_read.reported or None,
                    cost_usd=cost_usd,
                )
                model_slug = f"{model['providerID']}/{model['modelID']}" if model else None
                from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

                usage = apply_catalog_cost_to_usage(usage, model=model_slug)
                log_token_table(
                    input_tokens=inp,
                    cache_read=0,
                    cache_write=0,
                    output=out,
                    cost_usd=usage.cost_usd if usage else None,
                )
    return with_prompt(AgentResult(success=True, output=output or None, usage=usage), text)


__all__ = [
    "SERVER_LOG_TAIL_LINES",
    "ProviderTimeoutError",
    "ServerHandle",
    "boot_opencode_server",
    "opencode_provider_http_timeout_s",
    "prompt_session",
    "prompt_session_http",
]
