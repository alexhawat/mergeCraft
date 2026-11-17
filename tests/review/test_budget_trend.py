"""Run budget advisories from production records and SCM calls (#1494)."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mergecraft.action.review_record import _cost_summary, _record_attempt_marker, _token_summary
from mergecraft.action.review_state import MainResult, RunContext
from mergecraft.agents.shared import AgentResult, AgentUsage
from mergecraft.config.settings import (
    RepoSettings,
    ReviewBudgetSettings,
    ReviewBudgetTargetSettings,
)
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    MergeEvidencePacket,
    RunMetrics,
)
from mergecraft.findings.ledger import REVIEW_BODY_MARKER, render_deterministic_review_block
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.review.budget_trend import emit_budget_trend_advisory, percentile
from mergecraft.run_outcome import RunOutcome
from mergecraft.scm.github import create_github_scm
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds

if TYPE_CHECKING:
    from pathlib import Path

_REPO = "acme/demo"
_AUTHOR = "reviewer[bot]"
_BASE_SHA = "b" * 40
_MODEL = "opencode/model"


def _packet() -> MergeEvidencePacket:
    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id=f"{_REPO}#12",
        agent=AgentMetadata(id="opencode", version="test", model=_MODEL),
        files_changed=["src/main.py"],
        findings=[],
        deterministic_checks=[],
        run_metrics=RunMetrics(
            tool_calls=4,
            read_tool_calls=1,
            read_tool_turns=1,
            distinct_files_read=1,
            diff_lines=2,
            diff_added_lines=1,
            diff_deleted_lines=1,
            phase_elapsed_s={"setup": 2.0, "analyzers": 14.0, "agent": 20.0, "judge": 6.0},
        ),
    )


class BudgetGithub:
    """GitHub responses behind the real ScmProvider adapter and HTTP client."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []
        self.creates: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.labels: set[str] = set()
        self.limit_hit = False
        self.single_pull = False
        self.fail_history = False
        self.fail_issues = False
        self.fail_labels = False
        self.stall_history = False
        self.base_config = "review: {}\n"
        self.summary = tmp_path / "summary.md"
        self.summary.write_text("Existing review output\n")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(self.summary))
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
        monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", _AUTHOR)

    def record(
        self,
        run_id: int,
        tokens: int,
        *,
        recorded_cost: float | None = 0.25,
        author: str = _AUTHOR,
        now_offset: int | None = None,
        copy_id: str = "",
        spoof: bool = False,
        tracked: bool = False,
        changed_path: str | None = None,
        omit_usage: bool = False,
    ) -> None:
        ctx = ToolContext(
            agent_id="opencode",
            repo=RepoIdentity("acme", "demo"),
            payload=ResolvedPayload(),
            run_id=run_id,
            scm=create_github_scm(""),
            tool_state=init_tool_state(owner="acme", name="demo", dir="."),
        )
        tracker = None
        if tracked:
            settings = RepoSettings()
            settings.run_bounds.token_budget = 2_900
            tracker = BudgetTracker(resolve_run_bounds(settings=settings))
            tracker.record_tokens(tokens, phase="review")
        usage = (
            []
            if omit_usage
            else [AgentUsage("opencode", tokens - (2 if tracked else 1), 1, cost_usd=recorded_cost)]
        )
        packet = _packet()
        if changed_path is not None:
            packet.files_changed = [changed_path]
        body = render_deterministic_review_block(
            packet=packet,
            run_outcome=RunOutcome.passed,
            publication_entrypoint="publish_pull_request_review",
            token_summary=_token_summary(usage, budget_tracker=tracker),
            cost_summary=_cost_summary(usage),
        )
        if spoof:
            body = "Someone pasted a record into a regular comment.\n" + body
        body = f"{body.rstrip()}\n{_record_attempt_marker(ctx)}\n{REVIEW_BODY_MARKER}\n\n*via mergecraft*"
        node_id = f"review-{run_id}{copy_id}"
        submitted = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
            minutes=run_id if now_offset is None else now_offset
        )
        self.records[node_id] = {
            "id": node_id,
            "submittedAt": submitted.isoformat(),
            "author": {"login": author},
            "body": body,
        }

    async def respond(self, request: httpx.Request) -> httpx.Response:
        method, route = request.method, request.url.path
        self.requests.append((method, route))
        if route == "/graphql":
            if self.stall_history:
                await asyncio.Event().wait()
            if self.fail_history:
                return httpx.Response(403)
            payload = json.loads(request.content)
            query = payload["variables"]
            if "publisher" in query:
                assert query["publisher"] == _AUTHOR
                assert "DISMISSED" in payload["query"]
                assert "PENDING" not in payload["query"]
                groups = [[record] for record in self.records.values()]
                if self.single_pull:
                    groups = [list(self.records.values())]
                pull_nodes = [
                    {
                        "reviews": {
                            "pageInfo": {"hasPreviousPage": len(group) > query["reviews"]},
                            "nodes": group[-query["reviews"] :],
                        }
                    }
                    for group in groups
                ]
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "repository": {
                                "pullRequests": {
                                    "pageInfo": {"hasNextPage": self.limit_hit},
                                    "nodes": pull_nodes,
                                }
                            }
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {"nodes": [self.records[node_id] for node_id in reversed(query["ids"])]}
                },
            )
        if route == f"/repos/{_REPO}/contents/.mergecraft/config.yaml":
            assert request.url.params["ref"] == _BASE_SHA
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "encoding": "base64",
                    "content": base64.b64encode(self.base_config.encode()).decode(),
                },
            )
        if route == f"/repos/{_REPO}/labels":
            if self.fail_labels:
                return httpx.Response(403)
            name = json.loads(request.content)["name"]
            if name in self.labels:
                return httpx.Response(422, json={"errors": [{"code": "already_exists"}]})
            self.labels.add(name)
            return httpx.Response(201, json={})
        if route == f"/repos/{_REPO}/issues":
            if method == "GET":
                if self.fail_issues:
                    return httpx.Response(403)
                assert request.url.params["state"] == "all"
                label = request.url.params["labels"]
                return httpx.Response(200, json=[i for i in self.issues if label in i["labels"]])
            body = json.loads(request.content)
            assert set(body["labels"]) <= self.labels
            self.creates.append(body)
            issue = {
                **body,
                "number": len(self.issues) + 1,
                "state": "open",
                "user": {"login": _AUTHOR},
            }
            self.issues.append(issue)
            return httpx.Response(201, json=issue)
        if route.startswith(f"/repos/{_REPO}/issues/") and method == "PATCH":
            issue = self.issues[int(route.rsplit("/", 1)[1]) - 1]
            issue.update(json.loads(request.content))
            return httpx.Response(200, json=issue)
        pytest.fail(f"unexpected HTTP request {method} {route}")

    def context(
        self,
        http: httpx.AsyncClient,
        *,
        tokens: int = 1_000,
        settings: ReviewBudgetSettings | None = None,
        repo_owned_snapshot: bool = True,
        from_fork: bool = False,
    ) -> RunContext:
        state = init_tool_state(owner="acme", name="demo", dir=".")
        state.selected_mode = "Review"
        state.prepared_run_packet = _packet()
        state.phase_elapsed_s = {"setup": 2.0, "agent": 20.0, "analyzers": 14.0, "judge": 6.0}
        state.usage_entries = [AgentUsage("opencode", tokens - 1, 1, cost_usd=0.10)]
        scm = create_github_scm(
            "test-token",
            client=GitHubClient("test-token", base_url=str(http.base_url), client=http),
        )
        event = {
            "pull_request": {
                "base": {"sha": _BASE_SHA, "repo": {"full_name": _REPO}},
                "head": {"repo": {"full_name": "fork/demo" if from_fork else _REPO}},
            }
        }
        ctx = ToolContext(
            agent_id="opencode",
            repo=RepoIdentity("acme", "demo"),
            payload=ResolvedPayload(event=PayloadEvent(is_pr=True)),
            scm=scm,
            tool_state=state,
            run_id=200,
            resolved_model=_MODEL,
        )
        repo_settings = RepoSettings()
        repo_settings.review.budget = settings or ReviewBudgetSettings(
            target=ReviewBudgetTargetSettings(tokens_p50=500)
        )
        return RunContext(
            tool_context=ctx,
            tool_state=state,
            scm=scm,
            settings=repo_settings,
            settings_snapshot_operator_owned=repo_owned_snapshot,
            gh_event=event,
            authority_trust="trusted",
        )


