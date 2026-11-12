"""Dependency prep phase — detect and install Node/Python deps."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.prep.node import install_node_dependencies
from mergecraft.prep.python import install_python_dependencies
from mergecraft.prep.types import (
    DEFAULT_PREP_TIMEOUT_S,
    PrepOptions,
    PrepResult,
    is_prep_install_failure,
)
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from mergecraft.prep.types import PrepDefinition

_PREP_STEPS: Sequence[PrepDefinition] = (
    install_node_dependencies,
    install_python_dependencies,
)


async def _dirty_tracked_paths() -> set[str]:
    proc = await asyncio.create_subprocess_exec(
        *git_argv(["diff", "--name-only", "HEAD"]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = (
            f"git diff --name-only HEAD failed "
            f"(exit {proc.returncode}): {(stderr or b'').decode().strip() or '(no stderr)'}"
        )
        raise RuntimeError(msg)
    return {line for line in stdout.decode().splitlines() if line}


async def _restore_prep_dirtied_files(pre_dirty: set[str]) -> None:
    dirtied = [path for path in await _dirty_tracked_paths() if path not in pre_dirty]
    if not dirtied:
        return
    proc = await asyncio.create_subprocess_exec(
        *git_argv(["restore", "--staged", "--worktree", "--", *dirtied]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            "» failed to restore {} tracked file(s) modified by prep: {}",
            len(dirtied),
            (stderr or b"").decode().strip() or "(no stderr)",
        )
        return
    logger.info(
        "» restored {} tracked file(s) modified by prep: {}",
        len(dirtied),
        ", ".join(dirtied),
    )


async def _log_prep_dirtied_files(pre_dirty: set[str]) -> None:
    """Name tracked files that changed during prep without touching them.

    The agent shares the checkout while prep runs, so a changed file may be its
    edit; restoring it would silently revert that work.
    """
    dirtied = sorted(path for path in await _dirty_tracked_paths() if path not in pre_dirty)
    if dirtied:
        logger.info(
            "» {} tracked file(s) changed while prep ran; left as they are because the "
            "agent shares this checkout: {}",
            len(dirtied),
            ", ".join(dirtied),
        )


def _timed_out_result(step: PrepDefinition, timeout_s: float) -> PrepResult:
    return PrepResult(
        language=getattr(step, "language", "unknown"),
        dependencies_installed=False,
        issues=[
            f"dependency installation timed out after {timeout_s:g}s ({step.name}); "
            "its processes were stopped"
        ],
    )


async def _run_steps(opts: PrepOptions, results: list[PrepResult]) -> None:
    budget = opts.timeout_s if opts.timeout_s is not None and opts.timeout_s > 0 else None
    started = time.monotonic()
    for step in _PREP_STEPS:
        should = step.should_run()
        if asyncio.iscoroutine(should):
            should = await should
        if not should:
            logger.debug("» skipping {} (not applicable)", step.name)
            continue
        logger.debug("» running {}...", step.name)
        if budget is None:
            result = await step.run(opts)
        else:
            remaining = budget - (time.monotonic() - started)
            timed_out = remaining <= 0
            if not timed_out:
                try:
                    result = await asyncio.wait_for(step.run(opts), timeout=remaining)
                except TimeoutError:
                    timed_out = True
            if timed_out:
                result = _timed_out_result(step, budget)
                results.append(result)
                logger.warning("» {}: {}", step.name, result.issues[0])
                return
        results.append(result)
        if result.dependencies_installed:
            logger.debug("» {}: dependencies installed", step.name)
        elif result.skipped:
            logger.info(
                "» {}: {}",
                step.name,
                result.issues[0] if result.issues else "skipped",
            )
        elif result.issues:
            logger.warning("» {}: {}", step.name, result.issues[0])


async def run_prep_phase(options: PrepOptions | None = None) -> list[PrepResult]:
    """Run all applicable prep steps sequentially, within ``options.timeout_s``.

    Individual step failures are recorded on :class:`PrepResult` (issues +
    ``dependencies_installed=False``) rather than raising — the live Action
    path maps a failed install to ``RunOutcome.inconclusive`` (W6.1 / D4).
    A step still running at the phase deadline is cancelled (its process
    group is killed) and recorded as a failed install; later steps do not run.
    A policy skip (``skipped=True``, e.g. Python install with ``shell:
    disabled``) is not a failure. Callers that need fail-closed behaviour
    must inspect results via ``is_prep_install_failure`` (see
    ``main._prep_failure_reason`` / ``mcp.dependencies``).

    With ``options.agent_owned_tree`` the tracked files that changed while
    prep ran are logged, never restored (the agent may have edited them).
    """
    opts = options or PrepOptions()
    logger.debug("» starting prep phase...")
    start = time.perf_counter()
    results: list[PrepResult] = []

    from mergecraft.config.settings import RepoSettings
    from mergecraft.tracing.tracer import get_tracer_from_settings

    tracer = get_tracer_from_settings(RepoSettings())
    with tracer.start_span("mergecraft.prep") as _prep_span:
        try:
            pre_dirty = await _dirty_tracked_paths()
        except Exception as exc:
            logger.debug("» prep dirty snapshot skipped: {}", exc)
            pre_dirty = set()

        try:
            await _run_steps(opts, results)
        finally:
            try:
                if opts.agent_owned_tree:
                    await _log_prep_dirtied_files(pre_dirty)
                else:
                    await _restore_prep_dirtied_files(pre_dirty)
            except Exception as exc:
                logger.debug("» prep restore skipped: {}", exc)

    elapsed_ms = round((time.perf_counter() - start) * 1000)
    logger.debug("» prep phase completed ({}ms)", elapsed_ms)
    return results


class PrepRun:
    """A prep phase running as a task on the loop that started it.

    The task belongs to its owner loop, but the run awaits it from more than
    one: the orchestrator's main loop starts it, and the MCP server, which runs
    on its own loop in a daemon thread, serves ``await_dependency_installation``.
    Awaiting a foreign loop's task directly raises, so :meth:`wait` bridges the
    wait onto the owner loop with a thread-safe future. Waiters are shielded: a
    waiter that is cancelled or times out never cancels the install itself;
    only :meth:`cancel` does.
    """

    __slots__ = ("_loop", "_task")

    def __init__(self, task: asyncio.Future[list[PrepResult]]) -> None:
        self._task = task
        self._loop = task.get_loop()

    @property
    def task(self) -> asyncio.Future[list[PrepResult]]:
        return self._task

    def done(self) -> bool:
        return self._task.done()

    async def wait(self) -> list[PrepResult]:
        """Return the prep results, waiting from whichever loop is running.

        Raises ``RuntimeError`` when the install was stopped (:meth:`cancel`);
        a ``CancelledError`` from here always means the waiter itself was
        cancelled.
        """
        try:
            return await self._wait()
        except asyncio.CancelledError:
            if self._task.cancelled():
                msg = "dependency installation was stopped before it finished"
                raise RuntimeError(msg) from None
            raise

    async def _wait(self) -> list[PrepResult]:
        if self._task.done():
            return self._task.result()
        if asyncio.get_running_loop() is self._loop:
            return await asyncio.shield(self._task)
        if self._loop.is_closed():
            msg = "dependency installation's event loop is closed"
            raise RuntimeError(msg)

        async def _on_owner_loop() -> list[PrepResult]:
            return await asyncio.shield(self._task)

        bridged = asyncio.run_coroutine_threadsafe(_on_owner_loop(), self._loop)
        return await asyncio.wrap_future(bridged)

    def cancel(self) -> None:
        """Stop the install from any thread; its process groups are killed."""
        if self._task.done() or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._task.cancel)

    def __await__(self) -> Generator[Any, None, list[PrepResult]]:
        return self.wait().__await__()


__all__ = [
    "DEFAULT_PREP_TIMEOUT_S",
    "PrepOptions",
    "PrepResult",
    "PrepRun",
    "is_prep_install_failure",
    "run_prep_phase",
]
