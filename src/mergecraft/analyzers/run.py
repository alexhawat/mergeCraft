"""Execute analyzer plans and capture outcomes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.analyzers.resolve import AnalyzerPlan

CHECK_TIMEOUT_S = 300
MAX_OUTPUT_CHARS = 8_000

CheckStatus = Literal["passed", "failed", "timed_out", "unavailable"]


@dataclass(frozen=True, slots=True)
class AnalyzerOutcome:
    """Result of running one analyzer or static gate."""

    name: str
    command: str
    status: CheckStatus
    output: str
    exit_code: int | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def ran(self) -> bool:
        return self.status != "unavailable"


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… truncated at {MAX_OUTPUT_CHARS} chars"


def _command_string(argv: tuple[str, ...]) -> str:
    import shlex

    return shlex.join(argv)


def run_plan(plan: AnalyzerPlan) -> AnalyzerOutcome:
    """Run one resolved plan. Never raises."""
    if plan.mode == "skip":
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="",
            status="unavailable",
            output=plan.reason or f"skipped {plan.manifest_id}",
        )

    if plan.mode in {"ci-result", "managed", "container"} and not plan.argv:
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="",
            status="unavailable",
            output=f"{plan.mode} execution is not available in this wave",
        )

    cwd = plan.cwd
    timeout_s = plan.timeout_s or CHECK_TIMEOUT_S
    command = _command_string(plan.argv)
    try:
        completed = subprocess.run(
            list(plan.argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=plan.env or None,
        )
    except subprocess.TimeoutExpired:
        logger.warning("analyzer {} timed out after {}s", plan.manifest_id, timeout_s)
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command=command,
            status="timed_out",
            output=f"timed out after {timeout_s}s",
        )
    except OSError as exc:
        logger.info("analyzer {} is unavailable: {}", plan.manifest_id, exc)
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command=command,
            status="unavailable",
            output=f"not installed in this environment: {exc}",
        )

    combined = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if plan.version_note:
        combined = f"{plan.version_note}\n{combined}".strip()
    return AnalyzerOutcome(
        name=plan.manifest_id,
        command=command,
        status="passed" if completed.returncode == 0 else "failed",
        output=_truncate(combined),
        exit_code=completed.returncode,
    )


def run_plans(plans: list[AnalyzerPlan]) -> list[AnalyzerOutcome]:
    return [run_plan(plan) for plan in plans]


__all__ = [
    "CHECK_TIMEOUT_S",
    "MAX_OUTPUT_CHARS",
    "AnalyzerOutcome",
    "CheckStatus",
    "run_plan",
    "run_plans",
]
