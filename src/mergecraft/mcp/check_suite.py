"""get_check_suite_logs tool."""

from __future__ import annotations

import os
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.mcp.shared import execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

LogType = Literal["error", "warning", "failure", "trace"]


def _analyze_log(logs: str, excerpt_lines: int = 80) -> dict[str, Any]:
    clean = re.sub(r"\x1b\[[0-9;]*m", "", logs)
    lines = clean.split("\n")
    total = len(lines)
    index: list[dict[str, Any]] = []
    patterns: list[tuple[LogType, re.Pattern[str], re.Pattern[str] | None]] = [
        ("error", re.compile(r"##\[error\]", re.I), None),
        ("error", re.compile(r"\bError:", re.I), None),
        ("error", re.compile(r"\bERR_", re.I), None),
        ("error", re.compile(r"exit code [1-9]", re.I), None),
        ("warning", re.compile(r"##\[warning\]", re.I), None),
        ("warning", re.compile(r"\bWARN\b", re.I), re.compile(r"apt|dpkg|Reading package", re.I)),
        ("failure", re.compile(r"\d+ failed", re.I), None),
        ("failure", re.compile(r"FAIL\b", re.I), None),
        ("failure", re.compile(r"[✕✗×]"), None),
        ("trace", re.compile(r"^\s+at\s+", re.I), None),
    ]
    for i, line in enumerate(lines):
        for log_type, pattern, skip in patterns:
            if pattern.search(line):
                if skip and skip.search(line):
                    continue
                if log_type == "trace" and index and index[-1]["type"] == "trace":
                    continue
                truncated = line[:117] + "..." if len(line) > 120 else line
                index.append({"line": i + 1, "content": truncated.strip(), "type": log_type})
                break
    error_line = -1
    for i in range(len(lines) - 1, -1, -1):
        if re.search(r"##\[error\]", lines[i], re.I):
            error_line = i
            break
    if error_line == -1:
        start = max(0, total - excerpt_lines)
        end = total
    else:
        context_after = 5
        context_before = excerpt_lines - context_after
        start = max(0, error_line - context_before)
        end = min(total, error_line + context_after)
    return {
        "totalLines": total,
        "index": index,
        "excerpt": {
            "content": "\n".join(lines[start:end]),
            "startLine": start + 1,
            "endLine": end,
        },
    }


def get_check_suite_logs_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        check_suite_id = int(params["check_suite_id"])
        payload = await ctx.github.get(
            f"/repos/{ctx.repo.owner}/{ctx.repo.name}/actions/runs",
            params={"check_suite_id": check_suite_id, "per_page": 100},
        )
        runs = (
            payload.get("workflow_runs", [])
            if isinstance(payload, dict)
            else (payload if isinstance(payload, list) else [])
        )
        failed = [r for r in runs if r.get("conclusion") == "failure"]
        if not failed:
            return {
                "check_suite_id": check_suite_id,
                "message": "no failed workflow runs found for this check suite",
                "jobs": [],
            }
        temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        Path(temp).mkdir(parents=True, exist_ok=True)
        jobs_out: list[dict[str, Any]] = []
        for run in failed[:3]:
            run_id = run["id"]
            try:
                # Logs endpoint returns a zip redirect; use raw httpx via request.
                response = await ctx.github._client.get(
                    f"/repos/{ctx.repo.owner}/{ctx.repo.name}/actions/runs/{run_id}/logs",
                    headers={"Accept": "application/vnd.github+json"},
                    follow_redirects=True,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"log download failed: {response.status_code}")
                raw = response.content
            except Exception as err:
                logger.info("failed to download logs for run {}: {}", run_id, err)
                continue
            if not isinstance(raw, (bytes, bytearray)):
                continue
            log_text = ""
            try:
                with zipfile.ZipFile(BytesIO(raw)) as zf:
                    for name in zf.namelist():
                        if name.endswith(".txt"):
                            log_text += zf.read(name).decode("utf-8", errors="replace")
                            log_text += "\n"
            except zipfile.BadZipFile:
                log_text = bytes(raw).decode("utf-8", errors="replace")
            analysis = _analyze_log(log_text)
            full_path = str(Path(temp) / f"check-suite-{check_suite_id}-run-{run_id}.log")
            Path(full_path).write_text(log_text, encoding="utf-8")
            jobs_out.append(
                {
                    "job_id": run_id,
                    "job_name": run.get("name"),
                    "job_url": run.get("html_url"),
                    "log_index": analysis["index"],
                    "excerpt": {
                        "start_line": analysis["excerpt"]["startLine"],
                        "end_line": analysis["excerpt"]["endLine"],
                        "total_lines": analysis["totalLines"],
                        "content": analysis["excerpt"]["content"],
                    },
                    "full_log_path": full_path,
                }
            )
        return {"check_suite_id": check_suite_id, "jobs": jobs_out, "count": len(jobs_out)}

    return tool(
        name="get_check_suite_logs",
        description=(
            "Get workflow run logs for a failed check suite. Returns a log_index, "
            "excerpt, and full_log_path."
        ),
        input_schema={
            "type": "object",
            "properties": {"check_suite_id": {"type": "number"}},
            "required": ["check_suite_id"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_check_suite_logs"),
    )
