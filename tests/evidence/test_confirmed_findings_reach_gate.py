"""A judge-confirmed agent finding must reach the packet and block the gate.

Observed on PR #631. The reviewing agent raised one finding, it passed through
``verify_agent_findings``, and the judge returned ``confirm``:

    agent-finding verification: 1 queued, 0 already withdrawn, 0 over budget
    judge verdict: confirm on <...> | provider=codex ... lane=medium

The published review said "Request changes" and GitHub recorded
``CHANGES_REQUESTED`` — yet the evidence packet carried 13 findings, every one
``source: "ci"``, and ``decision.verdict`` was ``success``.

Cause: ``record_finding_verdict`` appends the confirmed row to
``ToolState.confirmed_findings``, a list distinct from ``ToolState.agent_findings``.
``load_run_findings`` read only the latter, so ``decide_approval`` — "a pure
function of typed findings" — was handed a set with no agent blocker in it.
``iter_finding_rows`` reads both, which is why the finding still reached the
review body a human reads while the gate approved.

This is not the #623 validation-drop bug. That fix works: a row that fails
``Finding`` validation increments the drop count and emits run-health evidence.
Nothing was dropped here, because the row was never in the list being read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.findings import load_run_findings, load_run_findings_with_drops
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def _ctx(tmp_path: Path) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.analyzer_run = AnalyzerRunState(ran=True, findings=[])
    return ToolContext(
        agent_id="codex",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=631, is_pr=True),
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("codex"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _confirmed_blocker(fingerprint: str = "a1b2c3d4e5f60718") -> dict[str, Any]:
    """A Major agent finding shaped as ``record_finding_verdict`` stores it."""
    return make_finding(
        tool="agent",
        rule_id="correctness",
        category="Functional Correctness",
        severity="Major",
        confidence="certain",
        message="removes a live seam without migrating its callers",
        path="src/mergecraft/utils/github.py",
        start_line=188,
        end_line=188,
        source="agent",
        introduced_by_pr="true",
        fingerprint=fingerprint,
    ).model_dump()


def test_confirmed_finding_reaches_the_packet(tmp_path: Path) -> None:
    """The regression: confirmed-only rows were invisible to the packet."""
    ctx = _ctx(tmp_path)
    ctx.tool_state.confirmed_findings.append(_confirmed_blocker())
    assert ctx.tool_state.agent_findings == [], "the #631 shape: confirmed but not in agent lane"

    findings = load_run_findings(ctx)

    assert [f.rule_id for f in findings] == ["correctness"]
    assert findings[0].severity == "Major"


def test_confirmed_blocker_fails_the_approval_gate(tmp_path: Path) -> None:
    """The consequence that actually mattered: the gate said ``success``."""
    ctx = _ctx(tmp_path)
    ctx.tool_state.confirmed_findings.append(_confirmed_blocker())

    verdict = decide_approval(
        load_run_findings(ctx),
        run_succeeded=True,
        tier="trusted",
    )

    assert verdict == "failure", "a judge-confirmed Major finding must block"


def test_row_in_both_lanes_is_counted_once(tmp_path: Path) -> None:
    """``merge_findings`` dedupes on fingerprint, so the fix cannot double-count."""
    ctx = _ctx(tmp_path)
    row = _confirmed_blocker()
    ctx.tool_state.agent_findings.append(dict(row))
    ctx.tool_state.confirmed_findings.append(dict(row))

    findings, dropped = load_run_findings_with_drops(ctx)

    assert len(findings) == 1
    assert dropped == 0


def test_no_confirmed_rows_still_approves(tmp_path: Path) -> None:
    """The fix must not invent blockers on a clean run."""
    ctx = _ctx(tmp_path)

    assert load_run_findings(ctx) == []
    # An empty finding set is ``neutral``, not ``success`` — absence of evidence
    # is not evidence of approval. The point here is only that the fix adds no
    # blocker of its own.
    assert decide_approval([], run_succeeded=True, tier="trusted") != "failure"
