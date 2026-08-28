"""Publish-path fail-soft short-id resolution for stored analyzer fingerprints (#493)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.tool_context import bind_review_publication_scope, github_client_from_ctx

from mergecraft.analyzers.finding import make_finding, resolve_finding_short_ids
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_NON_HEX_FINGERPRINT = "zzzzzzzzzzzzzzzzzzzzzzzzzz"
_HEX_FINGERPRINT = "a83f91c2d4e5f6a7b8c9d0e1"


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


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    tool_ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=_RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )
    bind_review_publication_scope(tool_ctx)
    return tool_ctx


def _analyzer_row(*, fingerprint: str, path: str, body: str) -> dict[str, Any]:
    """Build a fully-shaped analyzer finding row, as the pipeline stores them."""
    finding = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="likely",
        message=body,
        path=path,
        start_line=1,
        end_line=1,
        source="analyzer",
        fingerprint=fingerprint,
    )
    return {**finding.model_dump(), "fingerprint": fingerprint}


def _seed_analyzer_run(ctx: ToolContext, rows: list[dict[str, Any]]) -> None:
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=rows,
        mechanical_section="### 🔧 Mechanical findings",
    )


def _capture_loguru_warnings() -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="WARNING")
    return captured, sink_id


@pytest.mark.asyncio
async def test_stored_non_hex_fingerprint_does_not_abort_publication(ctx: ToolContext) -> None:
    """A non-hex fingerprint in analyzer state must not take down the whole review."""
    _seed_analyzer_run(
        ctx,
        [_analyzer_row(fingerprint=_NON_HEX_FINGERPRINT, path="src/bad.py", body="bad fp")],
    )
    spec = create_pull_request_review_tool(ctx)

    await spec.execute({"pull_number": 7, "body": "Review body.", "comments": []})

    payload = github_client_from_ctx(ctx).review_payload
    assert payload, "review was never published"
    assert "Review body." in str(payload.get("body") or "")


@pytest.mark.asyncio
async def test_valid_fingerprints_still_publish_alongside_an_invalid_one(
    ctx: ToolContext,
) -> None:
    """One bad fingerprint must not cost the valid findings their short ids."""
    _seed_analyzer_run(
        ctx,
        [
            _analyzer_row(fingerprint=_NON_HEX_FINGERPRINT, path="src/bad.py", body="bad fp"),
            _analyzer_row(fingerprint=_HEX_FINGERPRINT, path="src/good.py", body="good fp"),
        ],
    )
    spec = create_pull_request_review_tool(ctx)

    await spec.execute({"pull_number": 7, "body": "Review body.", "comments": []})

    published_body = str(github_client_from_ctx(ctx).review_payload.get("body") or "")
    assert "MC-a83f91" in published_body
    assert _NON_HEX_FINGERPRINT not in published_body


@pytest.mark.asyncio
async def test_skipped_fingerprint_is_reported_with_its_path(ctx: ToolContext) -> None:
    """An operator must be able to find the offending finding from the log alone."""
    from loguru import logger as loguru_logger

    _seed_analyzer_run(
        ctx,
        [_analyzer_row(fingerprint=_NON_HEX_FINGERPRINT, path="src/warn_ctx.py", body="bad fp")],
    )
    spec = create_pull_request_review_tool(ctx)
    captured, sink_id = _capture_loguru_warnings()
    try:
        await spec.execute({"pull_number": 7, "body": "Review body.", "comments": []})
    finally:
        loguru_logger.remove(sink_id)

    combined = "\n".join(captured)
    assert _NON_HEX_FINGERPRINT in combined
    assert "src/warn_ctx.py" in combined


def test_strict_resolver_stays_strict() -> None:
    """The shared strict helper must keep rejecting non-hex values (wire export, D9)."""
    with pytest.raises(ValueError, match=r"lowercase hex"):
        resolve_finding_short_ids([_NON_HEX_FINGERPRINT])
