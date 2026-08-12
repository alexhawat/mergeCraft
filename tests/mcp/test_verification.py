"""Agent-finding verification tools: reachability, budget, withdrawn skip, verdicts.

These are the runtime tests for C6 and #45. The unit tests in
``tests/agents/test_verifier.py`` pin the pure gate; these drive the seam the
reviewing agent actually calls, because a verification path that exists but is
not registered on the MCP server verifies nothing (#96).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.mcp.verification import (
    record_finding_verdict_tool,
    verify_agent_findings_tool,
)
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING, finding_fingerprint
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.learnings import learnings_file_path

if TYPE_CHECKING:
    from pathlib import Path

# A migration path puts the run on the `high` blast-radius lane; everything
# else here stays on a lane where one judge may retire a finding.
_HIGH_LANE_DIFF = """diff --git a/migrations/001_add_column.sql b/migrations/001_add_column.sql
--- a/migrations/001_add_column.sql
+++ b/migrations/001_add_column.sql
@@ -1,2 +1,3 @@
 select 1;
+alter table users add column email text;
"""


def _ctx(tmp_path: Path, *, analyzers_ran: bool = True) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    if analyzers_ran:
        state.analyzer_run = AnalyzerRunState(ran=True)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


async def _plan(ctx: ToolContext, findings: list[dict[str, Any]]) -> dict[str, Any]:
    result = await verify_agent_findings_tool(ctx).execute({"findings": findings})
    return json.loads(result.content[0]["text"])


async def _verdict(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    result = await record_finding_verdict_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


def _finding(body: str, *, severity: str = "Critical", path: str = "src/app.py") -> dict[str, Any]:
    return {"path": path, "line": 12, "severity": severity, "body": body}


# ── reachability ──────────────────────────────────────────────────────────────


def test_verification_tools_are_registered_on_every_run(tmp_path: Path) -> None:
    """The seam #96 taught us to check: present in the module, absent from the server."""
    names = {spec.name for spec in build_common_tools(_ctx(tmp_path))}
    assert "verify_agent_findings" in names
    assert "record_finding_verdict" in names


def test_recording_a_verdict_is_denied_to_subagents(tmp_path: Path) -> None:
    """The verifier reports a verdict; only the orchestrator writes it down."""
    specs = {spec.name: spec for spec in build_common_tools(_ctx(tmp_path))}
    assert specs["record_finding_verdict"].mutates is True
    assert specs["verify_agent_findings"].mutates is False


# ── the gate itself (C6) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_authored_critical_finding_reaches_the_verifier(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    payload = await _plan(_ctx(tmp_path), [_finding("this token is logged in plaintext")])

    assert payload["ready"] is True
    assert payload["subagent"] == "mergecraft-verifier"
    assert len(payload["dispatch"]) == 1
    dispatch = payload["dispatch"][0]
    assert dispatch["citedFile"] == str(tmp_path / "src" / "app.py")
    assert "this token is logged in plaintext" in dispatch["prompt"]
    assert WITHDRAWN_FINDINGS_HEADING.removeprefix("## ") in dispatch["prompt"]


@pytest.mark.asyncio
async def test_minor_agent_findings_do_not_earn_a_dispatch(tmp_path: Path) -> None:
    payload = await _plan(_ctx(tmp_path), [_finding("rename this variable", severity="Minor")])
    assert payload["dispatch"] == []
    assert len(payload["skippedBelowSeverity"]) == 1


@pytest.mark.asyncio
async def test_budget_caps_dispatches_at_the_repo_inline_budget(tmp_path: Path) -> None:
    """Twelve Critical findings, an inline budget of 8 — eight go, four do not."""
    findings = [_finding(f"finding number {index}") for index in range(12)]
    payload = await _plan(_ctx(tmp_path), findings)

    assert payload["budget"] == 8
    assert len(payload["dispatch"]) == 8
    assert len(payload["skippedOverBudget"]) == 4
    dispatched = {item["fingerprint"] for item in payload["dispatch"]}
    assert dispatched.isdisjoint(payload["skippedOverBudget"])
    assert len(dispatched | set(payload["skippedOverBudget"])) == 12


@pytest.mark.asyncio
async def test_budget_spends_on_critical_before_major(tmp_path: Path) -> None:
    findings = [_finding(f"major {i}", severity="Major") for i in range(8)]
    findings.append(_finding("the critical one"))
    payload = await _plan(_ctx(tmp_path), findings)

    critical_fp = finding_fingerprint(path="src/app.py", body="the critical one")
    assert critical_fp in {item["fingerprint"] for item in payload["dispatch"]}
    assert critical_fp not in payload["skippedOverBudget"]


