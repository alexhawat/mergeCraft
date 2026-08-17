"""analyze_ci_failures MCP tool — clustered CI intelligence for review mode (K3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import ToolClass, execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def analyze_ci_failures_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.ci.intelligence import run_ci_intelligence

        check_suite_id = int(params["check_suite_id"])
        pr_diff_paths = [str(path) for path in (params.get("pr_diff_paths") or [])]
        base_branch_runs = list(params.get("base_branch_runs") or [])
        retry_attempts = dict(params.get("retry_attempts") or {})
        base_branch_status = params.get("base_branch_status")
        if base_branch_status is not None:
            base_branch_status = str(base_branch_status).strip() or None
        fix_suggestions = dict(params.get("fix_suggestions") or {})
        return await run_ci_intelligence(
            ctx,
            check_suite_id=check_suite_id,
            pr_diff_paths=pr_diff_paths or None,
            base_branch_runs=base_branch_runs or None,
            retry_attempts=retry_attempts or None,
            base_branch_status=base_branch_status,
            fix_suggestions=fix_suggestions or None,
        )

    return tool(
        name="analyze_ci_failures",
        tool_class=ToolClass.ANALYSIS,
        timeout_ms=600_000,
        description=(
            "Fetch failing CI workflow logs for a check suite, cluster root causes, classify "
            "flaky and blame verdicts, and return review-ready output: section (CI failures "
            "heading), preMergeSummary (CI pre-merge row), inline comments, and stats. Use this "
            "instead of manually clustering raw get_check_suite_logs output."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "check_suite_id": {
                    "type": "number",
                    "description": "Failed check suite id from the PR head commit status.",
                },
                "pr_diff_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repo-relative paths changed by the PR (for blame attribution).",
                },
                "base_branch_status": {
                    "type": "string",
                    "description": (
                        "Optional base-branch conclusion for the same fingerprint "
                        "(failure/success) when known."
                    ),
                },
                "base_branch_runs": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional recent base-branch runs keyed by failure fingerprint.",
                },
                "retry_attempts": {
                    "type": "object",
                    "description": (
                        "Optional retry attempts keyed by failure fingerprint. Fingerprints "
                        "come from a prior analyze_ci_failures response (clusters[].fingerprint) "
                        "or from normalizing fixture failures; omit when retry history is unknown."
                    ),
                },
                "fix_suggestions": {
                    "type": "object",
                    "description": (
                        "Optional one-click suggestion bodies keyed by failure fingerprint "
                        "for PR-attributed hunks."
                    ),
                },
            },
            "required": ["check_suite_id"],
            "additionalProperties": False,
        },
        execute=execute(_run, "analyze_ci_failures"),
    )


__all__ = ["analyze_ci_failures_tool"]
