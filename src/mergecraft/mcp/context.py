"""ToolContext dataclass shared by MCP tools and the HTTP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.modes import Mode
    from mergecraft.review_checks import StaticCheckConfig
    from mergecraft.types import AgentId, XrepoConfig
    from mergecraft.utils.github import GitHubClient
    from mergecraft.utils.run_bounds import BudgetTracker

AccountPlan = Literal["free", "pro", "team", "enterprise", "unknown"]


@dataclass(slots=True)
class RepoIdentity:
    owner: str
    name: str


@dataclass(slots=True)
class PayloadEvent:
    trigger: str = "unknown"
    issue_number: int | None = None
    is_pr: bool = False
    branch: str | None = None
    title: str | None = None
    body: str | None = None


@dataclass(slots=True)
class ResolvedPayload:
    """Minimal runtime payload; expanded as action wiring lands."""

    event: PayloadEvent = field(default_factory=PayloadEvent)
    shell: Literal["disabled", "restricted", "enabled"] = "restricted"
    push: Literal["disabled", "restricted", "enabled"] = "restricted"
    triggerer: str | None = None
    model: str | None = None
    cwd: str | None = None
    generate_summary: bool = False
    status_checks: bool = False
    suggest_eval_add: bool = False
    timeout: str | None = None
    prompt: str = ""
    xrepo: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolContext:
    agent_id: AgentId
    repo: RepoIdentity
    payload: ResolvedPayload
    github: GitHubClient
    github_installation_token: str
    git_token: str
    api_token: str
    modes: list[Mode]
    tool_state: ToolState
    mcp_server_url: str
    tmpdir: str
    refresh_git_token: Callable[[str], Awaitable[str]] | None = None
    read_token: str | None = None
    xrepo: XrepoConfig | None = None
    prepush_script: str | None = None
    pr_approve_enabled: bool = False
    auto_merge_enabled: bool = False
    signed_commits: bool = False
    mode_instructions: dict[str, str] = field(default_factory=dict)
    static_checks: list[StaticCheckConfig] = field(default_factory=list)
    # Whether `run_static_checks` is offered at all. Gates run repo-declared
    # commands, so on a pull request they are commands the PR author controls —
    # that is exactly what `shell: disabled` exists to forbid. Offline reviews
    # gate this on trust tier (D7) like the MCP serve path.
    static_checks_enabled: bool = False
    # #36 / D10 — repo-declared mapping from a mergeCraft gate name to the CI
    # check-run name that proves it, and the workflow artifacts whose SARIF may
    # be ingested. Both empty by default: with no declaration mergeCraft never
    # reads the consumer's CI and never substitutes a gate outcome.
    ci_gate_checks: dict[str, str] = field(default_factory=dict)
    ci_sarif_artifacts: list[str] = field(default_factory=list)
    analyzers_mode: Literal["off", "auto", "full", "untrusted-only"] = "auto"
    trust_tier: Literal["trusted", "untrusted"] = "trusted"
    analyzers_settings_enabled: bool = True
    # #39 / D13 — whether this run may upload analyzer findings to GitHub code
    # scanning. Default False: with it unset nothing is built, nothing is
    # posted, and the run makes no extra API call. Resolved once in `main.py`
    # from the `sarif_upload` action input and `analyzers.sarifUpload`.
    sarif_upload_enabled: bool = False
    run_id: int | None = None
    job_id: str | None = None
    oss: bool = False
    plan: AccountPlan = "unknown"
    resolved_model: str | None = None
    # W12.4 — opt-in. When True, `create_pull_request_review` logs a
    # `logger.info` suggestion to add the run to the eval bank when the
    # run produced no positive findings, the trust tier is `trusted`,
    # and the trigger is a re-review (not a fresh PR). Default False
    # (no suggestion). mergeCraft never auto-adds (#44).
    suggest_eval_add: bool = False
    budget_tracker: BudgetTracker | None = None
