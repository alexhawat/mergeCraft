"""ToolContext dataclass shared by MCP tools and the HTTP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot
    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.modes import Mode
    from mergecraft.review_checks import StaticCheckConfig
    from mergecraft.scm.protocol import ScmProvider
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


@dataclass(slots=True, init=False)
class ToolContext:
    """Runtime context for MCP tools and the review harness.

    Production code must use :attr:`scm` (:class:`~mergecraft.scm.protocol.ScmProvider`).
    Tests may pass ``github=`` at construction or bind a client via
    ``tests.support.tool_context.bind_github_client``.
    """

    agent_id: AgentId
    repo: RepoIdentity
    payload: ResolvedPayload
    scm: ScmProvider
    github_installation_token: str
    git_token: str
    api_token: str
    modes: list[Mode]
    tool_state: ToolState
    mcp_server_url: str
    mcp_auth_token: str
    mcp_orchestrator_auth_token: str
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
    static_checks_enabled: bool = False
    ci_gate_checks: dict[str, str] = field(default_factory=dict)
    ci_sarif_artifacts: list[str] = field(default_factory=list)
    analyzers_mode: Literal["off", "auto", "full", "untrusted-only"] = "auto"
    trust_tier: Literal["trusted", "untrusted"] = "trusted"
    analyzers_settings_enabled: bool = True
    sarif_upload_enabled: bool = False
    run_id: int | None = None
    job_id: str | None = None
    oss: bool = False
    plan: AccountPlan = "unknown"
    resolved_model: str | None = None
    suggest_eval_add: bool = False
    budget_tracker: BudgetTracker | None = None
    repo_settings_snapshot: RepoSettingsSnapshot | None = None

    def __init__(
        self,
        *,
        agent_id: AgentId,
        repo: RepoIdentity,
        payload: ResolvedPayload,
        github: GitHubClient | None = None,
        scm: ScmProvider | None = None,
        github_installation_token: str = "",
        git_token: str = "",
        api_token: str = "",
        modes: list[Mode] | None = None,
        tool_state: ToolState | None = None,
        mcp_server_url: str = "",
        mcp_auth_token: str = "",
        mcp_orchestrator_auth_token: str = "",
        tmpdir: str = "",
        refresh_git_token: Callable[[str], Awaitable[str]] | None = None,
        read_token: str | None = None,
        xrepo: XrepoConfig | None = None,
        prepush_script: str | None = None,
        pr_approve_enabled: bool = False,
        auto_merge_enabled: bool = False,
        signed_commits: bool = False,
        mode_instructions: dict[str, str] | None = None,
        static_checks: list[StaticCheckConfig] | None = None,
        static_checks_enabled: bool = False,
        ci_gate_checks: dict[str, str] | None = None,
        ci_sarif_artifacts: list[str] | None = None,
        analyzers_mode: Literal["off", "auto", "full", "untrusted-only"] = "auto",
        trust_tier: Literal["trusted", "untrusted"] = "trusted",
        analyzers_settings_enabled: bool = True,
        sarif_upload_enabled: bool = False,
        run_id: int | None = None,
        job_id: str | None = None,
        oss: bool = False,
        plan: AccountPlan = "unknown",
        resolved_model: str | None = None,
        suggest_eval_add: bool = False,
        budget_tracker: BudgetTracker | None = None,
        repo_settings_snapshot: RepoSettingsSnapshot | None = None,
    ) -> None:
        from mergecraft.scm.github import GitHubScmAdapter

        if scm is not None:
            resolved_scm = scm
        elif github is not None:
            resolved_scm = GitHubScmAdapter(github)
        else:
            msg = "ToolContext requires scm= or github=; empty GitHub fallback is not allowed"
            raise ValueError(msg)

        self.agent_id = agent_id
        self.repo = repo
        self.payload = payload
        self.scm = resolved_scm
        self.github_installation_token = github_installation_token
        self.git_token = git_token
        self.api_token = api_token
        self.modes = list(modes or [])
        if tool_state is None:
            msg = "tool_state is required"
            raise ValueError(msg)
        self.tool_state = tool_state
        self.mcp_server_url = mcp_server_url
        self.mcp_auth_token = mcp_auth_token
        self.mcp_orchestrator_auth_token = mcp_orchestrator_auth_token
        self.tmpdir = tmpdir
        self.refresh_git_token = refresh_git_token
        self.read_token = read_token
        self.xrepo = xrepo
        self.prepush_script = prepush_script
        self.pr_approve_enabled = pr_approve_enabled
        self.auto_merge_enabled = auto_merge_enabled
        self.signed_commits = signed_commits
        self.mode_instructions = dict(mode_instructions or {})
        self.static_checks = list(static_checks or [])
        self.static_checks_enabled = static_checks_enabled
        self.ci_gate_checks = dict(ci_gate_checks or {})
        self.ci_sarif_artifacts = list(ci_sarif_artifacts or [])
        self.analyzers_mode = analyzers_mode
        self.trust_tier = trust_tier
        self.analyzers_settings_enabled = analyzers_settings_enabled
        self.sarif_upload_enabled = sarif_upload_enabled
        self.run_id = run_id
        self.job_id = job_id
        self.oss = oss
        self.plan = plan
        self.resolved_model = resolved_model
        self.suggest_eval_add = suggest_eval_add
        self.budget_tracker = budget_tracker
        self.repo_settings_snapshot = repo_settings_snapshot
