"""MCP tool primitives: ToolSpec, mutates flag, tool() helper."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Literal

from loguru import logger

JsonSchema = dict[str, Any]
# Tool bodies vary across modules; wrap loosely then normalize in ``execute``.
ToolBody = Callable[..., Awaitable[Any]]
ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any]]


class ToolClass(StrEnum):
    """D14 — ten closed values; role toolsets derive from class filters."""

    SCOPE = "scope"
    REPOSITORY_READ = "repository-read"
    ANALYSIS = "analysis"
    VERIFICATION = "verification"
    REVIEW_READ = "review-read"
    REVIEW_WRITE = "review-write"
    GITHUB_MUTATION = "github-mutation"
    REPOSITORY_MUTATION = "repository-mutation"
    SHELL = "shell"
    TERMINAL_PROTOCOL = "terminal-protocol"


REVIEWER_ALLOWED_TOOL_CLASSES: Final[frozenset[ToolClass]] = frozenset(
    {
        ToolClass.SCOPE,
        ToolClass.REPOSITORY_READ,
        ToolClass.ANALYSIS,
        ToolClass.REVIEW_READ,
    }
)
# Primary reviewer adds:
#   - REVIEW_WRITE   so ``create_pull_request_review`` / ``report_progress`` /
#                    ``record_finding_verdict`` can be admitted on /mcp/reviewer (D9 / C6).
#   - TERMINAL_PROTOCOL so ``submit_review_verdict`` (playbook step 10, C6) is
#                    admitted. mutates=False so no mutating-allowlist entry is needed.
#   - VERIFICATION   so ``verify_agent_findings`` (playbook step 8, C6) is admitted.
#                    mutates=False so no mutating-allowlist entry is needed.
# Subagents use REVIEWER_ALLOWED_TOOL_CLASSES (without these additions) so they
# remain denied publication and cannot call orchestrator-only tools.
PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES: Final[frozenset[ToolClass]] = (
    REVIEWER_ALLOWED_TOOL_CLASSES
    | frozenset(
        {
            ToolClass.REVIEW_WRITE,
            ToolClass.TERMINAL_PROTOCOL,
            ToolClass.VERIFICATION,
        }
    )
)
VERIFIER_ALLOWED_TOOL_CLASSES: Final[frozenset[ToolClass]] = frozenset(
    {
        ToolClass.REPOSITORY_READ,
        ToolClass.ANALYSIS,
        ToolClass.VERIFICATION,
    }
)
# ``checkout_pr`` is SCOPE + mutates=True but must stay on the reviewer surface
# (HA4.2 / D14). Every other mutating tool is orchestrator-only even when its
# class is otherwise allowed on a read-only role.
READONLY_MUTATING_ALLOWLIST: Final[frozenset[str]] = frozenset({"checkout_pr"})
# Primary reviewer additionally allows review publication (D9) and the three
# session tools the primary must be able to call:
#   - ``set_output``      (ANALYSIS, mutates=True) — Action output_schema + offline --json
#   - ``select_mode``     (SCOPE, mutates=True)    — default procedure Step 1
#   - ``report_progress`` (REVIEW_WRITE, mutates=True) — no-action path
# Subagents still use READONLY_MUTATING_ALLOWLIST so they cannot publish reviews
# or emit structured output.
PRIMARY_MUTATING_ALLOWLIST: Final[frozenset[str]] = READONLY_MUTATING_ALLOWLIST | frozenset(
    {
        "create_pull_request_review",
        "set_output",
        "select_mode",
        "report_progress",
        # C6: primary must persist verifier verdicts (REVIEW_WRITE + mutates).
        # Subagents keep READONLY_MUTATING_ALLOWLIST so they remain denied this write.
        "record_finding_verdict",
    }
)
# Session tools that must run in review-only (including before select_mode).
# Every other mutates=True tool is default-denied unless a write-capable mode
# is selected (none are registered in production).
_REVIEW_SESSION_MUTATIONS: Final[frozenset[str]] = PRIMARY_MUTATING_ALLOWLIST

_selected_mode_var: ContextVar[str | None] = ContextVar(
    "mergecraft_mcp_selected_mode", default=None
)


def bind_selected_mode(mode: str | None) -> Token[str | None]:
    """Bind the run's selected mode for mutating-tool gates (MCP request scope)."""
    return _selected_mode_var.set(mode)


def reset_selected_mode(token: Token[str | None]) -> None:
    """Restore the selected-mode binding from :func:`bind_selected_mode`."""
    _selected_mode_var.reset(token)


