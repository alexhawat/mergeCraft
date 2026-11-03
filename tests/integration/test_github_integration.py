"""W4 — live GitHub checkout + commit-status roundtrip."""

from __future__ import annotations

import asyncio
import os

import pytest

from mergecraft.utils.github import GitHubClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
]


_PROBE_CONTEXT = "mergecraft-w4-live-probe"
# GitHub's combined-status read is eventually consistent: a status the create
# call has just accepted can be missing from the list for a few seconds (#1018).
_STATUS_VISIBLE_TIMEOUT_S = 30.0
_STATUS_POLL_INTERVAL_S = 2.0


def _status_contexts(listed: object) -> list[object]:
    if not isinstance(listed, dict):
        return []
    statuses = listed.get("statuses") or listed.get("check_runs") or []
    return [row.get("context") for row in statuses if isinstance(row, dict)]


async def _poll_until_status_listed(client: GitHubClient, path: str, context: str) -> object:
    """Re-read the status list until ``context`` appears or the bounded wait runs out."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _STATUS_VISIBLE_TIMEOUT_S
    while True:
        listed = await client.get(path)
        assert isinstance(listed, dict), listed
        if context in _status_contexts(listed) or loop.time() >= deadline:
            return listed
        await asyncio.sleep(_STATUS_POLL_INTERVAL_S)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required for live GitHub integration (D9 — fail, do not skip)")
    return value


@pytest.mark.asyncio
async def test_checkout_and_status_check_roundtrip() -> None:
    token = _require("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("MERGECRAFT_LIVE_GITHUB_REPO", "")
    if "/" not in repo:
        pytest.fail("GITHUB_REPOSITORY or MERGECRAFT_LIVE_GITHUB_REPO (owner/name) is required")
    owner, name = repo.split("/", 1)
    sha = os.environ.get("GITHUB_SHA") or os.environ.get("MERGECRAFT_LIVE_GITHUB_SHA", "")
    if not sha:
        pytest.fail("GITHUB_SHA or MERGECRAFT_LIVE_GITHUB_SHA is required")

    client = GitHubClient(token)
    try:
        meta = await client.get(f"/repos/{owner}/{name}")
        assert isinstance(meta, dict)
        assert meta.get("full_name"), meta

        default_branch = str(meta.get("default_branch") or "pre-0.0.1")
        ref = await client.get(f"/repos/{owner}/{name}/git/ref/heads/{default_branch}")
        assert isinstance(ref, dict), ref

        created = await client.create_status(
            owner,
            name,
            sha,
            state="success",
            context=_PROBE_CONTEXT,
            description="live roundtrip probe",
        )
        assert isinstance(created, dict)
        assert created.get("state") == "success"
        assert created.get("context") == _PROBE_CONTEXT

        listed = await _poll_until_status_listed(
            client, f"/repos/{owner}/{name}/commits/{sha}/status", _PROBE_CONTEXT
        )
        contexts = _status_contexts(listed)
        assert _PROBE_CONTEXT in contexts, (
            f"status not visible {_STATUS_VISIBLE_TIMEOUT_S:.0f}s after create: {listed}"
        )

        first, second = await asyncio.gather(
            client.create_status(
                owner,
                name,
                sha,
                state="success",
                context=_PROBE_CONTEXT,
                description="concurrent-a",
            ),
            client.create_status(
                owner,
                name,
                sha,
                state="success",
                context=_PROBE_CONTEXT,
                description="concurrent-b",
            ),
        )
        assert isinstance(first, dict)
        assert first.get("state") == "success"
        assert isinstance(second, dict)
        assert second.get("state") == "success"
    finally:
        await client.aclose()
