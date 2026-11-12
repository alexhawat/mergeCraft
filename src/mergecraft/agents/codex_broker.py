"""Codex credential-broker session lifecycle and config wiring (plan 18 W3).

Exports:
    CodexBrokeredRun: Prepared broker env + posture with explicit teardown.
    OPENAI_API_KEY_ENV: Env var name for the OpenAI API key.
    active_broker_handle: Running loopback handle when the session is active.
    add_broker_openai_config: Point built-in OpenAI routing at the broker.
    begin_broker_session: Resolve posture and start the loopback broker.
    broker_config_for_api_key: Build broker config for an OpenAI API key.
    current_broker_session: Active session for this run context, if any.
    prepare_codex_brokered_run: Start broker, MCP config, and agent env.
    set_broker_session: Bind or clear the broker session for this run context.
    stop_broker_session: Stop a broker session context manager.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mergecraft.security import broker as _broker_mod
from mergecraft.security.broker import (
    OPENAI_UPSTREAM_BASE_URL,
    OPENAI_UPSTREAM_HOST,
    CodexBrokerPosture,
    CredentialBrokerConfig,
    CredentialBrokerHandle,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from mergecraft.agents.shared import AgentRunContext

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

broker_run_record_fields = _broker_mod.broker_run_record_fields
resolve_codex_broker_posture = _broker_mod.resolve_codex_broker_posture


@dataclass(slots=True)
class CodexBrokeredRun:
    """Result of :func:`prepare_codex_brokered_run` (plan 18 W3)."""

    agent_env: dict[str, str]
    broker_base_url: str | None
    posture: CodexBrokerPosture
    _session: CodexBrokerSession | None = field(default=None, repr=False)

    def close(self) -> None:
        """Stop the loopback broker and clear the context's session when owned."""
        if self._session is None:
            return
        session = self._session
        self._session = None
        stop_broker_session(session)
        if _active_broker_session.get() is session:
            _active_broker_session.set(None)

    def __enter__(self) -> CodexBrokeredRun:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@dataclass(slots=True)
class CodexBrokerSession:
    posture: CodexBrokerPosture
    handle: CredentialBrokerHandle | None = None
    _broker_cm: AbstractContextManager[CredentialBrokerHandle] | None = None

    @property
    def active(self) -> bool:
        return self.posture.active and self.handle is not None


# #1327 — the session is bound per run context, not per process. Concurrent
# Codex runs (roster or file-group fan-out) each see their own broker, and a
# second run's start no longer stops the first run's broker mid-request.
# ``asyncio`` tasks and ``asyncio.to_thread`` workers copy the context, so the
# driver's ``_build_env`` in the worker thread sees its own run's session.
_active_broker_session: ContextVar[CodexBrokerSession | None] = ContextVar(
    "mergecraft_codex_broker_session", default=None
)


def current_broker_session() -> CodexBrokerSession | None:
    """Return the broker session bound to the current run context, if any."""
    return _active_broker_session.get()


def active_broker_handle() -> CredentialBrokerHandle | None:
    session = current_broker_session()
    return session.handle if session is not None and session.active else None


def set_broker_session(session: CodexBrokerSession | None) -> None:
    """Bind ``session`` to the current run context (``None`` clears it).

    A different session already bound in *this* context is stopped first; a
    session bound by another, concurrent run is never touched.
    """
    previous = _active_broker_session.get()
    if session is not None and previous is not None and previous is not session:
        stop_broker_session(previous)
    _active_broker_session.set(session)


def broker_config_for_api_key(api_key: str) -> CredentialBrokerConfig:
    return CredentialBrokerConfig(
        upstream_base_url=OPENAI_UPSTREAM_BASE_URL,
        api_key=api_key,
        run_upstream_hosts=frozenset({OPENAI_UPSTREAM_HOST}),
    )


