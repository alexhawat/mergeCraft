"""MCP tool primitives: ToolSpec, mutates flag, tool() helper."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
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


def admits_readonly_role(spec: ToolSpec, allowed: frozenset[ToolClass]) -> bool:
    """True when ``spec`` may appear on a class-filtered read-only surface.

    Class membership is necessary but not sufficient: ``mutates=True`` tools
    stay off reviewer/verifier unless they are on
    ``READONLY_MUTATING_ALLOWLIST`` (today: ``checkout_pr``, HA4.2 / D14).
    """
    if spec.tool_class not in allowed:
        return False
    return not spec.mutates or spec.name in READONLY_MUTATING_ALLOWLIST


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
    return ToolSpec(
        name=name,
        description=description,
        input_schema=input_schema,
        execute=execute,
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
    """Wrap a tool body with success/error ToolResult handling."""

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