def guard_mutating_tool(tool_name: str, *, selected_mode: str | None = None) -> None:
    """Refuse tree/repo mutations unless a write-capable mode is selected."""
    if tool_name in _REVIEW_SESSION_MUTATIONS:
        return
    from mergecraft.modes import refuse_review_only_mutation

    mode = selected_mode if selected_mode is not None else _selected_mode_var.get()
    refuse_review_only_mutation(mode, action=tool_name)


def repository_mutation_class_for_push(
    push: Literal["disabled", "restricted", "enabled"],
) -> ToolClass:
    """Classify push/commit tools: ``repository-mutation`` only when push is enabled."""
    if push == "enabled":
        return ToolClass.REPOSITORY_MUTATION
    return ToolClass.GITHUB_MUTATION


@dataclass(slots=True)
class ToolResult:
    content: list[dict[str, str]]
    is_error: bool = False


@dataclass(slots=True)
class ToolSpec:
    """A mergeCraft MCP tool definition.

    ``mutates`` marks a named state-changing tool. Read-only role filters
    intersect class membership with this flag: mutating tools stay off
    reviewer/verifier unless the name is in ``READONLY_MUTATING_ALLOWLIST``.
    """

    name: str
    description: str
    input_schema: JsonSchema
    execute: ToolHandler
    tool_class: ToolClass
    mutates: bool = False
    annotations: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int | None = None

    def list_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.annotations:
            entry["annotations"] = self.annotations
        return entry


def admits_readonly_role(
    spec: ToolSpec,
    allowed: frozenset[ToolClass],
    *,
    mutating_allowlist: frozenset[str] = READONLY_MUTATING_ALLOWLIST,
) -> bool:
    """True when ``spec`` may appear on a class-filtered read-only surface.

    Class membership is necessary but not sufficient: ``mutates=True`` tools
    stay off reviewer/verifier unless their name is in ``mutating_allowlist``.

    D9: publication is gated by name, not class.  ``REVIEW_WRITE`` is shared
    by several tools (``create_pull_request_review``, ``record_finding_verdict``,
    ``report_progress``, ``resolve_review_thread``); class membership alone
    would leak all of them to the reviewer.  The primary reviewer passes
    ``PRIMARY_MUTATING_ALLOWLIST`` which adds ``create_pull_request_review``,
    ``record_finding_verdict``, ``set_output``, ``select_mode``, and
    ``report_progress`` by name; subagents keep ``READONLY_MUTATING_ALLOWLIST``
    (checkout_pr only) so they remain denied publication and cannot call
    session tools.
    """
    if spec.tool_class not in allowed:
        return False
    return not spec.mutates or spec.name in mutating_allowlist


def tool(
    *,
    name: str,
    description: str,
    input_schema: JsonSchema,
    execute: ToolHandler,
    tool_class: ToolClass,
    mutates: bool = False,
    annotations: dict[str, Any] | None = None,
    timeout_ms: int | None = None,
) -> ToolSpec:
    handler = execute
    if mutates:
        inner = execute

        async def _gated(params: Mapping[str, Any]) -> Any:
            try:
                guard_mutating_tool(name)
            except Exception as error:
                return handle_tool_error(error)
            return await inner(params)

        handler = _gated
    return ToolSpec(
        name=name,
        description=description,
        input_schema=input_schema,
        execute=handler,
        tool_class=tool_class,
        mutates=mutates,
        annotations=annotations or {},
        timeout_ms=timeout_ms,
    )


def handle_tool_success(data: Mapping[str, Any] | str) -> ToolResult:
    text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
    return ToolResult(content=[{"type": "text", "text": text}])


def handle_tool_error(error: object) -> ToolResult:
    message = str(error)
    if isinstance(error, Exception):
        message = str(error)
    return ToolResult(content=[{"type": "text", "text": f"Error: {message}"}], is_error=True)


def get_http_status(err: object) -> int | None:
    status = getattr(err, "status", None)
    if isinstance(status, int):
        return status
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def execute(fn: ToolBody, tool_name: str | None = None) -> ToolHandler:
    """Wrap a tool body with success/error ToolResult handling.

    Mutation gating is applied once in :func:`tool` via ``guard_mutating_tool``.
    Callers must not pass ``mutates`` here.
    """

    async def _fn(params: Mapping[str, Any]) -> ToolResult:
        try:
            result = await fn(params)
            if isinstance(result, Mapping | str):
                return handle_tool_success(result)
            return handle_tool_success({"result": result})
        except Exception as error:
            prefix = f"[{tool_name}]" if tool_name else "tool"
            logger.info("{} error: {}", prefix, error)
            logger.debug("{} params: {}", prefix, params)
            return handle_tool_error(error)

    return _fn


EMPTY_SCHEMA: JsonSchema = {"type": "object", "properties": {}, "additionalProperties": False}