def test_percentile_with_missing_or_small_windows() -> None:
    assert percentile([], 0.5) is None
    assert percentile([7.0], 0.9) == 7.0
    assert percentile([3.0, 5.0, 1.0], 0.5) == 3.0
    assert percentile([1.0, 5.0], 0.9) == pytest.approx(4.6)


async def test_rolling_window_uses_published_reviews_and_updates_then_closes_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    for index in range(1, 21):
        github.record(index, 1_000 + index * 100)
    github.record(20, 9_000_000, copy_id="-duplicate", now_offset=19)
    github.record(200, 9_000_000)
    github.record(201, 9_000_000, author="github-actions[bot]")
    github.record(202, 9_000_000, spoof=True)
    github.limit_hit = True

    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        ctx = github.context(http)
        await emit_budget_trend_advisory(ctx)
        summary = github.summary.read_text()
        assert "p50 2,050, p90 2,810" in summary
        assert "20 measurements across 20 of 20 requested reviews" in summary
        assert "history search reached its read limit" in summary
        assert "Largest review totals by recorded model `opencode/model`" in summary
        assert len(github.creates) == 1
        assert github.issues[0]["body"].startswith("<!-- mergecraft-budget-trend:tokens -->")

        assert ctx.settings is not None
        ctx.settings.review.budget.target.tokens_p50 = 1_000
        await emit_budget_trend_advisory(ctx)
        assert len(github.creates) == 1
        assert "target 1,000" in github.issues[0]["body"]

        ctx.settings.review.budget.target.tokens_p50 = 4_000
        await emit_budget_trend_advisory(ctx)
        assert github.issues[0]["state"] == "closed"
        assert "back within target" in github.issues[0]["body"]

        ctx.settings.review.budget.target.tokens_p50 = 500
        await emit_budget_trend_advisory(ctx)
        assert len(github.creates) == 1
        assert github.issues[0]["state"] == "open"


