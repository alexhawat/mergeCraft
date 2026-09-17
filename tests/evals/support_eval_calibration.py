"""Shared pins for plan 25 (evals & calibration) E2 / E4 tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

STRUCTURAL_BASELINE: Final[str] = "evals/results/latest.json"
EVAL_GATE_JOB_ID: Final[str] = "eval-gate"
PROVIDER_PATHS: Final[frozenset[str]] = frozenset(
    {"claude", "codex", "cursor", "gemini", "opencode", "jev"}
)
PROVIDER_SECRET_ENV: Final[frozenset[str]] = frozenset(
    {
        "NOUS_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "TYPESAFE_API_KEY",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    }
)
FAITHFULNESS_SIGNAL_NAMES: Final[tuple[str, ...]] = (
    "unverified_finding_rate",
    "contradicts_rate",
    "quote_verification_failures",
)


def structural_baseline_path() -> Path:
    return REPO_ROOT / STRUCTURAL_BASELINE


def ci_eval_gate_job() -> dict[str, Any]:
    return job(load_workflow("ci.yml"), EVAL_GATE_JOB_ID)


def job_script_text(gate: dict[str, Any]) -> str:
    parts: list[str] = []
    name = gate.get("name")
    if isinstance(name, str):
        parts.append(name)
    for step in gate.get("steps") or []:
        if not isinstance(step, dict):
            continue
        step_name = step.get("name")
        if isinstance(step_name, str):
            parts.append(step_name)
        run = step.get("run")
        if isinstance(run, str):
            parts.append(run)
    return "\n".join(parts)


def ci_eval_gate_source() -> str:
    lines = read_text(".github/workflows/ci.yml").splitlines(keepends=True)
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        if line.startswith(f"  {EVAL_GATE_JOB_ID}:"):
            start = index
            continue
        if start is None:
            continue
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            key = line.strip().rstrip(":")
            if key and " " not in key and not key.startswith("#"):
                end = index
                break
    if start is None:
        return ""
    return "".join(lines[start:end])


__all__ = [
    "EVAL_GATE_JOB_ID",
    "FAITHFULNESS_SIGNAL_NAMES",
    "PROVIDER_PATHS",
    "PROVIDER_SECRET_ENV",
    "STRUCTURAL_BASELINE",
    "ci_eval_gate_job",
    "ci_eval_gate_source",
    "job_script_text",
    "structural_baseline_path",
]
