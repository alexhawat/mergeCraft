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
from mergecraft.scm.github import github_client_from_scm

if TYPE_CHECKING:
    from mergecraft.ci.types import ProviderContext, RawFailure
    from mergecraft.mcp.context import ToolContext
    from mergecraft.utils.github import GitHubClient


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
        client: GitHubClient | None = None,
        runs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Download failed workflow logs for a check suite (legacy MCP contract)."""
        if client is None:
            client = github_client_from_scm(ctx.scm)
        if client is None:
            return {
                "check_suite_id": check_suite_id,
                "message": "check-suite logs unavailable: GitHub client not bound",
                "jobs": [],
                "skipped": True,
            }
        if runs is None:
            runs = await client.list_workflow_runs_for_check_suite(
                ctx.repo.owner, ctx.repo.name, check_suite_id
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
        selected, overflow = apply_truncation(failed, cap=truncation_cap)
        for run in selected:
            run_id = run.get("id")
            if not isinstance(run_id, int):
                continue
            try:
                raw = await client.download_workflow_run_logs(
                    ctx.repo.owner,
                    ctx.repo.name,
                    run_id,
                )
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
        return {
            "check_suite_id": check_suite_id,
            "jobs": jobs_out,
            "count": len(jobs_out),
            "total_failed_runs": len(failed),
            "overflow": overflow,
        }

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
