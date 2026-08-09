"""Thin action entry — delegates to ``mergecraft gha`` / ``main()``."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.main import MainResult


def main() -> None:
    """Action main entrypoint (Docker / CLI)."""
    from mergecraft.main import main as run_main

    try:
        result = asyncio.run(run_main())
    except Exception as error:
        logger.error("action failed: {}", error)
        sys.exit(1)
    if not result.success:
        logger.error("action failed: {}", result.error or "agent execution failed")
        sys.exit(1)
    _write_outputs(result)
    sys.exit(0)


def _write_outputs(result: MainResult) -> None:
    """Append this run's action outputs to ``GITHUB_OUTPUT``.

    ``evidence_packet`` is the operator's handle on the merge evidence
    packet (#47 / #96): a path under ``RUNNER_TEMP`` that a later
    ``actions/upload-artifact`` step can consume. It is omitted rather than
    emitted empty when the run produced no packet, so a workflow can gate on
    the output being set.
    """
    out_file = os.environ.get("GITHUB_OUTPUT")
    if not out_file:
        if result.evidence_packet_path:
            logger.info("merge evidence packet: {}", result.evidence_packet_path)
        return
    lines: list[str] = []
    if result.result:
        lines.append(f"result={result.result}\n")
    if result.evidence_packet_path:
        lines.append(f"evidence_packet={result.evidence_packet_path}\n")
        logger.info("merge evidence packet: {}", result.evidence_packet_path)
    if not lines:
        return
    with open(out_file, "a", encoding="utf-8") as fh:
        fh.writelines(lines)


if __name__ == "__main__":
    main()
