"""Behavioral checks for the trusted, App-authenticated approval helper."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.approve_app_review import approve

REPO = "acme/demo"
HEAD = "a" * 40
RUN = {
    "id": 123,
    "run_attempt": 2,
    "event": "pull_request_target",
    "conclusion": "success",
    "head_sha": "b" * 40,  # PRT base SHA must never select the reviewed commit.
    "run_started_at": "2026-09-08T01:00:00Z",
    "repository": {"full_name": REPO},
    "pull_requests": [{"number": 7, "head": {"sha": HEAD}}],
}
PR = {
    "state": "open",
    "draft": False,
    "head": {"sha": HEAD, "repo": {"full_name": REPO}},
    "base": {"repo": {"full_name": REPO}},
}
CHECK = {
    "id": 10,
    "external_id": "123:2",
    "name": "mergecraft-approval",
    "app": {"id": 42},
    "head_sha": HEAD,
    "details_url": "https://github.com/acme/demo/actions/runs/123",
    "status": "completed",
    "conclusion": "success",
    "completed_at": "2026-09-08T01:01:00Z",
}


def execute(
    *,
    run: dict[str, Any] | None = None,
    checks: list[dict[str, Any]] | None = None,
    heads: list[dict[str, Any]] | None = None,
    app_id: str = "42",
    server: str = "https://github.com",
) -> tuple[bool, list[dict[str, Any]]]:
    posted: list[dict[str, Any]] = []
    snapshots = iter(heads if heads is not None else [PR, PR])

    def api(path: str, body: dict[str, Any] | None) -> Any:
        if body is not None:
            assert path == "/repos/acme/demo/pulls/7/reviews"
            posted.append(body)
            return {"id": 8}
        if path.endswith("/pulls/7"):
            return next(snapshots)
        assert path == f"/repos/acme/demo/commits/{HEAD}/check-runs?per_page=100"
        return {"check_runs": checks if checks is not None else [CHECK]}

    result = approve(api, repo=REPO, run=run or RUN, app_id=app_id, server=server)
    return result, posted


def test_app_approval_uses_pr_head_not_prt_workflow_head() -> None:
    result, posted = execute()
    assert result
    assert posted[0]["commit_id"] == HEAD
    assert posted[0]["event"] == "APPROVE"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("app", {"id": 99}),
        ("external_id", "123:1"),
        ("external_id", None),
        ("head_sha", "b" * 40),
        ("details_url", "https://github.com/acme/demo/actions/runs/122"),
        ("completed_at", "2026-09-07T01:01:00Z"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("name", "unrelated"),
    ],
)
def test_app_approval_rejects_unattributable_verdict(key: str, value: Any) -> None:
    check = {**CHECK, key: value}
    assert execute(checks=[check]) == (False, [])


@pytest.mark.parametrize("moment", ["before_check", "before_submit"])
def test_app_approval_rejects_head_movement(moment: str) -> None:
    moved = deepcopy(PR)
    moved["head"]["sha"] = "c" * 40
    assert execute(heads=[moved] if moment == "before_check" else [PR, moved]) == (False, [])


def test_app_approval_does_not_reuse_earlier_success_after_failure() -> None:
    assert execute(checks=[CHECK, {**CHECK, "id": 11, "conclusion": "failure"}]) == (False, [])


@pytest.mark.parametrize("app_id", ["", "name", "42\n"])
def test_app_approval_requires_numeric_configured_identity(app_id: str) -> None:
    assert execute(app_id=app_id) == (False, [])


def test_app_approval_rejects_fork_even_with_associated_pr() -> None:
    fork = deepcopy(PR)
    fork["head"]["repo"]["full_name"] = "someone/demo"
    assert execute(heads=[fork]) == (False, [])


@pytest.mark.parametrize("key", ["run_started_at", "id", "pull_requests", "repository"])
def test_app_approval_missing_provenance_fails_closed(key: str) -> None:
    run = deepcopy(RUN)
    run.pop(key)
    assert execute(run=run) == (False, [])


def test_app_tokens_are_refreshed_per_attempt_and_fallback_is_preserved() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/mergecraft.yml").read_text())
    job = workflow["jobs"]["review"]
    assert "head.repo.full_name == github.repository" in job["env"]["HAS_APP"]
    steps = job["steps"]
    for provider in ("nous", "codex", "claude"):
        mint = next(step for step in steps if step.get("id") == f"app_token_{provider}")
        review = next(step for step in steps if step.get("id") == f"mergecraft_{provider}")
        assert steps.index(mint) + 1 == steps.index(review)
        assert "env.HAS_APP == 'true'" in mint["if"]
        assert " ".join(review["if"].split()) in " ".join(mint["if"].split())
        assert (
            f"steps.app_token_{provider}.outputs.app-slug"
            in review["env"]["MERGECRAFT_REVIEWER_BOT_LOGIN"]
        )
        assert mint["with"]["repositories"] == "${{ github.event.repository.name }}"
        assert not mint["with"].get("skip-token-revoke")
        assert mint["continue-on-error"] is True
        assert (
            review["with"]["token"]
            == f"${{{{ steps.app_token_{provider}.outputs.token || github.token }}}}"
        )


def test_app_approval_only_executes_trusted_default_branch_code() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/mergecraft-approve.yml").read_text())
    steps = workflow["jobs"]["approve"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] is False
    assert all(step["if"] == "env.HAS_APP == 'true'" for step in steps)
    assert "MERGECRAFT_REVIEWER_PAT" not in str(workflow)


def test_app_approval_pending_newer_verdict_cannot_reuse_success() -> None:
    assert execute(
        checks=[
            CHECK,
            {**CHECK, "id": 11, "status": "in_progress", "conclusion": None, "completed_at": None},
        ]
    ) == (False, [])


def test_enterprise_run_url_is_required_and_accepted() -> None:
    server = "https://github.example.test"
    accepted, posted = execute(server=server)
    assert not accepted
    assert not posted
    check = deepcopy(CHECK)
    check["details_url"] = f"{server}/acme/demo/actions/runs/123"
    accepted, posted = execute(server=server, checks=[check])
    assert accepted
    assert len(posted) == 1


@pytest.mark.parametrize("server", ["https://github.com", "https://github.example.test"])
def test_api_uses_explicit_host_and_ephemeral_token(
    monkeypatch: pytest.MonkeyPatch, server: str
) -> None:
    from scripts import approve_app_review as helper

    monkeypatch.setenv("GITHUB_SERVER_URL", server)
    monkeypatch.setenv("GH_TOKEN", "nonsecret-app-fixture")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "wrong-cached-fixture")
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: Any) -> Any:
        calls.append(args)
        assert kwargs["env"]["GH_ENTERPRISE_TOKEN"] == "nonsecret-app-fixture"
        assert kwargs["env"]["GH_TOKEN"] == "nonsecret-app-fixture"
        return helper.subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(helper.subprocess, "run", run)
    assert helper._api("/repos/acme/demo", None) == {}
    assert calls == [
        ["gh", "api", "--hostname", server.removeprefix("https://"), "/repos/acme/demo"]
    ]


def test_api_does_not_fall_back_to_cached_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import approve_app_review as helper

    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example.test")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="explicit App token"):
        helper._api("/repos/acme/demo", None)
