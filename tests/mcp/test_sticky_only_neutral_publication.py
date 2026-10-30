"""#1078 — a non-terminal neutral rung publishes to the sticky only.

The fallback chain used to post one formal review per rung. Without verifiable
authorship (#1029) a later rung cannot supersede an earlier review, so the
workflow marks a rung that a fallback will replace (OpenCode Go -> Codex) with
``MERGECRAFT_STICKY_ONLY_NEUTRAL``. A neutral decision on that rung must not
post a formal review; the deterministic record goes to the sticky progress
comment at finalize. Non-neutral decisions are untouched.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from tests.support.tool_context import bind_review_publication_scope, github_client_from_ctx

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool, should_publish_sticky_only
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_ENV = "MERGECRAFT_STICKY_ONLY_NEUTRAL"


class _RecordingGitHub(GitHubClient):
    """Records review writes instead of sending them."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.reviews: list[dict[str, Any]] = []

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.reviews.append({"pull_number": pull_number, **payload})
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
        trust_tier="trusted",
    )
    bind_review_publication_scope(tool_ctx)
    return tool_ctx


def _packet(verdict: str) -> SimpleNamespace:
    return SimpleNamespace(decision=SimpleNamespace(verdict=verdict))


def test_sticky_only_requires_both_the_env_flag_and_a_neutral_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    assert should_publish_sticky_only(_packet("neutral")) is False

    monkeypatch.setenv(_ENV, "true")
    assert should_publish_sticky_only(_packet("neutral")) is True
    assert should_publish_sticky_only(_packet("success")) is False
    assert should_publish_sticky_only(_packet("failure")) is False
    assert should_publish_sticky_only(SimpleNamespace(decision=None)) is False


@pytest.mark.asyncio
async def test_a_neutral_decision_does_not_post_a_formal_review(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, "true")
    monkeypatch.setattr(
        "mergecraft.evidence.run_packet.resolve_prepared_run_packet",
        lambda *_args, **_kwargs: _packet("neutral"),
    )

    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Review body.", "approved": True}
    )

    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload.get("stickyOnly") is True
    assert payload.get("published") is False
    reviewer = github_client_from_ctx(ctx)
    assert reviewer.reviews == [], "a non-terminal neutral rung must not post a review"
    assert ctx.tool_state.review_publication_sticky_only is True
    assert ctx.tool_state.review_publication_entrypoint == "sticky_only_neutral"
