"""Recall merge into analyzer run state (RC10, D1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.tool_context import github_client_from_ctx

from mergecraft.analyzers.budget import DEFERRED_SECTION_HEADING
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.convergence_runtime import merge_recall_findings_into_analyzer_run
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.mcp.verification import record_finding_verdict_tool, verify_agent_findings_tool
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import finding_fingerprint
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingGitHub(GitHubClient):
    """Captures the review payload instead of sending it."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.review_payload: dict[str, Any] = {}

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payload = payload
        return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=_RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def test_merge_recall_preserves_analyzer_overflow_in_deferred_section() -> None:
    """Recall merge must re-render deferred HTML from all deferred rows, not recall-only."""
    overflow_path = "src/overflow.py"
    overflow_body = "Analyzer overflow finding."
    recall_path = "src/recall.py"
    recall_body = "Novel recall finding."

    analyzer_run = AnalyzerRunState(
        ran=True,
        deferred_findings=[
            {
                "path": overflow_path,
                "line": 9,
                "body": overflow_body,
                "severity": "Major",
            }
        ],
        deferred_section=(
            f"{DEFERRED_SECTION_HEADING}\n\n"
            "<details><summary>Non-blocking deferred findings</summary>\n\n"
            f"**Major** `{overflow_path}:9` — {overflow_body}\n\n"
            "</details>"
        ),
    )

    merge_recall_findings_into_analyzer_run(
        analyzer_run,
        draft=[{"path": "src/draft.py", "line": 1, "body": "Already drafted."}],
        recalled=[{"path": recall_path, "line": 12, "body": recall_body, "severity": "Major"}],
    )

    assert analyzer_run.deferred_section is not None
    assert overflow_body in analyzer_run.deferred_section
    assert recall_body in analyzer_run.deferred_section
    assert len(analyzer_run.deferred_findings) == 2


def test_merge_recall_skips_findings_already_in_deferred() -> None:
    """Recall must not duplicate analyzer overflow rows already in deferred_findings."""
    overflow_path = "src/overflow.py"
    overflow_body = "Analyzer overflow finding."

    analyzer_run = AnalyzerRunState(
        ran=True,
        deferred_findings=[
            {
                "path": overflow_path,
                "line": 9,
                "body": overflow_body,
                "severity": "Major",
            }
        ],
    )

    merge_recall_findings_into_analyzer_run(
        analyzer_run,
        draft=[{"path": "src/draft.py", "line": 1, "body": "Already drafted."}],
        recalled=[{"path": overflow_path, "line": 9, "body": overflow_body, "severity": "Major"}],
    )

    assert len(analyzer_run.deferred_findings) == 1
    assert analyzer_run.deferred_findings[0]["body"] == overflow_body


@pytest.mark.asyncio
async def test_withdrawn_agent_finding_not_reappears_in_deferred_on_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify → drop → publish with recallPass: dropped finding stays out of deferred."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("review:\n  recallPass: true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    dropped_body = "this can never be None"
    dropped_fp = finding_fingerprint(path="src/app.py", body=dropped_body)
    recall_body = "Timeout never assigned before the retry loop runs."

    ctx = _tool_ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(ran=True)

    await verify_agent_findings_tool(ctx).execute(
        {
            "findings": [
                {
                    "path": "src/app.py",
                    "line": 12,
                    "severity": "Major",
                    "body": dropped_body,
                },
                {
                    "path": "src/other.py",
                    "line": 5,
                    "severity": "Major",
                    "body": recall_body,
                },
            ]
        }
    )
    await record_finding_verdict_tool(ctx).execute(
        {
            "fingerprint": dropped_fp,
            "verdict": "drop",
            "reason": "The caller already guards the None case.",
        }
    )

    inline_body = "Separate inline finding for draft coverage."
    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": "Review summary without deferred paste.",
            "comments": [
                {
                    "path": "src/inline.py",
                    "line": 1,
                    "body": inline_body,
                }
            ],
        }
    )

    published_body = str(github_client_from_ctx(ctx).review_payload.get("body") or "")
    assert dropped_body not in published_body
    assert dropped_fp not in published_body
    assert recall_body in published_body
    inline_comments = list(github_client_from_ctx(ctx).review_payload.get("comments") or [])
    inline_paths = {str(row.get("path") or "") for row in inline_comments}
    assert "src/app.py" not in inline_paths
    assert any(inline_body in str(row.get("body") or "") for row in inline_comments)
