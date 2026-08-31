"""Codex credential-broker session lifecycle and config wiring (plan 18 W3).

Exports:
    CodexBrokeredRun: Prepared broker env + posture with explicit teardown.
    OPENAI_API_KEY_ENV: Env var name for the OpenAI API key.
    OPENAI_BROKER_PROVIDER_ID: ``model_providers`` table id for the broker.
    active_broker_handle: Running loopback handle when the session is active.
    add_broker_provider_table: Point ``model_providers.openai`` at the broker.
    begin_broker_session: Resolve posture and start the loopback broker.
    broker_config_for_api_key: Build broker config for an OpenAI API key.
    current_broker_session: Active session for this process, if any.
    prepare_codex_brokered_run: Start broker, MCP config, and agent env.
    set_broker_session: Install or replace the process-wide broker session.
    stop_broker_session: Stop a broker session context manager.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mergecraft.security import broker as _broker_mod
from mergecraft.security.broker import (
    CODEX_BROKER_BEARER_ENV,
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
OPENAI_BROKER_PROVIDER_ID = "openai"

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
        """Stop the loopback broker and clear the module session when owned."""
        global _active_broker_session
        if self._session is None:
            return
        session = self._session
        self._session = None
        stop_broker_session(session)
        with _broker_session_lock:
            if _active_broker_session is session:
                _active_broker_session = None

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


_active_broker_session: CodexBrokerSession | None = None
_broker_session_lock = threading.Lock()


def current_broker_session() -> CodexBrokerSession | None:
    with _broker_session_lock:
        return _active_broker_session


def active_broker_handle() -> CredentialBrokerHandle | None:
    session = current_broker_session()
    return session.handle if session is not None and session.active else None


def set_broker_session(session: CodexBrokerSession | None) -> None:
    global _active_broker_session
    with _broker_session_lock:
        if (
            session is not None
            and _active_broker_session is not None
            and _active_broker_session is not session
        ):
            stop_broker_session(_active_broker_session)
        _active_broker_session = session


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


def add_broker_provider_table(config: dict[str, Any], broker_base_url: str) -> None:
    """Point ``model_providers.openai`` at the loopback credential broker (W3).

    When the broker is active it owns the ``openai`` provider slot so Codex
    routes default OpenAI models through loopback. Custom gateway tables may
    still be present when ``MERGECRAFT_CUSTOM_PROVIDER_*`` env vars are set.
    """
    model_providers = config.get("model_providers")
    if not isinstance(model_providers, dict):
        model_providers = {}
        config["model_providers"] = model_providers
    model_providers[OPENAI_BROKER_PROVIDER_ID] = {
        "name": OPENAI_BROKER_PROVIDER_ID,
        "base_url": broker_base_url,
        "env_key": CODEX_BROKER_BEARER_ENV,
        "wire_api": "responses",
    }


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
    return CodexBrokeredRun(
        agent_env=agent_env,
        broker_base_url=handle.base_url if handle is not None else None,
        posture=posture,
        _session=session,
    )


__all__ = [
    "CODEX_BROKER_BEARER_ENV",
    "OPENAI_API_KEY_ENV",
    "OPENAI_BROKER_PROVIDER_ID",
    "CodexBrokerSession",
    "CodexBrokeredRun",
    "active_broker_handle",
    "add_broker_provider_table",
    "begin_broker_session",
    "broker_config_for_api_key",
    "broker_run_record_fields",
    "current_broker_session",
    "prepare_codex_brokered_run",
    "resolve_codex_broker_posture",
    "set_broker_session",
    "stop_broker_session",
]