def stop_broker_session(session: CodexBrokerSession | None) -> None:
    if session is None or session._broker_cm is None:
        return
    session._broker_cm.__exit__(None, None, None)
    session._broker_cm = None
    session.handle = None


def _start_broker_session(*, api_key: str, posture: CodexBrokerPosture) -> CodexBrokerSession:
    config = broker_config_for_api_key(api_key)
    broker_cm = _broker_mod.credential_broker(config)
    try:
        handle = broker_cm.__enter__()
    except Exception as exc:
        msg = f"Codex credential broker refused to start: {exc}"
        raise RuntimeError(msg) from exc
    return CodexBrokerSession(posture=posture, handle=handle, _broker_cm=broker_cm)


def begin_broker_session(
    *,
    openai_api_key: str = "",
    posture: CodexBrokerPosture | None = None,
) -> CodexBrokerSession:
    """Resolve Codex broker posture and start the loopback broker when active."""
    resolved = posture or _broker_mod.resolve_codex_broker_posture(openai_api_key=openai_api_key)
    if not resolved.active:
        return CodexBrokerSession(posture=resolved)
    api_key = openai_api_key.strip() or os.environ.get(OPENAI_API_KEY_ENV, "").strip()
    if not api_key:
        inactive = CodexBrokerPosture(
            active=False,
            auth_mode="none",
            reason="broker inactive: no OpenAI API key configured",
        )
        return CodexBrokerSession(posture=inactive)
    return _start_broker_session(api_key=api_key, posture=resolved)


def broker_provider_base_url(broker_base_url: str) -> str:
    """Return the loopback broker URL Codex should use for ``openai_base_url``."""
    normalized = broker_base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def add_broker_openai_config(config: dict[str, Any], broker_base_url: str) -> None:
    """Route built-in OpenAI through the loopback credential broker (W3 / #594).

    Codex 0.149+ reserves ``model_providers.openai``; use top-level
    ``openai_base_url`` instead. The throwaway bearer belongs in
    ``OPENAI_API_KEY`` (see :func:`mergecraft.agents.codex._build_env`).
    """
    config["openai_base_url"] = broker_provider_base_url(broker_base_url)


def prepare_codex_brokered_run(
    ctx: AgentRunContext,
    *,
    openai_api_key: str = "",
) -> CodexBrokeredRun:
    """Start broker, build env, auth stub, and MCP config (plan 18 W3)."""
    from mergecraft.agents import codex as codex_module

    expected_posture = _broker_mod.resolve_codex_broker_posture(openai_api_key=openai_api_key)
    session = begin_broker_session(openai_api_key=openai_api_key, posture=expected_posture)
    if expected_posture.active and not session.active:
        reason = session.posture.reason
        msg = f"Codex credential broker inactive: {reason}"
        raise RuntimeError(msg)
    posture = session.posture
    set_broker_session(session)
    try:
        codex_module.write_mcp_config(ctx)
        agent_env = codex_module._build_env(ctx)
    except Exception:
        stop_broker_session(session)
        set_broker_session(None)
        raise
    handle = session.handle
    broker_base_url = broker_provider_base_url(handle.base_url) if handle is not None else None
    # Clear the process-wide probe so later ``write_mcp_config`` calls without an
    # active ``_run()`` do not inherit broker routing from this setup path.
    set_broker_session(None)
    return CodexBrokeredRun(
        agent_env=agent_env,
        broker_base_url=broker_base_url,
        posture=posture,
        _session=session,
    )


__all__ = [
    "OPENAI_API_KEY_ENV",
    "CodexBrokerSession",
    "CodexBrokeredRun",
    "active_broker_handle",
    "add_broker_openai_config",
    "begin_broker_session",
    "broker_config_for_api_key",
    "broker_provider_base_url",
    "broker_run_record_fields",
    "current_broker_session",
    "prepare_codex_brokered_run",
    "resolve_codex_broker_posture",
    "set_broker_session",
    "stop_broker_session",
]
