"""Shared formatting and JSON I/O helpers for ``mergecraft eval``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.cli.errors import cli_bail
from mergecraft.evals import PERMANENT_TEST_DIR_NAME

if TYPE_CHECKING:
    from mergecraft.evals.store import Case, ReplayDiff


def default_permanent_dir() -> Path:
    """Return the default permanent-test target directory."""
    return Path("tests") / "evals" / PERMANENT_TEST_DIR_NAME


def case_to_json(case: Case) -> dict[str, Any]:
    """Return the JSON-safe dict representation of a case."""
    return case.model_dump(mode="json")


def format_human(case: Case) -> str:
    """Render a case as a one-line human-readable summary."""
    pr_part = f" pr=#{case.pr_number}" if case.pr_number is not None else ""
    return (
        f"- {case.id} [{case.category}] {case.title} "
        f"(submitted={case.submitted_at.isoformat()}{pr_part}, "
        f"expected={case.expected_decision})"
    )


def format_diff_human(diff: ReplayDiff) -> str:
    """Render a :class:`ReplayDiff` as a human-readable text block."""
    lines = [
        f"case: {diff.case_id}",
        f"expected: {diff.expected_decision}",
        f"current:  {diff.current_decision or '(unavailable)'}",
        f"status:   {diff.status}",
    ]
    if diff.notes:
        lines.append(f"notes:    {diff.notes}")
    return "\n".join(lines)


def format_diff_json(diff: ReplayDiff) -> dict[str, Any]:
    """Return a JSON-safe replay diff payload."""
    return diff.model_dump(mode="json")


def read_json_or_jsonl(path: Path) -> Any:
    """Decode a corpus file that may be JSON or JSON Lines."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        rows = [
            json.loads(line)
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("//")
        ]
        if not rows:
            raise
        return rows


def replay_inputs_from_packet(path: Path) -> tuple[list[dict[str, Any]], bool, str]:
    """Extract ``decide_approval()`` inputs from a merge evidence packet."""
    if not path.is_file():
        cli_bail(f"{path} is not a file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        cli_bail(f"could not read packet {path}: {exc}")
    if not isinstance(payload, dict):
        cli_bail(f"{path}: expected a merge evidence packet object")
    rows = payload.get("findings")
    if not isinstance(rows, list):
        cli_bail(f"{path}: packet has no 'findings' array")
    findings = [row for row in rows if isinstance(row, dict)]
    run = payload.get("run")
    run_succeeded = True
    if isinstance(run, dict) and isinstance(run.get("succeeded"), bool):
        run_succeeded = bool(run["succeeded"])
    tier = "trusted"
    for holder in (payload, run if isinstance(run, dict) else {}):
        value = holder.get("trust_tier") if isinstance(holder, dict) else None
        if value in {"trusted", "untrusted"}:
            tier = str(value)
            break
    return findings, run_succeeded, tier


__all__ = [
    "case_to_json",
    "default_permanent_dir",
    "format_diff_human",
    "format_diff_json",
    "format_human",
    "read_json_or_jsonl",
    "replay_inputs_from_packet",
]
