"""ScmProvider protocol and validation helpers (DG9 / D10)."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

# GitHub REST helpers exercised today (mirrors tests/scm/test_protocol.py).
_GITHUB_REST_OPERATIONS: frozenset[str] = frozenset(
    {
        "get_repo",
        "get_commit",
        "get_issue",
        "create_issue",
        "update_issue",
        "list_issue_comments",
        "get_issue_comment",
        "create_issue_comment",
        "update_issue_comment",
        "list_issues",
        "create_label",
        "add_labels",
        "get_pull",
        "update_pull",
        "list_pull_files",
        "list_reviews",
        "get_review",
        "create_review",
        "submit_review",
        "delete_pending_review",
        "get_review_comment",
        "create_review_comment_reply",
        "create_status",
        "list_check_suites_for_ref",
        "get_check_suite",
        "list_check_runs_for_ref",
        "list_workflow_run_artifacts",
        "download_artifact_zip",
        "download_workflow_run_logs",
        "graphql",
        "get",
        "post",
        "patch",
        "put",
        "delete",
        "request",
    }
)

_GITHUB_MCP_READ_TOOLS: frozenset[str] = frozenset(
    {
        "get_pull_request",
        "get_issue",
        "get_issue_comments",
        "get_commit_info",
        "list_pull_request_reviews",
        "list_check_runs",
        "get_check_suite",
    }
)

# MCP tools whose production implementations use generic REST/GraphQL ops rather
# than a namesake protocol method — mapped in tests/scm/test_protocol.py.
_GITHUB_MCP_GENERIC_TOOLS: frozenset[str] = frozenset(
    {
        "get_issue_events",
        "get_check_suite_logs",
        "get_review_comments",
        "checkout_pr",
    }
)

_GITHUB_MCP_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "create_issue_comment",
        "edit_issue_comment",
        "reply_to_review_comment",
        "create_pull_request_review",
        "create_issue",
        "close_issue",
        "reopen_issue",
        "create_pull_request",
        "update_pull_request_body",
        "close_pull_request",
        "add_labels",
        "remove_labels",
        "resolve_review_thread",
    }
)

_PROTOCOL_OPERATIONS: frozenset[str] = (
    _GITHUB_REST_OPERATIONS | _GITHUB_MCP_READ_TOOLS | _GITHUB_MCP_WRITE_TOOLS
)


class ScmCapability(StrEnum):
    """Optional SCM features a provider may expose."""

    GRAPHQL = "graphql"
    CHECK_RUNS = "check_runs"
    CHECK_SUITES = "check_suites"
    WORKFLOW_ARTIFACTS = "workflow_artifacts"
    REVIEW_THREADS = "review_threads"
    STATUSES = "statuses"


@runtime_checkable
class ScmProvider(Protocol):
    """Platform-neutral SCM surface for mergeCraft review runs."""

    @property
    def capabilities(self) -> frozenset[ScmCapability]: ...

    async def aclose(self) -> None: ...

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any: ...

    async def get(self, path: str, **kwargs: Any) -> Any: ...
    async def post(self, path: str, **kwargs: Any) -> Any: ...
    async def patch(self, path: str, **kwargs: Any) -> Any: ...
    async def put(self, path: str, **kwargs: Any) -> Any: ...
    async def delete(self, path: str, **kwargs: Any) -> Any: ...

    async def graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]: ...
    async def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]: ...

    async def get_issue(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> dict[str, Any]: ...
    async def create_issue(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]: ...
    async def update_issue(
        self, owner: str, repo: str, issue_number: int, **fields: Any
    ) -> dict[str, Any]: ...
    async def list_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def get_issue_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]: ...
    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]: ...
    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]: ...
    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]: ...
    async def create_label(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        color: str = "ededed",
        description: str | None = None,
    ) -> dict[str, Any]: ...
    async def add_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]: ...

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]: ...
    async def update_pull(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]: ...
    async def list_pull_files(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def get_review(
        self, owner: str, repo: str, pull_number: int, review_id: int, **kwargs: Any
    ) -> dict[str, Any]: ...
    async def create_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]: ...
    async def submit_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        review_id: int,
        *,
        event: str,
        body: str | None = None,
    ) -> dict[str, Any]: ...
    async def delete_pending_review(
        self, owner: str, repo: str, pull_number: int, review_id: int
    ) -> dict[str, Any] | None: ...
    async def get_review_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]: ...
    async def create_review_comment_reply(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]: ...

    async def create_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        *,
        state: str,
        context: str,
        description: str | None = None,
        target_url: str | None = None,
    ) -> dict[str, Any]: ...
    async def list_check_suites_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]: ...
    async def get_check_suite(
        self, owner: str, repo: str, check_suite_id: int
    ) -> dict[str, Any]: ...
    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]: ...
    async def list_workflow_run_artifacts(
        self, owner: str, repo: str, run_id: int
    ) -> list[dict[str, Any]]: ...
    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes: ...
    async def download_workflow_run_logs(self, owner: str, repo: str, run_id: int) -> bytes: ...

    # MCP-level aliases (tool names differ from REST helpers).
    async def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]: ...
    async def get_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def get_commit_info(self, owner: str, repo: str, sha: str) -> dict[str, Any]: ...
    async def list_pull_request_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def list_check_runs(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]: ...

    async def edit_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]: ...
    async def reply_to_review_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]: ...
    async def create_pull_request_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]: ...
    async def close_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]: ...
    async def reopen_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]: ...
    async def create_pull_request(
        self, owner: str, repo: str, *, title: str, head: str, base: str, **extra: Any
    ) -> dict[str, Any]: ...
    async def update_pull_request_body(
        self, owner: str, repo: str, pull_number: int, body: str
    ) -> dict[str, Any]: ...
    async def close_pull_request(
        self, owner: str, repo: str, pull_number: int
    ) -> dict[str, Any]: ...
    async def remove_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]: ...
    async def resolve_review_thread(
        self, owner: str, repo: str, thread_id: str
    ) -> dict[str, Any]: ...


def protocol_operation_names() -> frozenset[str]:
    """Return every operation name the GitHub surface exposes today."""
    return _PROTOCOL_OPERATIONS


def protocol_supports_github_operations() -> bool:
    """True when the declared protocol covers the full GitHub REST + MCP surface."""
    declared = protocol_operation_names()
    return declared >= _GITHUB_REST_OPERATIONS and declared >= (
        _GITHUB_MCP_READ_TOOLS | _GITHUB_MCP_WRITE_TOOLS
    )


def mcp_generic_tool_names() -> frozenset[str]:
    """MCP tools satisfied via generic REST/GraphQL ops, not namesake protocol methods."""
    return _GITHUB_MCP_GENERIC_TOOLS


def _async_protocol_operations() -> frozenset[str]:
    """Operation names declared ``async def`` on ``ScmProvider``."""
    async_ops: set[str] = set()
    for name in protocol_operation_names():
        member = getattr(ScmProvider, name, None)
        if member is not None and inspect.iscoroutinefunction(member):
            async_ops.add(name)
    return frozenset(async_ops)


@dataclass(slots=True)
class ProviderValidationReport:
    complete: bool
    missing: tuple[str, ...] = ()


def validate_provider(provider: object) -> ProviderValidationReport:
    """Check that ``provider`` implements every declared protocol operation."""
    missing: list[str] = []
    async_ops = _async_protocol_operations()
    for name in sorted(protocol_operation_names()):
        member = getattr(provider, name, None)
        if member is None or not callable(member):
            missing.append(name)
            continue
        is_async = inspect.iscoroutinefunction(member)
        if name in async_ops and not is_async:
            missing.append(f"{name} (expected async)")
        elif name not in async_ops and is_async:
            missing.append(f"{name} (expected sync)")
    return ProviderValidationReport(complete=not missing, missing=tuple(missing))


def resolve_scm_provider(ctx: ToolContext) -> ScmProvider:
    """Return the SCM provider bound on a tool context."""
    return ctx.scm
