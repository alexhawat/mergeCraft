"""Public MCP product tools — six semantic tools over completed-review IR (D3 / D5).

Exports:
    PUBLIC_TOOL_NAMES: Closed frozenset of public tool names.
    build_public_tools: Build the dedicated public ``ToolSpec`` list.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.capabilities.manifest import capabilities_manifest
from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES
from mergecraft.mcp.shared import EMPTY_SCHEMA, JsonSchema, ToolClass, execute, tool
from mergecraft.offline_review import parse_offline_review_findings, run_offline_diff_review
from mergecraft.review.completed import (
    completed_review_exists,
    completed_review_payload,
    lookup_finding_packet_in_review,
    lookup_finding_row_in_review,
    persist_offline_review,
)
from mergecraft.review.explain import finding_explain_payload
from mergecraft.review.finding_lookup import is_safe_path_stem
from mergecraft.review.snapshot import canonical_review_snapshot
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.source_resolve import SourceResolverSpec, confine_path

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec

PUBLIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "review_change",
        "get_review",
        "inspect_finding",
        "explain_finding",
        "get_capabilities",
        "get_policy",
    }
)

_OBJECT_SCHEMA: JsonSchema = {"type": "object", "additionalProperties": False}


def _repo_root(ctx: ToolContext) -> Path:
    cwd = ctx.payload.cwd or ctx.tmpdir
    return Path(cwd).resolve()


def _validated_review_id(review_id: str) -> str | None:
    if is_safe_path_stem(review_id):
        return review_id
    return None


class _ParamRequiredError(ValueError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


def _resolve_outcome(*, success: bool, outcome: RunOutcome | None) -> str:
    if outcome is not None:
        return outcome.value
    return RunOutcome.passed.value if success else RunOutcome.failed.value


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _ParamRequiredError(field)
    return value.strip()


def _require_params(
    params: dict[str, Any],
    *fields: str,
) -> dict[str, Any]:
    """Validate required string params; return values or a single-field error dict."""
    values: dict[str, str] = {}
    for field in fields:
        try:
            values[field] = _require_nonempty_str(params.get(field), field)
        except _ParamRequiredError as exc:
            return {"error": f"{exc.field} is required"}
    return values


def review_change_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.offline_review import OfflineReviewResult
        from mergecraft.review.engine import ReviewEngine
        from mergecraft.tracing.review_context import resolve_review_id

        repo_root = _repo_root(ctx)
        # D4 — ``entry="cli"`` matches offline review snapshot shape for public MCP serve.
        snapshot = canonical_review_snapshot(entry="cli", source=str(repo_root))
        trace_session_id = resolve_review_id()
        review_id = _validated_review_id(trace_session_id)
        if review_id is None:
            return {"error": "invalid review_id"}

        diff_file = None
        raw_diff = params.get("diff")
        if raw_diff is not None:
            confined = confine_path(repo_root, str(raw_diff))
            if confined is None:
                return {"error": "diff path must be inside the workspace"}
            diff_file = confined

        trust_override = None
        if ctx.trust_tier in ("trusted", "untrusted"):
            trust_override = ctx.trust_tier

        source_spec = SourceResolverSpec(
            cwd=repo_root,
            invocation_root=repo_root,
            base=params.get("base"),
            head=params.get("head"),
        )
        engine: ReviewEngine[OfflineReviewResult] = ReviewEngine(snapshot=snapshot)
        result = await run_offline_diff_review(
            cwd=repo_root,
            base=params.get("base"),
            diff_file=diff_file,
            prompt_extra=params.get("prompt"),
            dry_run=bool(params.get("dry_run", False)),
            invocation_root=repo_root,
            source_spec=source_spec,
            engine=engine,
            trust_override=trust_override,
        )
        if not result.success:
            return {"error": result.error or "review_change failed"}

        findings = parse_offline_review_findings(result)
        finding_rows = persist_offline_review(
            review_id=review_id,
            trace_session_id=trace_session_id,
            snapshot=snapshot,
            repo_root=repo_root,
            model="(mcp-public)",
            prompt=params.get("prompt"),
            findings=findings,
            evidence_packet_path=result.evidence_packet_path,
        )
        outcome = _resolve_outcome(success=result.success, outcome=result.outcome)
        return {
            "review_id": review_id,
            "outcome": outcome,
            "findings": finding_rows,
            "summary": (
                f"Review {review_id} completed with {len(finding_rows)} finding(s)."
                if finding_rows
                else f"Review {review_id} completed with no findings."
            ),
        }

    return tool(
        name="review_change",
        tool_class=ToolClass.ANALYSIS,
        description=(
            "Run a read-only mergeCraft review on the workspace change and persist a "
            "durable review id. Do not use when you need to commit, push, or open a PR — "
            "use runtime reviewer tools instead."
        ),
        input_schema={
            **_OBJECT_SCHEMA,
            "properties": {
                "base": {
                    "type": "string",
                    "description": "Optional git base ref for the diff (defaults to HEAD).",
                },
                "head": {
                    "type": "string",
                    "description": "Optional git head ref when comparing two refs.",
                },
                "diff": {
                    "type": "string",
                    "description": "Optional path to a standalone patch file.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Materialize the diff and build the review prompt without "
                        "invoking an agent."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional extra instructions appended to the review prompt.",
                },
            },
        },
        execute=execute(_run, "review_change"),
    )


def get_review_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        required = _require_params(params, "review_id")
        if "error" in required:
            return required
        review_id = required["review_id"]
        payload = completed_review_payload(review_id, repo_root=_repo_root(ctx))
        if payload is None:
            return {"error": f"unknown review id {review_id!r}"}
        return payload

    return tool(
        name="get_review",
        tool_class=ToolClass.REVIEW_READ,
        description=(
            "Load a previously persisted review by id. Do not use before "
            "`review_change` has stored that review."
        ),
        input_schema={
            **_OBJECT_SCHEMA,
            "properties": {
                "review_id": {
                    "type": "string",
                    "description": "Stored review id returned by `review_change`.",
                },
            },
            "required": ["review_id"],
        },
        execute=execute(_run, "get_review"),
    )


def inspect_finding_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        required = _require_params(params, "finding_id", "review_id")
        if "error" in required:
            return required
        finding_id = required["finding_id"]
        review_id = required["review_id"]
        repo_root = _repo_root(ctx)
        if not completed_review_exists(review_id, repo_root=repo_root):
            return {"error": f"unknown review id {review_id!r}"}
        row = lookup_finding_row_in_review(review_id, finding_id, repo_root=repo_root)
        if row is None:
            return {"error": f"unknown finding id {finding_id!r}"}
        return {"finding_id": finding_id, "finding": row, "review_id": review_id}

    return tool(
        name="inspect_finding",
        tool_class=ToolClass.REVIEW_READ,
        description=(
            "Return structured metadata for one finding by MC- short id or fingerprint. "
            "Do not use without the review id that stored the finding."
        ),
        input_schema={
            **_OBJECT_SCHEMA,
            "properties": {
                "finding_id": {
                    "type": "string",
                    "description": "MC- short id or fingerprint for the finding.",
                },
                "review_id": {
                    "type": "string",
                    "description": "Stored review id that owns the finding.",
                },
            },
            "required": ["finding_id", "review_id"],
        },
        execute=execute(_run, "inspect_finding"),
    )


def explain_finding_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        required = _require_params(params, "finding_id", "review_id")
        if "error" in required:
            return required
        finding_id = required["finding_id"]
        review_id = required["review_id"]
        repo_root = _repo_root(ctx)
        if not completed_review_exists(review_id, repo_root=repo_root):
            return {"error": f"unknown review id {review_id!r}"}
        packet = lookup_finding_packet_in_review(
            review_id,
            finding_id,
            repo_root=repo_root,
        )
        if packet is None:
            return {"error": f"unknown finding id {finding_id!r}"}
        return finding_explain_payload(finding_id, packet, review_id=review_id)

    return tool(
        name="explain_finding",
        tool_class=ToolClass.REVIEW_READ,
        description=(
            "Explain one finding using the same payload shape as `mergecraft explain`. "
            "Do not use for whole-change summaries — call without a finding id on the CLI."
        ),
        input_schema={
            **_OBJECT_SCHEMA,
            "properties": {
                "finding_id": {
                    "type": "string",
                    "description": "MC- short id or fingerprint for the finding.",
                },
                "review_id": {
                    "type": "string",
                    "description": "Stored review id that owns the finding.",
                },
            },
            "required": ["finding_id", "review_id"],
        },
        execute=execute(_run, "explain_finding"),
    )


def get_capabilities_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(_params: dict[str, Any]) -> dict[str, Any]:
        manifest = capabilities_manifest()
        return {**manifest}

    return tool(
        name="get_capabilities",
        tool_class=ToolClass.REVIEW_READ,
        description=(
            "Return the review-only capability manifest (allowed vs forbidden actions). "
            "Do not use to mutate repository state — it is read-only metadata."
        ),
        input_schema=EMPTY_SCHEMA,
        execute=execute(_run, "get_capabilities"),
    )


def get_policy_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "trust_tier": ctx.trust_tier,
            "policy_rule_ids": list(DEFAULT_GATE_POLICIES),
            "policies": {
                rule_id: action.value for rule_id, action in DEFAULT_GATE_POLICIES.items()
            },
        }

    return tool(
        name="get_policy",
        tool_class=ToolClass.REVIEW_READ,
        description=(
            "Return the read-only gate policy for this serve context. "
            "Do not use to change trust tier or gate rules — there is no setter."
        ),
        input_schema=EMPTY_SCHEMA,
        execute=execute(_run, "get_policy"),
    )


def build_public_tools(ctx: ToolContext) -> list[ToolSpec]:
    """Build the six public product tools for ``/mcp/public`` (D3 / D5)."""
    return [
        review_change_tool(ctx),
        get_review_tool(ctx),
        inspect_finding_tool(ctx),
        explain_finding_tool(ctx),
        get_capabilities_tool(ctx),
        get_policy_tool(ctx),
    ]


__all__ = [
    "PUBLIC_TOOL_NAMES",
    "build_public_tools",
]
