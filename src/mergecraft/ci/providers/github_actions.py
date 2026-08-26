"""GitHub Actions pipeline provider (K1.2)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.ci.archive_bounds import decode_log_archive
from mergecraft.ci.log_excerpt import analyze_log
from mergecraft.ci.truncate import DEFAULT_TRUNCATION_CAP, apply_truncation

if TYPE_CHECKING:
    from mergecraft.ci.types import ProviderContext, RawFailure
    from mergecraft.mcp.context import ToolContext
    from mergecraft.utils.github import GitHubClient


def unavailable_check_suite_logs(
    check_suite_id: int,
    *,
    message: str,
    skipped: bool = False,
) -> dict[str, Any]:
    """MCP skip/unavailable payload (unbound client or listing failure).

    Always includes ``available: False`` so clients do not treat an empty
    job list as a live suite with no failures.
    """
    return {
        "check_suite_id": check_suite_id,
        "message": message,
        "jobs": [],
        "available": False,
        "skipped": skipped,
    }


def unbound_check_suite_logs(check_suite_id: int) -> dict[str, Any]:
    """Payload when no GitHub client is bound — skip, do not invent a list."""
    return unavailable_check_suite_logs(
        check_suite_id,
        message="check-suite logs unavailable: GitHub client not bound",
        skipped=True,
    )


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
        client: GitHubClient,
        runs: list[dict[str, Any]],
        truncation_cap: int = DEFAULT_TRUNCATION_CAP,
    ) -> dict[str, Any]:
        """Download failed workflow logs for a check suite (legacy MCP contract).

        ``client`` and ``runs`` are required: the orchestrator lists check-suite
        runs once and passes them in. This method does not re-bind or re-list.
        """
        failed = [run for run in runs if run.get("conclusion") == "failure"]
        if not failed:
            # Trusted empty: no failed runs. Omit ``available`` so this does
            # not share the unbound/truncated/list-failure shape
            # (``unavailable_check_suite_logs`` always sets ``available: False``).
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
        return decode_log_archive(raw)


__all__ = [
    "GitHubActionsProvider",
    "unavailable_check_suite_logs",
    "unbound_check_suite_logs",
]
