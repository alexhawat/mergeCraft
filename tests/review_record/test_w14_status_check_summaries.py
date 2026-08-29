"""W1.4 — status checks derive truthful summaries (implementation W4)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from loguru import logger

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY, decide_approval
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.evidence.run_packet import prepare_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, report_status_checks
from tests.review_record.conftest import make_scoped_finding, make_test_finding

if TYPE_CHECKING:
    from pathlib import Path

RUN_URL = "https://github.com/acme/demo/actions/runs/33126460925"
REVIEWED_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
PR_HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"


class _RecordingGitHub(GitHubClient):
    def __init__(self, *, pr_head_sha: str = PR_HEAD_SHA) -> None:
        super().__init__(token="test-token")
        self.pr_head_sha = pr_head_sha
        self.check_runs: list[dict[str, Any]] = []
        self.fail_next_approval_post = False

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"head": {"sha": self.pr_head_sha}}

    async def post(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/check-runs"):
            body = kwargs.get("json")
            if isinstance(body, dict):
                if body.get("name") == APPROVAL_CHECK and self.fail_next_approval_post:
                    msg = "simulated check-run post failure"
                    raise RuntimeError(msg)
                self.check_runs.append(body)
        return {}


def _ctx(tmp_path: Path, *, github: _RecordingGitHub | None = None) -> ToolContext:
    gh = github or _RecordingGitHub()
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.approval = ApprovalRecord(would_approve=True, sha=REVIEWED_SHA)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=546, is_pr=True),
            status_checks=True,
            shell="restricted",
        ),
        github=gh,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        run_id="33126460925",
    )


def _packet_with_findings(
    findings: list[Any],
    *,
    verdict: str,
    reason: str,
) -> Any:
    packet = build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=findings,
        deterministic_checks=[],
        self_assessment={"would_approve": verdict == "success", "sha": REVIEWED_SHA},
    )
    packet.decision = Decision(
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet


def _approval_summary(github: _RecordingGitHub) -> str:
    approval = next(run for run in github.check_runs if run.get("name") == APPROVAL_CHECK)
    return str(approval["output"]["summary"])


@pytest.mark.asyncio
async def test_zero_change_findings_never_claim_outstanding_feedback(tmp_path: Path) -> None:
    run_only = [
        make_scoped_finding(scope="run", severity="Critical", rule_id="ignored-tool-error"),
    ]
    packet = _packet_with_findings(run_only, verdict="success", reason="run health advisory only")
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    await report_status_checks(ctx, run_succeeded=True, packet=packet)
    summary = _approval_summary(github)
    assert "outstanding review feedback" not in summary.lower()


@pytest.mark.asyncio
async def test_three_distinct_summaries_for_outcomes(tmp_path: Path) -> None:
    cases = [
        (
            "change findings outstanding",
            [make_scoped_finding(scope="change", severity="Major", introduced_by_pr="true")],
            "failure",
            "blocking change finding",
        ),
        (
            "run incomplete",
            [],
            "neutral",
            "review did not complete",
        ),
        (
            "approved",
            [make_test_finding(severity="Minor", source="agent")],
            "success",
            "approved",
        ),
    ]
    summaries: list[str] = []
    for _label, findings, verdict, reason in cases:
        if verdict == "success" and findings:
            decision = decide_approval(findings, run_succeeded=True, tier="trusted")
            assert decision == "success"
        packet = _packet_with_findings(findings, verdict=verdict, reason=reason)
        github = _RecordingGitHub()
        ctx = _ctx(tmp_path, github=github)
        await report_status_checks(ctx, run_succeeded=verdict != "neutral", packet=packet)
        summaries.append(_approval_summary(github))
    assert len({s.splitlines()[0] for s in summaries}) == 3


@pytest.mark.asyncio
async def test_every_summary_carries_run_url_and_reviewed_sha(tmp_path: Path) -> None:
    packet = _packet_with_findings([], verdict="success", reason="clean")
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    await report_status_checks(ctx, run_succeeded=True, packet=packet)
    summary = _approval_summary(github)
    assert RUN_URL in summary
    assert REVIEWED_SHA in summary


@pytest.mark.asyncio
async def test_failed_check_run_post_emits_warning_and_annotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    warnings: list[str] = []
    log_warnings: list[str] = []

    import mergecraft.utils.gha_log as gha_log

    real_warning = gha_log.warning

    def _spy_warning(message: str) -> None:
        warnings.append(message)
        real_warning(message)

    monkeypatch.setattr(gha_log, "warning", _spy_warning)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    github = _RecordingGitHub()
    github.fail_next_approval_post = True
    packet = _packet_with_findings([], verdict="success", reason="clean")

    with logger.contextualize():
        handler_id = logger.add(
            lambda msg: log_warnings.append(msg.record["message"]), level="WARNING"
        )

    try:
        ctx = _ctx(tmp_path, github=github)
        await report_status_checks(ctx, run_succeeded=True, packet=packet)
    finally:
        logger.remove(handler_id)

    captured = capsys.readouterr()
    assert warnings, "expected ::warning:: annotation on failed approval post"
    assert any(APPROVAL_CHECK in message for message in log_warnings)
    assert re.search(r"::warning::", captured.out)


@pytest.mark.asyncio
async def test_successful_post_emits_one_info_line_per_check(tmp_path: Path) -> None:
    packet = prepare_run_packet(_ctx(tmp_path), run_succeeded=True)
    ctx = _ctx(tmp_path)
    info_lines: list[str] = []
    handler_id = logger.add(lambda msg: info_lines.append(msg.record["message"]), level="INFO")
    try:
        await report_status_checks(ctx, run_succeeded=True, packet=packet)
    finally:
        logger.remove(handler_id)
    posted = [line for line in info_lines if "posted" in line and "check" in line]
    assert len(posted) == 2


@pytest.mark.asyncio
async def test_post_failure_does_not_raise_into_run_outcome(tmp_path: Path) -> None:
    github = _RecordingGitHub()
    github.fail_next_approval_post = True
    ctx = _ctx(tmp_path, github=github)
    packet = _packet_with_findings([], verdict="success", reason="clean")
    await report_status_checks(ctx, run_succeeded=True, packet=packet)
