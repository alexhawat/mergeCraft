"""Repository identity, not fork ancestry, determines a PR's trust floor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.config.trust_policy import is_fork_pull_request, resolve_trust_policy

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("head", "base", "fork"),
    [
        ({"id": 42, "fork": True}, {"id": 42, "fork": True}, False),
        ({"id": 42, "fork": False}, {"id": 99}, True),
        ({"full_name": "ACME/fork", "fork": True}, {"full_name": "acme/FORK"}, False),
        ({"full_name": "other/repo", "fork": False}, {"full_name": "acme/repo"}, True),
        ({"id": 42, "full_name": "a/b"}, {"id": 99, "full_name": "a/b"}, True),
        ({"id": 42, "full_name": "old/name"}, {"id": 42, "full_name": "new/name"}, False),
        ({"fork": False}, {"id": 42}, True),
        ({"id": True}, {"id": 1}, True),
        ({"id": 0}, {"id": 0}, True),
        ({"full_name": ""}, {"full_name": ""}, True),
        (None, {"id": 42}, True),
        ({"id": 42}, None, True),
    ],
)
def test_pull_repository_identity(
    head: dict[str, Any] | None, base: dict[str, Any] | None, fork: bool
) -> None:
    event = {"pull_request": {"head": {"repo": head}, "base": {"repo": base}}}
    assert is_fork_pull_request(event) is fork
    assert derive_trust_tier(event=event, event_name="pull_request") == (
        "untrusted" if fork else "trusted"
    )


@pytest.mark.parametrize("event_name", ["pull_request", "pull_request_target", "issue_comment"])
def test_internal_branch_on_a_fork_keeps_configured_trust(tmp_path: Path, event_name: str) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text('trust:\n  selfReview: "full"\n')
    repo = {"id": 42, "full_name": "acme/fork", "fork": True}
    event = {
        "pull_request": {"head": {"repo": repo}, "base": {"repo": repo}},
        "comment": {"author_association": "MEMBER"},
    }
    policy = resolve_trust_policy(event=event, event_name=event_name, config_root=tmp_path)
    assert policy.execution_trust == "trusted"
    assert policy.authority_trust == "trusted"


async def test_checkout_accepts_internal_pr_in_a_fork(tmp_path: Path) -> None:
    import asyncio

    from mergecraft.mcp.checkout import checkout_pr_tool
    from tests.mcp.test_checkout_target_binding import _ctx_for, _pr_repo, _StubGitHub

    class SameForkGitHub(_StubGitHub):
        async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
            pull = await super().get_pull(owner, repo, pull_number)
            own_repo = {"id": 42, "full_name": f"{owner}/{repo}", "fork": True}
            pull["head"]["repo"] = own_repo
            pull["base"]["repo"] = own_repo
            return pull

        async def get(self, path: str, **kwargs: Any) -> Any:
            return [] if path.endswith(("/reviews", "/comments")) else {}

    repo = await asyncio.to_thread(_pr_repo, tmp_path)
    ctx = _ctx_for(repo, SameForkGitHub(fork=False), tmp_path, bound_pr=1)
    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert not result.is_error, result.content
