"""W4 — live GitHub checkout + commit-status roundtrip."""

from __future__ import annotations

import asyncio
import os

import pytest

from mergecraft.utils.github import GitHubClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.xfail(
        reason="green after W4: GitHub checkout + status-check roundtrip",
        strict=False,
    ),
]


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
            context="mergecraft-w4-live-probe",
            description="live roundtrip probe",
        )
        assert isinstance(created, dict)
        assert created.get("state") == "success"
        assert created.get("context") == "mergecraft-w4-live-probe"

        listed = await client.get(f"/repos/{owner}/{name}/commits/{sha}/status")
        assert isinstance(listed, dict)
        statuses = listed.get("statuses") or listed.get("check_runs") or []
        contexts = [row.get("context") for row in statuses if isinstance(row, dict)]
        assert "mergecraft-w4-live-probe" in contexts, f"status not visible after create: {listed}"

        first, second = await asyncio.gather(
            client.create_status(
                owner,
                name,
                sha,
                state="success",
                context="mergecraft-w4-live-probe",
                description="concurrent-a",
            ),
            client.create_status(
                owner,
                name,
                sha,
                state="success",
                context="mergecraft-w4-live-probe",
                description="concurrent-b",
            ),
        )
        assert isinstance(first, dict)
        assert first.get("state") == "success"
        assert isinstance(second, dict)
        assert second.get("state") == "success"
    finally:
        await client.aclose()
