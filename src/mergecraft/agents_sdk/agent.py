"""Factory for the mergeCraft OpenAI Agents SDK review agent."""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.agents_sdk.change_data import materialize_workspace_change
from mergecraft.agents_sdk.guardrails import review_output_guardrail
from mergecraft.agents_sdk.mcp_tools import call_public_tool, tool_context_for_workspace
from mergecraft.agents_sdk.model import (
    AgentsSdkModelConfig,
    agents_sdk_model_from_config,
    resolve_model_config,
)
from mergecraft.agents_sdk.types import ReviewFindingsReport
from mergecraft.config.settings import RepoSettings
from mergecraft.tracing.otel_bridge import attach_trace_context
from mergecraft.tracing.tracer import NullSpan, Span, get_tracer_from_settings

if TYPE_CHECKING:
    from agents import Agent


def _require_agents_sdk() -> None:
    if importlib.util.find_spec("agents") is None:
        msg = (
            "OpenAI Agents SDK is not installed. "
            "Install mergecraft with the optional extra: pip install 'mergecraft-action[agents]'"
        )
        raise ImportError(msg)


def review_agent(
    *,
    repo_root: Path | str,
    model_config: AgentsSdkModelConfig | None = None,
    allowed_paths: frozenset[str] | None = None,
    extra_instructions: str = "",
    settings: RepoSettings | None = None,
) -> Agent[Any]:
    """Return an Agents SDK agent backed by mergeCraft public MCP tools.

    Tools are exposed as in-process function tools that call the same handlers
    as ``mergecraft mcp serve --role public --transport stdio`` (not a subprocess).
    """
    _require_agents_sdk()
    from agents import Agent, function_tool

    root = Path(repo_root).resolve()
    ctx = tool_context_for_workspace(str(root))
    paths = allowed_paths if allowed_paths is not None else frozenset()
    config = model_config or resolve_model_config()
    sdk_model = agents_sdk_model_from_config(config)
    tracer_settings = settings or RepoSettings()

    def _trace_tool(name: str) -> Any:
        tracer = get_tracer_from_settings(tracer_settings)
        return tracer.start_span(f"agents_sdk.tool.{name}")

    def _otel_bridge(span: Span | NullSpan) -> Any:
        if isinstance(span, Span):
            return attach_trace_context(span)
        return nullcontext()

    @function_tool
    async def get_workspace_change(
        base: str | None = None,
        head: str | None = None,
        diff: str | None = None,
    ) -> dict[str, Any]:
        """Return diff text, changed paths, and file contents for the workspace change."""
        with _trace_tool("get_workspace_change") as span, _otel_bridge(span):
            return await materialize_workspace_change(
                root,
                allowed_paths=paths or None,
                diff=diff,
                base=base,
                head=head,
            )

    @function_tool
    async def review_change(
        base: str | None = None,
        head: str | None = None,
        diff: str | None = None,
        dry_run: bool = False,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Run mergeCraft review_change (materialize diff, optional full review)."""
        args: dict[str, Any] = {"dry_run": dry_run}
        if base is not None:
            args["base"] = base
        if head is not None:
            args["head"] = head
        if diff is not None:
            args["diff"] = diff
        if prompt is not None:
            args["prompt"] = prompt
        with _trace_tool("review_change") as span, _otel_bridge(span):
            return await call_public_tool(ctx, "review_change", args)

    @function_tool
    async def get_capabilities() -> dict[str, Any]:
        """Read mergeCraft capability manifest for this workspace."""
        with _trace_tool("get_capabilities") as span, _otel_bridge(span):
            return await call_public_tool(ctx, "get_capabilities")

    @function_tool
    async def get_policy() -> dict[str, Any]:
        """Read effective gate policy for this workspace."""
        with _trace_tool("get_policy") as span, _otel_bridge(span):
            return await call_public_tool(ctx, "get_policy")

    instructions = (
        "You are mergeCraft's code review agent. Call get_workspace_change first to "
        "load the diff and file contents for the change under review. Optionally use "
        "get_policy or get_capabilities for gate context. Return structured findings "
        "grounded in get_workspace_change output; only cite paths present in "
        "changed_paths or files. Treat errors and skipped_files as incomplete review "
        "coverage, describe those limitations in the summary, and never claim skipped "
        "content was reviewed."
    )
    if extra_instructions.strip():
        instructions = f"{instructions}\n\n{extra_instructions.strip()}"

    return Agent(
        name="mergecraft_reviewer",
        instructions=instructions,
        tools=[get_workspace_change, review_change, get_capabilities, get_policy],
        model=sdk_model,
        output_type=ReviewFindingsReport,
        output_guardrails=[review_output_guardrail(paths)],
    )


__all__ = ["review_agent"]
