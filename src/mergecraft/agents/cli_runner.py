"""Shared lifecycle for streaming CLI attempts.

Drivers declare provider transport, event parsing, and result classification.
The runner owns spawning in the review checkout, pipe draining, watchdogs,
process-group cleanup, and usage on timeout. AgentImpl retains the outer
cancellation scope and integrity gate; post_run owns resumable retry policy.
Provider environment builders retain isolated homes and credential handling.

Exports:
    CliHarnessSpec: Provider-specific inputs to one streaming attempt.
    cli_working_directory: Resolve the review checkout with a no-repo fallback.
    run_cli_attempt: Run one attempt under shared process supervision.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents._stream_consumer import StreamSpanAccumulator, consume_stream
from mergecraft.agents.activity_watchdog import (
    event_has_model_output,
    event_type_name,
    watchdog_for_process,
)
from mergecraft.agents.shared import (
    STDERR_DRAIN_JOIN_TIMEOUT_S,
    AgentResult,
    spawn_agent_cli,
    start_stderr_drain,
    with_prompt,
)
from mergecraft.config.env import AgentRuntimeEnv
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.utils.process_group import (
    kill_process_group,
    track_process_group,
    wait_or_kill_process_group,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents.shared import AgentRunContext, AgentUsage


@dataclass(frozen=True)
class CliHarnessSpec:
    """Transport and provider callbacks for one CLI invocation."""

    label: str
    command: list[str]
    env: dict[str, str]
    accumulator: StreamSpanAccumulator
    handler: Callable[[StreamSpanAccumulator, dict[str, Any]], None]
    classify: Callable[[int, str], AgentResult]
    stdin_text: str | None = None
    prompt: str | None = None
    close_spans: Callable[[], None] | None = None
    usage: Callable[[], AgentUsage | None] | None = None
    missing_binary: Callable[[], AgentResult] | None = None


def cli_working_directory(ctx: AgentRunContext) -> str:
    """Resolve the checkout for every CLI backend.

    Args:
        ctx (AgentRunContext): Run whose primary repository is being reviewed.

    Returns:
        str: Primary checkout, or the process directory before repo setup.

    Examples:
        An offline review runs in its checkout even when invoked elsewhere.
    """
    try:
        directory = primary_repo_state(ctx.tool_state).dir
    except RuntimeError:
        directory = ""
    return directory or os.getcwd()


def run_cli_attempt(spec: CliHarnessSpec, ctx: AgentRunContext) -> AgentResult:
    """Execute a provider's stream with shared timeout and cleanup semantics.

    Args:
        spec (CliHarnessSpec): Transport, parser, and classifier for this attempt.
        ctx (AgentRunContext): Checkout and idle budget for the current run.

    Returns:
        AgentResult: Provider result, or a retryable timeout retaining usage.

    Examples:
        Drivers call this after building their provider-specific event handler.
    """
    accumulator = spec.accumulator
    usage = spec.usage or accumulator.to_usage
    try:
        try:
            process = spawn_agent_cli(
                spec.command,
                env=spec.env,
                cwd=cli_working_directory(ctx),
                stdin_text=spec.stdin_text,
            )
        except FileNotFoundError as exc:
            if spec.missing_binary is not None:
                return spec.missing_binary()
            return with_prompt(AgentResult(success=False, error=str(exc)), spec.prompt)

        with track_process_group(process):
            assert process.stdout is not None
            assert process.stderr is not None
            stderr_drain = start_stderr_drain(process.stderr)
            watchdog = watchdog_for_process(
                process,
                label=spec.label,
                interval_s=ctx.idle_timeout_s,
                accumulator=accumulator,
                stderr_text=stderr_drain.text,
                deadline_s=AgentRuntimeEnv().agent_timeout,
            )

            def watched_handler(acc: StreamSpanAccumulator, event: dict[str, Any]) -> None:
                watchdog.touch(
                    model_output=event_has_model_output(event), event_type=event_type_name(event)
                )
                spec.handler(acc, event)

            try:
                consume_stream(
                    raw_stream=process.stdout, accumulator=accumulator, handler=watched_handler
                )
                returncode = wait_or_kill_process_group(
                    process, timeout=AgentRuntimeEnv().agent_timeout
                )
            except subprocess.TimeoutExpired:
                return with_prompt(
                    AgentResult(
                        success=False,
                        error=f"{spec.label} CLI timed out",
                        metadata={"timeout": True, "retryable": True},
                        usage=usage(),
                    ),
                    spec.prompt,
                )
            except BaseException:
                # A parser exception must not strand a running child.
                if process.poll() is None:
                    kill_process_group(process.pid)
                    wait_or_kill_process_group(process, timeout=5)
                raise
            finally:
                watchdog.stop()
                stderr_drain.join(timeout=STDERR_DRAIN_JOIN_TIMEOUT_S)

        if watchdog.stalled:
            diagnostic = watchdog.diagnostic()
            return with_prompt(
                AgentResult(
                    success=False,
                    error=diagnostic.render(),
                    metadata=diagnostic.as_metadata(),
                    usage=usage(),
                ),
                spec.prompt,
            )
        return spec.classify(returncode, stderr_drain.text())
    finally:
        if spec.close_spans is not None:
            try:
                spec.close_spans()
            except Exception as exc:
                logger.debug("{} stream handler cleanup failed: {}", spec.label, exc)
