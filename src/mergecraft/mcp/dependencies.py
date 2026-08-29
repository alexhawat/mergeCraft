"""Dependency installation tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import EMPTY_SCHEMA, ToolClass, execute, tool
from mergecraft.mcp.tool_state import DependencyInstallationState
from mergecraft.modes._api_only_scope import API_ONLY_SCOPE, API_ONLY_SCOPE_GUIDANCE
from mergecraft.prep import PrepOptions, PrepResult, is_prep_install_failure, run_prep_phase

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _format_prep_results(results: list[PrepResult], *, scope_notice: str | None = None) -> str:
    if not results:
        body = (
            "No supported language detected in this repository "
            "(checked for package.json, requirements.txt, pyproject.toml, etc.).\n\n"
            "Inspect the repository structure to determine how dependencies should be "
            "installed, then use shell to install them."
        )
    else:
        lines: list[str] = []
        for result in results:
            if result.language == "unknown":
                continue
            lang = "Node.js" if result.language == "node" else "Python"
            if result.dependencies_installed:
                lines.append(
                    f"{lang} dependencies installed successfully via {result.package_manager}."
                )
            elif result.skipped:
                reason = result.issues[0] if result.issues else "skipped by policy"
                lines.append(f"{lang} dependency installation skipped: {reason}")
            else:
                err = "\n".join(result.issues) if result.issues else "unknown error"
                lines.append(f"{lang} dependency installation failed.\n\nError:\n{err}")
        body = "\n\n".join(lines) if lines else _format_prep_results([], scope_notice=scope_notice)
    if scope_notice:
        return f"{scope_notice}\n\n{body}"
    return body


def _prep_scope_notice(ctx: ToolContext) -> str | None:
    if ctx.tool_state.review_scope == API_ONLY_SCOPE:
        return API_ONLY_SCOPE_GUIDANCE
    return None


def start_installation(ctx: ToolContext) -> None:
    if ctx.tool_state.dependency_installation is not None:
        return
    options = PrepOptions(
        ignore_scripts=ctx.trust_tier == "untrusted" or ctx.payload.shell == "disabled"
    )
    promise = asyncio.ensure_future(run_prep_phase(options))
    ctx.tool_state.dependency_installation = DependencyInstallationState(
        status="in_progress",
        promise=promise,
        results=None,
    )

    def _done(task: asyncio.Future[list[PrepResult]]) -> None:
        state = ctx.tool_state.dependency_installation
        if state is None:
            return
        try:
            results = task.result()
            # W6.1 — surface install failure on the state; ``main()`` maps
            # ``status="failed"`` to ``RunOutcome.inconclusive`` (not silent
            # continue). The MCP tools still return the formatted summary so
            # the agent can see the reason.
            has_failure = any(is_prep_install_failure(r) for r in results)
            state.status = "failed" if has_failure else "completed"
            state.results = results
        except Exception:
            state.status = "failed"

    promise.add_done_callback(_done)


def start_dependency_installation_tool(ctx: ToolContext):
    async def _run(_params: dict[str, Any]):
        state = ctx.tool_state.dependency_installation
        if state and state.status in {"completed", "failed"}:
            return {
                "status": state.status,
                "message": "Dependency installation already completed.",
                "summary": _format_prep_results(
                    state.results or [], scope_notice=_prep_scope_notice(ctx)
                ),
            }
        if state and state.status == "in_progress":
            return {
                "status": "in_progress",
                "message": (
                    "Dependency installation is already in progress. "
                    "Call await_dependency_installation when you need to use them."
                ),
            }
        start_installation(ctx)
        return {
            "status": "started",
            "message": (
                "Dependency installation started in background. Continue with other "
                "tasks and call await_dependency_installation when you need dependencies."
            ),
        }

    return tool(
        name="start_dependency_installation",
        tool_class=ToolClass.ANALYSIS,
        mutates=True,
        description=(
            "Start installing project dependencies in the background. Non-blocking and idempotent."
        ),
        input_schema=EMPTY_SCHEMA,
        execute=execute(_run, "start_dependency_installation"),
    )


def await_dependency_installation_tool(ctx: ToolContext):
    async def _run(_params: dict[str, Any]):
        if ctx.tool_state.dependency_installation is None:
            start_installation(ctx)
        state = ctx.tool_state.dependency_installation
        if state is None:
            msg = "failed to initialize dependency installation state"
            raise RuntimeError(msg)
        if state.status in {"completed", "failed"}:
            return {
                "status": state.status,
                "message": _format_prep_results(
                    state.results or [], scope_notice=_prep_scope_notice(ctx)
                ),
            }
        if state.promise is None:
            msg = "dependency installation state is corrupted - no promise found"
            raise RuntimeError(msg)
        results = await state.promise
        return {
            "status": state.status,
            "message": _format_prep_results(results, scope_notice=_prep_scope_notice(ctx)),
        }

    return tool(
        name="await_dependency_installation",
        tool_class=ToolClass.ANALYSIS,
        description=(
            "Wait for dependency installation to complete and get the results. "
            "Auto-starts if not yet started."
        ),
        input_schema=EMPTY_SCHEMA,
        execute=execute(_run, "await_dependency_installation"),
    )
