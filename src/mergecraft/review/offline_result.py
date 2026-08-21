"""Offline review result type and packet/failure helpers (leaf of ``offline_review``).

Exports:
    OfflineReviewResult: Outcome of a local CLI review run.
    _emit_offline_packet: Write the evidence packet after an agent attempt.
    _offline_error_outcome: Map an exception onto a ``RunOutcome``.
    _offline_failure: Build a failed ``OfflineReviewResult``.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.analyzers.finding import Finding, parse_findings_payload
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext
    from mergecraft.utils.offline_diff import DiffMaterialization


@dataclass(slots=True)
class OfflineReviewResult:
    success: bool
    output: str | None = None
    error: str | None = None
    diff_path: str | None = None
    empty_diff: bool = False
    structured_output: str | None = None
    # On-disk path of the run's merge evidence packet (#47 / #96), or None
    # when no packet was produced (dry run, empty diff, emission failure).
    evidence_packet_path: str | None = None
    outcome: RunOutcome | None = None
    scope_reduction: object | None = None


def _offline_failure(
    *,
    error: str,
    outcome: RunOutcome,
    diff_path: str | None = None,
    evidence_packet_path: str | None = None,
    output: str | None = None,
    structured_output: str | None = None,
) -> OfflineReviewResult:
    return OfflineReviewResult(
        success=False,
        error=error,
        output=output,
        structured_output=structured_output,
        diff_path=diff_path,
        evidence_packet_path=evidence_packet_path,
        outcome=outcome,
    )


def _offline_error_outcome(exc: BaseException) -> RunOutcome:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, subprocess.TimeoutExpired)):
        return RunOutcome.timed_out
    if isinstance(exc, ValueError):
        return RunOutcome.configuration_error
    return RunOutcome.infra_error


def _offline_change_id(cwd: Path, materialization: DiffMaterialization) -> str:
    """Return the ``change_id`` an offline review attests to.

    There is no pull request, so the packet addresses the local working tree
    and the base it was diffed against — enough for a human to reconstruct
    what was reviewed.
    """
    base = materialization.base_ref or "patch"
    return f"local/{cwd.name}@{base}"


def _emit_offline_packet(
    tool_context: ToolContext,
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    run_succeeded: bool,
    structured_output: str | None,
    output_path: Path | None,
) -> str | None:
    """Emit the evidence packet for an offline review (#96).

    The offline path holds the agent's findings in typed form (its
    ``set_output`` payload), so they are merged into the packet on top of the
    analyzer findings. A malformed payload is skipped rather than fatal — the
    caller reports that error separately, and a packet with analyzer evidence
    only still beats no packet.
    """
    from mergecraft.evidence.run_packet import emit_run_packet

    extra: list[Finding] = []
    if structured_output:
        try:
            # ``parse_findings_payload`` validates and then dumps back to dicts;
            # the packet dedupes on ``Finding.fingerprint``, so re-type them.
            extra = [
                Finding.model_validate(row) for row in parse_findings_payload(structured_output)
            ]
        except ValueError as exc:
            logger.debug("offline evidence packet: unparsable structured output — {}", exc)

    written = emit_run_packet(
        tool_context,
        run_succeeded=run_succeeded,
        change_id=_offline_change_id(cwd, materialization),
        extra_findings=extra,
        output_path=output_path,
    )
    from mergecraft.evidence.run_manifest import build_run_manifest

    manifest = build_run_manifest(
        cwd=cwd,
        model=tool_context.resolved_model or tool_context.tool_state.model or "(unresolved)",
        agent_id=tool_context.agent_id,
        prompt_text=materialization.path.read_text(encoding="utf-8"),
    )
    logger.info("» run manifest fingerprints: {}", manifest)
    return str(written) if written else None
