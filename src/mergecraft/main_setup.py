"""Setup-script run + deadline-deduction helpers used by ``main.py``.

Extracted from ``main.py`` so the orchestrator stays under the 1k-line ceiling.
Both helpers carry over verbatim — the audit confirmed ``NO_ISSUES`` on the
setup-script runner (S1 / F6) and on the agent-deadline deducter (S1 / F6).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.utils.process_group import (
    kill_process_group,
    register_process_group,
    unregister_process_group,
)

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.tool_state import ToolState


async def _run_setup_script(
    state: ToolState,
    settings: RepoSettings,
    trust_tier: str,
    event_name: str,
    setup_timeout_s: int,
) -> tuple[str, str, float]:
    """Run the trusted-tier ``setup_script`` and report a skip / failure reason.

    Returns ``(setup_hook_failure, setup_script_skip_reason, setup_elapsed_s)``.
    A non-trusted tier sets ``setup_script_skip_reason`` and returns; a
    trusted tier with no script returns zero-initialized values; a trusted
    tier with a script runs the script under a session leader so
    ``kill_process_group`` reaches grandchildren (F6), redacts ``stderr``
    via :func:`mergecraft.analyzers.redact.redact_secrets`, and stamps the
    failure / skip reason on the run's :class:`ToolState` plus a warning
    log line. The failure / skip reason is read off ``ToolState`` by
    :func:`main` when it resolves the ``RunOutcome`` — the helper writes
    it, but the read + classification live in the orchestrator.
    """
    setup_script_skip_reason = ""
    setup_hook_failure = ""
    setup_started_at = time.monotonic()
    if settings.setup_script:
        if trust_tier == "trusted":
            logger.info("» running setup script")
            proc = await asyncio.create_subprocess_shell(
                settings.setup_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # F6 — session leader so killpg reaches grandchildren
            )
            register_process_group(proc.pid)
            try:
                _out, err = await asyncio.wait_for(proc.communicate(), timeout=setup_timeout_s)
            except TimeoutError:
                # F6 — TERM → grace → KILL the whole tree (convention 9).
                kill_process_group(proc.pid)
                setup_hook_failure = f"setup script timed out after {setup_timeout_s}s"
            else:
                if proc.returncode != 0:
                    detail = redact_secrets((err or b"").decode(errors="replace")[:500])
                    setup_hook_failure = f"setup script failed (exit {proc.returncode}): {detail}"
            finally:
                unregister_process_group(proc.pid)
            if setup_hook_failure:
                state.setup_hook_failure = setup_hook_failure
                logger.warning("» {}", setup_hook_failure)
        else:
            setup_script_skip_reason = (
                f"skipped setup_script on untrusted tier ({event_name} event)"
            )
            state.setup_script_skip_reason = setup_script_skip_reason
            logger.warning("» {}", setup_script_skip_reason)
    setup_elapsed_s = time.monotonic() - setup_started_at
    return setup_hook_failure, setup_script_skip_reason, setup_elapsed_s


def _compute_agent_deadline(
    timeout_ms: int | None, setup_elapsed_s: float
) -> tuple[int | None, str]:
    """Deduct setup elapsed time from the agent deadline (S1 / F6).

    Returns ``(agent_timeout_ms, log_line_or_empty)``. When ``timeout_ms`` is
    ``None`` (``--notimeout``), the agent deadline is unbounded and no log
    line is emitted. Otherwise the deadline is ``max(1, timeout_ms -
    setup_elapsed_s * 1000)`` and a log line is returned whenever the
    deduction actually changed the deadline. The helper does not emit the
    log itself so the caller can route it through whichever logger bound
    the run; ``main`` discards the second tuple element.
    """
    if timeout_ms is None:
        return None, ""
    agent_timeout_ms = max(1, int(timeout_ms - setup_elapsed_s * 1000))
    if agent_timeout_ms != timeout_ms:
        return (
            agent_timeout_ms,
            f"» deducted setup elapsed {setup_elapsed_s:.2f}s from agent deadline ({timeout_ms / 1000}s -> {agent_timeout_ms / 1000}s)",
        )
    return agent_timeout_ms, ""


__all__ = ["_compute_agent_deadline", "_run_setup_script"]
