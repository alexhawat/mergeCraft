"""GitHub Actions pipeline provider (K1.2)."""

from __future__ import annotations

import os
import zipfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.ci.log_excerpt import analyze_log
from mergecraft.ci.truncate import DEFAULT_TRUNCATION_CAP, apply_truncation

if TYPE_CHECKING:
    from mergecraft.ci.types import ProviderContext, RawFailure
    from mergecraft.mcp.context import ToolContext


class GitHubActionsProvider:
    """GitHub Actions adapter wrapping the legacy check-suite log downloader."""

    supports_retry_state = True
    skip_reason = None

    def detect(self, context: ProviderContext) -> bool:
        return bool(context.get("github") or context.get("github_token"))

    def fetch_failures(self, pr: dict[str, object]) -> list[RawFailure]:
        _ = pr
        return []

    async def fetch_check_suite_logs(
        self,
        ctx: ToolContext,
        *,
        check_suite_id: int,
        truncation_cap: int = DEFAULT_TRUNCATION_CAP,
    ) -> dict[str, Any]:
        """Download failed workflow logs for a check suite (legacy MCP contract)."""
        payload = await ctx.github.get(
            f"/repos/{ctx.repo.owner}/{ctx.repo.name}/actions/runs",
            params={"check_suite_id": check_suite_id, "per_page": 100},
        )
        runs = (
            payload.get("workflow_runs", [])
            if isinstance(payload, dict)
            else (payload if isinstance(payload, list) else [])
        )
        failed = [run for run in runs if run.get("conclusion") == "failure"]
        if not failed:
            return {
                "check_suite_id": check_suite_id,
                "message": "no failed workflow runs found for this check suite",
                "jobs": [],
            }

        temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        Path(temp).mkdir(parents=True, exist_ok=True)
        jobs_out: list[dict[str, Any]] = []
        selected, _overflow = apply_truncation(failed, cap=truncation_cap)
        for run in selected:
            run_id = run["id"]
            try:
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

            log_text = self._decode_log_archive(raw)
            analysis = analyze_log(log_text)
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

    @staticmethod
    def _decode_log_archive(raw: bytes | bytearray) -> str:
        log_text = ""
        try:
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                for name in zf.namelist():
                    if name.endswith(".txt"):
                        log_text += zf.read(name).decode("utf-8", errors="replace")
                        log_text += "\n"
        except zipfile.BadZipFile:
            log_text = bytes(raw).decode("utf-8", errors="replace")
        return log_text


__all__ = ["GitHubActionsProvider"]
