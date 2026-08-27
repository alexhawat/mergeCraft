"""Dependency prep phase — detect and install Node/Python deps."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.prep.node import install_node_dependencies
from mergecraft.prep.python import install_python_dependencies
from mergecraft.prep.types import PrepOptions, PrepResult, is_prep_install_failure
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from collections.abc import Sequence

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


async def run_prep_phase(options: PrepOptions | None = None) -> list[PrepResult]:
    """Run all applicable prep steps sequentially.

    Individual step failures are recorded on :class:`PrepResult` (issues +
    ``dependencies_installed=False``) rather than raising — the live Action
    path maps a failed install to ``RunOutcome.inconclusive`` (W6.1 / D4).
    A policy skip (``skipped=True``, e.g. Python install with ``shell:
    disabled``) is not a failure. Callers that need fail-closed behaviour
    must inspect results via ``is_prep_install_failure`` (see
    ``main._prep_failure_reason`` / ``mcp.dependencies``).
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
            for step in _PREP_STEPS:
                should = step.should_run()
                if asyncio.iscoroutine(should):
                    should = await should
                if not should:
                    logger.debug("» skipping {} (not applicable)", step.name)
                    continue
                logger.debug("» running {}...", step.name)
                result = await step.run(opts)
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
        finally:
            try:
                await _restore_prep_dirtied_files(pre_dirty)
            except Exception as exc:
                logger.debug("» prep restore skipped: {}", exc)

    elapsed_ms = round((time.perf_counter() - start) * 1000)
    logger.debug("» prep phase completed ({}ms)", elapsed_ms)
    return results


__all__ = ["PrepOptions", "PrepResult", "is_prep_install_failure", "run_prep_phase"]