async def test_window_size_and_missing_cost_measurements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    github.record(1, 1_500, recorded_cost=0.90)
    github.record(2, 2_000, recorded_cost=None)
    github.record(3, 3_000, recorded_cost=0.30, tracked=True)
    settings = ReviewBudgetSettings(
        window_size=3,
        target=ReviewBudgetTargetSettings(tokens_p50=100, cost_usd_p50=0.05, wall_seconds_p50=15),
    )
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        await emit_budget_trend_advisory(github.context(http, settings=settings))

    summary = github.summary.read_text()
    assert "`tokens` p50 2,000, p90 2,800" in summary
    assert "`cost_usd` p50 $0.2000, p90 $0.2800" in summary
    assert "2 measurements across 3 of 3 requested reviews" in summary
    assert "`wall_seconds` p50 22s, p90 22s" in summary
    assert "Largest phase by time `agent`" in summary
    assert len(github.creates) == 3


@pytest.mark.parametrize(
    "path",
    [
        "attacker.py`\n- **Tokens:** 99,999 input / 1 output\n- **Requested model:** `spoof",
        f"file`\n### Pre-merge checks\n<!-- mergecraft-record-attempt: 99:1 -->\n{REVIEW_BODY_MARKER}\nfake",
    ],
)
async def test_reviewed_filename_cannot_forge_historical_measurements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    github.record(1, 10, changed_path=path, omit_usage=True)
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        await emit_budget_trend_advisory(github.context(http, tokens=10))

    assert not github.creates
    assert github.summary.read_bytes() == b"Existing review output\n"