@pytest.mark.asyncio
async def test_already_withdrawn_finding_is_never_re_verified(tmp_path: Path) -> None:
    body = "the retry loop double-charges"
    fingerprint = finding_fingerprint(path="src/app.py", body=body)
    learnings = tmp_path / "mergecraft-learnings.md"
    learnings.write_text(
        f"# Learnings\n\n{WITHDRAWN_FINDINGS_HEADING}\n\n"
        f"- Idempotency key makes the retry safe. "
        f"<!-- mergecraft-finding:v1:{fingerprint} -->\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path)
    ctx.tool_state.learnings_file_path = str(learnings)

    payload = await _plan(ctx, [_finding(body)])
    assert payload["dispatch"] == []
    assert payload["skippedWithdrawn"] == [fingerprint]


# ── verdicts (C6 + D14) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drop_verdict_lands_under_the_withdrawn_heading(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    body = "this can never be None"
    fingerprint = finding_fingerprint(path="src/app.py", body=body)

    payload = await _verdict(
        ctx,
        fingerprint=fingerprint,
        verdict="drop",
        reason="The caller already guards the None case at src/app.py:4.",
    )
    assert payload["publishable"] is False
    assert payload["recordedWithdrawn"] is True

    text = (tmp_path / "mergecraft-learnings.md").read_text(encoding="utf-8")
    assert WITHDRAWN_FINDINGS_HEADING in text
    assert "The caller already guards the None case" in text
    assert f"<!-- mergecraft-finding:v1:{fingerprint} -->" in text


@pytest.mark.asyncio
async def test_a_dropped_finding_stays_refuted_on_the_next_run(tmp_path: Path) -> None:
    """The round trip C6 asks for: drop once, skipped forever after."""
    ctx = _ctx(tmp_path)
    body = "this can never be None"
    fingerprint = finding_fingerprint(path="src/app.py", body=body)
    await _verdict(ctx, fingerprint=fingerprint, verdict="drop", reason="Guarded upstream.")

    ctx.tool_state.learnings_file_path = learnings_file_path(str(tmp_path))
    payload = await _plan(ctx, [_finding(body)])
    assert payload["dispatch"] == []
    assert payload["skippedWithdrawn"] == [fingerprint]


@pytest.mark.asyncio
async def test_confirm_verdict_publishes_and_writes_nothing(tmp_path: Path) -> None:
    payload = await _verdict(
        _ctx(tmp_path),
        fingerprint="a" * 24,
        verdict="confirm",
        reason="Reproduced by reading the caller.",
    )
    assert payload["publishable"] is True
    assert payload["recordedWithdrawn"] is False
    assert not (tmp_path / "mergecraft-learnings.md").exists()


@pytest.mark.asyncio
async def test_verdict_records_judge_model_provider_and_rubric_version(tmp_path: Path) -> None:
    """#45's first acceptance criterion, at the seam that produces verdicts."""
    payload = await _verdict(
        _ctx(tmp_path),
        fingerprint="b" * 24,
        verdict="confirm",
        reason="Confirmed.",
    )
    assert payload["judgeProvider"] == "claude"
    assert payload["judgeModel"] == "claude-sonnet-5"
    assert payload["judgeModelPinned"] is True
    assert payload["judgeVersion"]
    assert payload["rubricVersion"]


@pytest.mark.asyncio
async def test_high_stakes_lane_drop_is_escalated_not_withdrawn(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    diff = tmp_path / "pr.diff"
    diff.write_text(_HIGH_LANE_DIFF, encoding="utf-8")
    ctx.tool_state.repos[ctx.tool_state.primary_repo_key].diff_path = str(diff)

    payload = await _verdict(
        ctx,
        fingerprint="c" * 24,
        verdict="drop",
        reason="I could not reproduce it.",
    )
    assert payload["escalatedToHuman"] is True
    assert payload["recordedWithdrawn"] is False
    assert payload["publishable"] is True
    assert not (tmp_path / "mergecraft-learnings.md").exists()


# ── deterministic checks come first (D14 / W13.3) ─────────────────────────────


@pytest.mark.asyncio
async def test_no_dispatch_before_a_deterministic_check_has_run(tmp_path: Path) -> None:
    payload = await _plan(_ctx(tmp_path, analyzers_ran=False), [_finding("boom")])
    assert payload["ready"] is False
    assert payload["dispatch"] == []
    assert "secondary evaluators" in payload["reason"]


@pytest.mark.asyncio
async def test_no_verdict_before_a_deterministic_check_has_run(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, analyzers_ran=False)
    payload = await _verdict(ctx, fingerprint="d" * 24, verdict="drop", reason="nope")
    assert payload["recorded"] is False
    assert not (tmp_path / "mergecraft-learnings.md").exists()


@pytest.mark.asyncio
async def test_static_checks_alone_satisfy_the_ordering_gate(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, analyzers_ran=False)
    ctx.tool_state.static_checks_ran = True
    payload = await _plan(ctx, [_finding("boom")])
    assert payload["ready"] is True
    assert payload["deterministicChecks"] == ["run_static_checks"]
