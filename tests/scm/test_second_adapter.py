"""DG9.1 RED suite — second SCM adapter contract (D10 demand-gated).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (DG9.1 RED,
DG9.2 impl).
"""

from __future__ import annotations

import pytest
from tests.scm.conftest import require_scm


def test_one_additional_provider_satisfies_the_protocol() -> None:
    """At least one non-GitHub adapter fully implements ``ScmProvider``."""
    require_scm()
    from mergecraft.scm.gitlab import GitLabScmAdapter
    from mergecraft.scm.protocol import ScmProvider, validate_provider

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    assert isinstance(adapter, ScmProvider)
    report = validate_provider(adapter)
    assert report.complete is True, f"adapter missing protocol operations: {report.missing}"


@pytest.mark.asyncio
async def test_unsupported_capability_is_declared_not_faked() -> None:
    """Providers declare unsupported capabilities instead of emulating GitHub."""
    require_scm()
    from mergecraft.scm.errors import UnsupportedScmCapability
    from mergecraft.scm.gitlab import GitLabScmAdapter
    from mergecraft.scm.protocol import ScmCapability

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    assert adapter.capabilities == frozenset()
    assert ScmCapability.GRAPHQL not in adapter.capabilities

    with pytest.raises(UnsupportedScmCapability) as exc_info:
        await adapter.graphql("query { viewer { username } }")

    message = str(exc_info.value).lower()
    assert "graphql" in message or "unsupported" in message
    assert "capabilit" in message


@pytest.mark.asyncio
async def test_create_review_raises_unsupported_not_fabricated_success() -> None:
    """Review publication must not receive hollow dicts missing GitHub-shaped ``id``."""
    require_scm()
    from mergecraft.scm.errors import UnsupportedScmCapability
    from mergecraft.scm.gitlab import GitLabScmAdapter

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")

    with pytest.raises(UnsupportedScmCapability) as exc_info:
        await adapter.create_review("acme", "demo", 7, event="COMMENT", body="nope")

    assert "create_review" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_gitlab_list_workflow_runs_for_check_suite_is_unsupported_stub() -> None:
    """Protocol names the GitHub helper; GitLab stubs it instead of faking runs."""
    require_scm()
    from mergecraft.scm.errors import UnsupportedScmCapability
    from mergecraft.scm.gitlab import GitLabScmAdapter

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    assert callable(adapter.list_workflow_runs_for_check_suite)
    with pytest.raises(UnsupportedScmCapability) as exc_info:
        await adapter.list_workflow_runs_for_check_suite("acme", "demo", 7)
    assert "list_workflow_runs_for_check_suite" in str(exc_info.value).lower()


def test_tool_context_preserves_explicit_scm_instance(tmp_path: object) -> None:
    """Non-GitHub ``scm`` must not be replaced by an empty GitHub fallback client."""
    require_scm()
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.modes import compute_modes
    from mergecraft.scm.github import GitHubScmAdapter
    from mergecraft.scm.gitlab import GitLabScmAdapter

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    path = str(tmp_path)
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        scm=adapter,
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=path),
        mcp_server_url="",
        tmpdir=path,
    )

    assert ctx.scm is adapter
    assert not isinstance(ctx.scm, GitHubScmAdapter)
