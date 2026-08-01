"""Execute analyzer plans and capture outcomes."""

from __future__ import annotations

import contextlib
import resource
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.redact import redact_analyzer_output

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.sandbox import SandboxContext

CHECK_TIMEOUT_S = 300
MAX_OUTPUT_CHARS = 8_000

CheckStatus = Literal["passed", "failed", "timed_out", "unavailable", "declared-but-cannot-run"]


@dataclass(frozen=True, slots=True)
class AnalyzerOutcome:
    """Result of running one analyzer or static gate."""

    name: str
    command: str
    status: CheckStatus
    output: str
    exit_code: int | None = None
    output_path: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def ran(self) -> bool:
        return self.status not in {"unavailable", "declared-but-cannot-run"}


def _run_tmpdir(plan: AnalyzerPlan) -> Path:
    from pathlib import Path

    base = plan.cwd or Path.cwd()
    tmpdir = base / ".mergecraft" / "analyzer-runs"
    tmpdir.mkdir(parents=True, exist_ok=True)
    return tmpdir


def _persist_output(raw: str, *, plan: AnalyzerPlan) -> str | None:
    if not raw:
        return None
    from mergecraft.analyzers.parse import persist_analyzer_output

    redacted = redact_analyzer_output(raw, tool_id=plan.manifest_id)
    path = persist_analyzer_output(redacted, tmpdir=_run_tmpdir(plan), tool_id=plan.manifest_id)
    return str(path)


def _sandbox_preexec(context: SandboxContext) -> None:
    if sys.platform == "win32":
        return
    with contextlib.suppress(OSError):
        resource.setrlimit(
            resource.RLIMIT_NPROC,
            (context.max_processes, context.max_processes),
        )
    if context.memory_mb > 0:
        with contextlib.suppress(OSError):
            byte_limit = context.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (byte_limit, byte_limit))


def _truncate(text: str, *, output_path: str | None = None) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    if output_path:
        elided = len(text) - MAX_OUTPUT_CHARS
        return (
            f"... [{elided} chars truncated; full output saved to {output_path}] ...\n"
            f"{text[-MAX_OUTPUT_CHARS:]}"
        )
    return text[:MAX_OUTPUT_CHARS] + f"\n… truncated at {MAX_OUTPUT_CHARS} chars"


def _command_string(argv: tuple[str, ...]) -> str:
    import shlex

    return shlex.join(argv)


def run_plan(
    plan: AnalyzerPlan, *, sandbox_context: SandboxContext | None = None
) -> AnalyzerOutcome:
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
    if sandbox_context is not None:
        timeout_s = min(timeout_s, sandbox_context.timeout_s)
    command = _command_string(plan.argv)
    preexec_fn = None
    run_argv = list(plan.argv)
    if sandbox_context is not None and sandbox_context.read_only_source and sys.platform != "win32":
        preexec_fn = lambda: _sandbox_preexec(sandbox_context)  # noqa: E731
        from mergecraft.mcp.shell import detect_sandbox_method

        method = detect_sandbox_method()
        if method == "unshare":
            run_argv = ["unshare", "--pid", "--fork", "--mount-proc", *plan.argv]
        elif method == "sudo-unshare":
            run_argv = ["sudo", "unshare", "--pid", "--fork", "--mount-proc", *plan.argv]
    try:
        completed = subprocess.run(
            run_argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=plan.env or None,
            preexec_fn=preexec_fn,
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

    raw_stdout = (completed.stdout or "").strip()
    raw_stderr = (completed.stderr or "").strip()
    raw_for_parser = raw_stdout or raw_stderr
    combined = raw_for_parser
    if raw_stderr and raw_stdout:
        combined = f"{raw_stdout}\n{raw_stderr}".strip()
    elif raw_stderr:
        combined = raw_stderr
    if plan.version_note:
        combined = f"{plan.version_note}\n{combined}".strip()
    redacted = redact_analyzer_output(combined, tool_id=plan.manifest_id)
    persist_source = raw_for_parser or combined
    output_path = _persist_output(persist_source, plan=plan)
    return AnalyzerOutcome(
        name=plan.manifest_id,
        command=command,
        status="passed" if completed.returncode == 0 else "failed",
        output=_truncate(redacted, output_path=output_path),
        exit_code=completed.returncode,
        output_path=output_path,
    )


def run_plans(
    plans: list[AnalyzerPlan],
    *,
    sandbox_context: SandboxContext | None = None,
) -> list[AnalyzerOutcome]:
    return [run_plan(plan, sandbox_context=sandbox_context) for plan in plans]


__all__ = [
    "CHECK_TIMEOUT_S",
    "MAX_OUTPUT_CHARS",
    "AnalyzerOutcome",
    "CheckStatus",
    "run_plan",
    "run_plans",
]