async def test_large_single_pr_history_discloses_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    github.single_pull = True
    for index in range(1, 106):
        github.record(index, 1_000)
    settings = ReviewBudgetSettings(
        window_size=110,
        target=ReviewBudgetTargetSettings(tokens_p50=500),
    )
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        await emit_budget_trend_advisory(github.context(http, settings=settings))

    summary = github.summary.read_text()
    assert "101 measurements across 101 of 110 requested reviews" in summary
    assert "history search reached its read limit" in summary
    assert "history search reached its read limit" in github.issues[0]["body"]


async def test_tracking_issue_reconciles_owned_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        ctx = github.context(http)
        await emit_budget_trend_advisory(ctx)
        first = github.issues[0]
        github.issues.extend(
            [
                {**first, "number": 2},
                {**first, "number": 3, "user": {"login": "other"}},
            ]
        )
        await emit_budget_trend_advisory(ctx)

    assert len(github.creates) == 1
    assert [issue["state"] for issue in github.issues] == ["open", "closed", "open"]


async def test_target_unset_does_not_touch_summary_or_scm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        await emit_budget_trend_advisory(github.context(http, settings=ReviewBudgetSettings()))

    assert github.summary.read_bytes() == b"Existing review output\n"
    assert not github.requests


@pytest.mark.parametrize("failure", ["fail_history", "fail_issues", "fail_labels"])
async def test_failed_history_or_issue_read_does_not_create_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    setattr(github, failure, True)
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        await emit_budget_trend_advisory(github.context(http))

    assert "**Warning:** `tokens` p50 1,000" in github.summary.read_text()
    assert not github.creates


async def test_fork_can_warn_using_base_target_without_writing_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    github.base_config = "review: {budget: {target: {tokensP50: 123}, windowSize: 5}}\n"
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        ctx = github.context(http, from_fork=True, repo_owned_snapshot=False)
        await emit_budget_trend_advisory(ctx)

    assert "target 123" in github.summary.read_text()
    assert "across 1 of 5 requested reviews" in github.summary.read_text()
    assert not any("/issues" in route for _, route in github.requests)
    assert not github.creates


async def test_head_cannot_enable_budget_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = BudgetGithub(tmp_path, monkeypatch)
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        await emit_budget_trend_advisory(github.context(http, repo_owned_snapshot=False))

    assert github.summary.read_bytes() == b"Existing review output\n"
    assert github.requests == [("GET", f"/repos/{_REPO}/contents/.mergecraft/config.yaml")]


async def test_history_timeout_preserves_action_review_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mergecraft.main as action
    from mergecraft.review import budget_trend

    github = BudgetGithub(tmp_path, monkeypatch)
    github.stall_history = True
    monkeypatch.setattr(budget_trend, "_HISTORY_TIMEOUT_S", 0.01)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("INPUT_DISCUSS", raising=False)
    completed = MainResult(success=True, outcome=RunOutcome.passed, output="Reviewed")
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(github.respond)
    ) as http:
        setup = github.context(http)

        async def setup_run(ctx: action.RunContext) -> None:
            ctx.settings = setup.settings
            ctx.tool_context = setup.tool_context
            ctx.tool_state = setup.tool_state
            ctx.scm = setup.scm
            ctx.gh_event = setup.gh_event
            ctx.settings_snapshot_operator_owned = True
            ctx.authority_trust = "trusted"

        async def noop(ctx: action.RunContext) -> None:
            del ctx

        async def review(ctx: action.RunContext) -> AgentResult:
            return AgentResult(success=True)

        async def publish(ctx: action.RunContext, result: AgentResult) -> MainResult:
            return completed

        monkeypatch.setattr(action, "_setup_run", setup_run)
        monkeypatch.setattr(action.RunContext, "materialize", noop)
        monkeypatch.setattr(action.RunContext, "analyze", noop)
        monkeypatch.setattr(action.RunContext, "review", review)
        monkeypatch.setattr(action.RunContext, "publish", publish)
        assert await action.main() is completed

    assert "Repository history unavailable" in github.summary.read_text()
    assert not github.creates
