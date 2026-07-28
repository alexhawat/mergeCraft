"""Mutable per-run tool state (ported from toolState.ts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

RepoAccess = Literal["primary", "write", "read"]


@dataclass(slots=True)
class BackgroundProcess:
    pid: int
    output_path: str
    pid_path: str


@dataclass(slots=True)
class StoredPushDest:
    remote_name: str
    remote_branch: str
    local_branch: str


@dataclass(slots=True)
class CommentableLines:
    RIGHT: set[int] = field(default_factory=set)
    LEFT: set[int] = field(default_factory=set)


@dataclass(slots=True)
class InitialHeadBranch:
    kind: Literal["branch"]
    name: str


@dataclass(slots=True)
class InitialHeadDetached:
    kind: Literal["detached"]
    sha: str


InitialHead = InitialHeadBranch | InitialHeadDetached


@dataclass(slots=True)
class RepoToolState:
    owner: str
    name: str
    dir: str
    access: RepoAccess
    default_branch: str | None = None
    push_url: str | None = None
    push_dest: StoredPushDest | None = None
    initial_head: InitialHead | None = None
    issue_number: int | None = None
    checkout_sha: str | None = None
    commentable_lines_by_file: dict[str, CommentableLines] | None = None
    commentable_lines_pull_number: int | None = None
    commentable_lines_checkout_sha: str | None = None
    before_sha: str | None = None
    diff_coverage: Any = None


@dataclass(slots=True)
class ProgressComment:
    id: str
    type: Literal["issue", "review"]


@dataclass(slots=True)
class ReviewRecord:
    id: int
    node_id: str
    reviewed_sha: str | None


@dataclass(slots=True)
class ApprovalRecord:
    would_approve: bool
    sha: str | None


@dataclass(slots=True)
class ReviewReplyRecord:
    comment_id: int
    url: str | None
    body_with_footer: str


@dataclass(slots=True)
class DependencyInstallationState:
    status: Literal["not_started", "in_progress", "completed", "failed"]
    promise: Any = None
    results: list[Any] | None = None


@dataclass(slots=True)
class AnalyzerStatusRow:
    id: str
    status: str
    reason: str | None = None
    finding_count: int = 0


@dataclass(slots=True)
class AnalyzerRunState:
    ran: bool = False
    reason: str | None = None
    analyzers: list[AnalyzerStatusRow] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    inline: list[dict[str, Any]] = field(default_factory=list)
    mechanical_section: str | None = None
    pre_merge_summary: str | None = None
    lockfile_digest: str | None = None


@dataclass(slots=True)
class ToolState:
    repos: dict[str, RepoToolState]
    primary_repo_key: str
    prepush_failure_count: int = 0
    background_processes: dict[str, BackgroundProcess] = field(default_factory=dict)
    selected_mode: str | None = None
    review: ReviewRecord | None = None
    approval: ApprovalRecord | None = None
    review_replies: dict[int, ReviewReplyRecord] = field(default_factory=dict)
    dependency_installation: DependencyInstallationState | None = None
    progress_comment: ProgressComment | None | Literal[False] = None
    # None = unset, ProgressComment = active, False = deliberately deleted (TS uses null)
    had_progress_comment: bool = False
    last_progress_body: str | None = None
    was_updated: bool = False
    final_summary_written: bool = False
    existing_plan_comment_id: int | None = None
    previous_plan_body: str | None = None
    summary_file_path: str | None = None
    summary_seed: str | None = None
    summary_persist_attempted: bool = False
    learnings_file_path: str | None = None
    learnings_seed: str | None = None
    learnings_persist_attempted: bool = False
    xrepo_learnings_file_path: str | None = None
    xrepo_learnings_seed: str | None = None
    xrepo_learnings_persist_attempted: bool = False
    output: str | None = None
    usage_entries: list[Any] = field(default_factory=list)
    model: str | None = None
    model_fallback: dict[str, str] | None = None
    unselected_proxy_default: bool | None = None
    model_clamped: dict[str, str] | None = None
    sha_pinned: bool | None = None
    oss: bool | None = None
    todo_tracker: Any = None
    agent_diagnostic: Any = None
    browser_daemon: Any = None
    analyzer_run: AnalyzerRunState | None = None


def repo_key(owner: str, name: str) -> str:
    return f"{owner}/{name}".lower()


def init_tool_state(
    *,
    owner: str,
    name: str,
    dir: str,
    progress_comment: ProgressComment | None = None,
) -> ToolState:
    if progress_comment:
        logger.info(
            "using pre-created progress comment: {} ({})",
            progress_comment.id,
            progress_comment.type,
        )
    primary = repo_key(owner, name)
    repos = {
        primary: RepoToolState(owner=owner, name=name, dir=dir, access="primary"),
    }
    return ToolState(
        repos=repos,
        primary_repo_key=primary,
        progress_comment=progress_comment,
        had_progress_comment=progress_comment is not None,
    )


def primary_repo_state(tool_state: ToolState) -> RepoToolState:
    state = tool_state.repos.get(tool_state.primary_repo_key)
    if state is None:
        msg = "primary repo state not initialized"
        raise RuntimeError(msg)
    return state


def require_repo_state(tool_state: ToolState, owner: str, name: str) -> RepoToolState:
    key = repo_key(owner, name)
    state = tool_state.repos.get(key)
    if state is None:
        msg = f"repo {key} is not a registered checkout — use checkout_repo first"
        raise RuntimeError(msg)
    return state


def ensure_repo_state(
    tool_state: ToolState,
    *,
    owner: str,
    name: str,
    dir: str,
    access: RepoAccess,
) -> RepoToolState:
    key = repo_key(owner, name)
    existing = tool_state.repos.get(key)
    if existing is not None:
        return existing
    created = RepoToolState(owner=owner, name=name, dir=dir, access=access)
    tool_state.repos[key] = created
    return created
