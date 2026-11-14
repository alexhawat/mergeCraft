"""Exercise merge queue approval through the real Action entry point."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

import mergecraft.main as main_mod
import mergecraft.merge_queue as merge_queue_mod
from mergecraft import __version__
from mergecraft.classify.reapproval import ReviewStamp, parse_review_stamp
from mergecraft.config.settings import RepoSettings
from mergecraft.config.settings_snapshot import RepoSettingsSnapshot
from mergecraft.mcp.context import PayloadEvent
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.reapproval import review_policy_digest
from mergecraft.scm.github import create_github_scm
from mergecraft.utils.status_checks import report_status_checks
from tests.support.github_fakes import StrictGitHubClient
from tests.support.tool_context import make_tool_context

if TYPE_CHECKING:
    from mergecraft.evidence.packet import MergeEvidencePacket

_REPOSITORY = "acme/demo"
_HEAD = "a" * 40
_BASE = "b" * 40
_PR = "c" * 40
_PRIOR_PR = "d" * 40
_PRIOR_GROUP = "e" * 40
_WORKFLOW = ".github/workflows/mergecraft.yml"
_WORKFLOW_BLOB = "f" * 40
_APP = "mergecraft-reviewer"
_REF = f"refs/heads/gh-readonly-queue/main/pr-42-{_BASE}"


class _GitHub(StrictGitHubClient):
    def __init__(self) -> None:
        super().__init__()
        self.checks: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}
        self.closed = False

    async def get(self, path: str, **kwargs: Any) -> Any:
        return self.responses.get(path, {})

    async def post(self, path: str, **kwargs: Any) -> Any:
        assert path == f"/repos/{_REPOSITORY}/check-runs"
        self.checks.append(kwargs["json"])
        return {}

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


@pytest.fixture
def queue_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _GitHub:
    gh = _GitHub()
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps(
            {
                "action": "checks_requested",
                "repository": {"full_name": _REPOSITORY},
                "merge_group": {
                    "head_sha": _HEAD,
                    "head_ref": _REF,
                    "base_sha": _BASE,
                    "base_ref": "refs/heads/main",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPOSITORY)
    monkeypatch.setenv("GITHUB_SHA", _HEAD)
    monkeypatch.setenv("GITHUB_REF", _REF)
    monkeypatch.setenv("INPUT_STATUS_CHECKS", "enabled")
    monkeypatch.setenv("INPUT_TOKEN", "ghs_fake")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{_REPOSITORY}/{_WORKFLOW}@{_REF}")
    monkeypatch.setattr(main_mod, "GitHubClient", lambda _token: gh)

    async def unexpected_review(*args: object) -> None:
        pytest.fail("merge_group must never dispatch the review runtime")

    def unexpected_workspace(*args: object) -> None:
        pytest.fail("merge_group must not prepare a review workspace")

    monkeypatch.setattr(main_mod, "_setup_run", unexpected_review)
    monkeypatch.setattr(main_mod, "prepare_workspace_for_agent", unexpected_workspace)
    return gh


async def test_unproven_merge_group_posts_failure_on_group_sha(queue_event: _GitHub) -> None:
    result = await main_mod.main()

    assert not result.success
    [check] = queue_event.checks
    assert check["name"] == "mergecraft-approval"
    assert check["head_sha"] == _HEAD
    assert check["conclusion"] == "failure"


async def test_mismatched_group_sha_does_not_post_to_either_commit(
    queue_event: _GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)

    result = await main_mod.main()

    assert not result.success
    assert queue_event.checks == []


def _ref(name: str, commit: str) -> dict[str, Any]:
    return {"ref": name, "object": {"sha": commit, "type": "commit"}}


def _entry(name: str, oid: str, *, mode: str = "100644") -> dict[str, str]:
    return {"path": name, "sha": oid, "mode": mode, "type": "tree" if mode == "040000" else "blob"}


def _tree(gh: _GitHub, commit: str, oid: str, entries: list[dict[str, str]]) -> None:
    tree = {"truncated": False, "tree": entries}
    root = f"/repos/{_REPOSITORY}"
    gh.responses[f"{root}/git/trees/{oid}"] = tree
    gh.responses[f"{root}/git/trees/{commit}"] = tree
    gh.responses[f"{root}/git/commits/{commit}"] = {"sha": commit, "tree": {"sha": oid}}


def _ref_response(gh: _GitHub, name: str, commit: str) -> None:
    gh.responses[f"/repos/{_REPOSITORY}/git/ref/{name.removeprefix('refs/')}"] = _ref(name, commit)


def _compare(gh: _GitHub, base: str, head: str, merge_base: str) -> None:
    gh.responses[f"/repos/{_REPOSITORY}/compare/{base}...{head}"] = {
        "merge_base_commit": {"sha": merge_base}
    }


def _pull(gh: _GitHub, number: int, head: str) -> None:
    gh.responses[f"/repos/{_REPOSITORY}/pulls/{number}"] = {
        "number": number,
        "state": "open",
        "base": {"ref": "main", "sha": _BASE, "repo": {"full_name": _REPOSITORY}},
        "head": {"sha": head},
    }


def _approval(gh: _GitHub, head: str, stamp: ReviewStamp, *, app: str = _APP) -> dict[str, Any]:
    check = {
        "id": 10,
        "head_sha": head,
        "name": "mergecraft-approval",
        "app": {"slug": app},
        "status": "completed",
        "conclusion": "success",
        "details_url": "https://github.com/acme/demo/actions/runs/10",
        "output": {"summary": "\n".join(stamp.lines())},
    }
    gh.responses[f"/repos/{_REPOSITORY}/commits/{head}/check-runs"] = {
        "total_count": 1,
        "check_runs": [check],
    }
    return check


async def _evidence(gh: _GitHub, *, prelude: str = _BASE) -> ReviewStamp:
    root = f"/repos/{_REPOSITORY}"
    _ref_response(gh, "refs/heads/main", _BASE)
    _ref_response(gh, f"refs/heads/gh-readonly-queue/main/pr-42-{prelude}", _HEAD)
    _pull(gh, 42, _PR)
    gh.responses[f"{root}/contents/.mergecraft/config.yaml"] = {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(
            b"review:\n  mergeQueue:\n    trustedCheckApps: [mergecraft-reviewer]\n"
        ).decode(),
    }
    directory = _entry(".github", "1" * 40, mode="040000")
    gh.responses[f"{root}/git/trees/{'1' * 40}"] = {
        "truncated": False,
        "tree": [_entry("workflows", "2" * 40, mode="040000")],
    }
    gh.responses[f"{root}/git/trees/{'2' * 40}"] = {
        "truncated": False,
        "tree": [_entry("mergecraft.yml", _WORKFLOW_BLOB)],
    }
    original, changed = _entry("code", "3" * 40), _entry("code", "4" * 40)
    config = _entry(".mergecraft", "0" * 40, mode="040000")
    gh.responses[f"{root}/git/trees/{'0' * 40}"] = {
        "truncated": False,
        "tree": [_entry("config.yaml", "f" * 40)],
    }
    _tree(gh, _BASE, "5" * 40, [directory, config, original])
    _tree(gh, _PR, "6" * 40, [directory, config, changed])
    _tree(gh, _HEAD, "6" * 40, [directory, config, changed])
    _compare(gh, _BASE, _PR, _BASE)
    _compare(gh, prelude, _HEAD, prelude)
    digest = await review_policy_digest(
        create_github_scm("ghs_fake", client=gh),
        "acme",
        "demo",
        _BASE,
        workflow_path=_WORKFLOW,
        version=__version__,
    )
    stamp = ReviewStamp(42, "main", digest, _BASE)
    _approval(gh, _PR, stamp)
    return stamp


async def test_single_approved_pr_posts_success_without_dispatch(queue_event: _GitHub) -> None:
    await _evidence(queue_event)

    result = await main_mod.main()

    assert result.success
    [check] = queue_event.checks
    assert check["head_sha"] == _HEAD
    assert check["conclusion"] == "success"
    assert f"PR #42: {_PR}" in check["output"]["summary"]


@pytest.mark.parametrize(
    "variant",
    ["shared-app", "newer-failure", "stale-head", "stale-policy", "mode"],
    ids=["shared-app", "newer-failure", "stale-head", "stale-policy", "mode"],
)
async def test_refuses_invalid_approval_or_changed_tree(queue_event: _GitHub, variant: str) -> None:
    stamp = await _evidence(queue_event)
    root = f"/repos/{_REPOSITORY}"
    match variant:
        case "shared-app":
            _approval(queue_event, _PR, stamp, app="github-actions")
        case "newer-failure":
            old_check = _approval(queue_event, _PR, stamp)
            queue_event.responses[f"{root}/commits/{_PR}/check-runs"] = {
                "total_count": 2,
                "check_runs": [old_check, {**old_check, "id": 11, "conclusion": "failure"}],
            }
        case "stale-head":
            _pull(queue_event, 42, _PRIOR_PR)
        case "stale-policy":
            _approval(queue_event, _PR, replace(stamp, policy_digest="0" * 64))
        case "mode":
            directory = _entry(".github", "1" * 40, mode="040000")
            config = _entry(".mergecraft", "0" * 40, mode="040000")
            _tree(
                queue_event,
                _HEAD,
                "7" * 40,
                [directory, config, _entry("code", "4" * 40, mode="100755")],
            )

    result = await main_mod.main()

    assert not result.success
    [check] = queue_event.checks
    assert check["head_sha"] == _HEAD
    assert check["conclusion"] == "failure"


def _replace_event_base(new_ref: str, new_base: str) -> None:
    event_file = Path(os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(event_file.read_text(encoding="utf-8"))
    event["merge_group"].update(head_ref=new_ref, base_sha=new_base)
    event_file.write_text(json.dumps(event), encoding="utf-8")


@pytest.mark.parametrize("prior_approved", [True, False], ids=["all-approved", "mixed"])
async def test_group_requires_approval_for_every_predictive_layer(
    queue_event: _GitHub, monkeypatch: pytest.MonkeyPatch, prior_approved: bool
) -> None:
    stamp = await _evidence(queue_event, prelude=_PRIOR_GROUP)
    new_ref = _REF.replace(_BASE, _PRIOR_GROUP)
    _replace_event_base(new_ref, _PRIOR_GROUP)
    monkeypatch.setenv("GITHUB_REF", new_ref)
    previous_ref = f"refs/heads/gh-readonly-queue/main/pr-41-{_BASE}"
    _ref_response(queue_event, previous_ref, _PRIOR_GROUP)
    queue_event.responses[
        f"/repos/{_REPOSITORY}/git/matching-refs/heads/gh-readonly-queue/main/"
    ] = [
        _ref(previous_ref, _PRIOR_GROUP),
        _ref(new_ref, _HEAD),
    ]
    _pull(queue_event, 41, _PRIOR_PR)
    _compare(queue_event, _BASE, _PRIOR_PR, _BASE)
    _compare(queue_event, _BASE, _PRIOR_GROUP, _BASE)
    directory = _entry(".github", "1" * 40, mode="040000")
    config = _entry(".mergecraft", "0" * 40, mode="040000")
    extra = _entry("other", "8" * 40)
    original, changed = _entry("code", "3" * 40), _entry("code", "4" * 40)
    _tree(queue_event, _PRIOR_PR, "9" * 40, [directory, config, original, extra])
    _tree(queue_event, _PRIOR_GROUP, "9" * 40, [directory, config, original, extra])
    _tree(queue_event, _HEAD, "7" * 40, [directory, config, changed, extra])
    if prior_approved:
        _approval(queue_event, _PRIOR_PR, replace(stamp, pull_number=41))

    result = await main_mod.main()

    assert result.success is prior_approved
    [check] = queue_event.checks
    assert check["conclusion"] == ("success" if prior_approved else "failure")


async def test_proof_timeout_posts_a_blocking_check(
    queue_event: _GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow_api(*args: str, **kwargs: Any) -> Any:
        await asyncio.Event().wait()

    monkeypatch.setattr(queue_event, "get", slow_api)
    monkeypatch.setattr(main_mod, "_MERGE_GROUP_PROOF_TIMEOUT_S", 0.01)

    result = await main_mod.main()

    assert not result.success
    assert result.error == "Merge group evidence verification timed out."
    [check] = queue_event.checks
    assert check["head_sha"] == _HEAD
    assert check["conclusion"] == "failure"
    assert queue_event.closed


async def test_tree_walk_budget_fails_closed(
    queue_event: _GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _evidence(queue_event)
    monkeypatch.setattr(merge_queue_mod, "_MAX_WALKED_ENTRIES", 1)

    result = await main_mod.main()

    assert not result.success
    assert result.error == "The Git tree delta exceeds the traversal budget"
    assert queue_event.checks[0]["conclusion"] == "failure"


@pytest.mark.parametrize(
    ("source_event", "workflow_sha", "stamped"),
    [
        ("pull_request_target", _BASE, True),
        ("pull_request", _BASE, False),
        ("pull_request_target", _HEAD, False),
    ],
    ids=["target-workflow", "head-workflow", "different-workflow-revision"],
)
async def test_source_approval_check_only_stamps_an_operator_owned_review(
    queue_event: _GitHub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_event: str,
    workflow_sha: str,
    stamped: bool,
) -> None:
    expected = await _evidence(queue_event)
    monkeypatch.setenv("GITHUB_EVENT_NAME", source_event)
    monkeypatch.setenv("GITHUB_SHA", _BASE)
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", workflow_sha)
    ctx = make_tool_context(
        tmp_path,
        trust_tier="trusted",
        github=queue_event,
        event=PayloadEvent(trigger=source_event, issue_number=42, is_pr=True),
    )
    ctx.payload.status_checks = True
    ctx.gh_event = {"pull_request": queue_event.responses[f"/repos/{_REPOSITORY}/pulls/42"]}
    ctx.repo_settings_snapshot = RepoSettingsSnapshot(
        settings=RepoSettings.model_validate(
            {"review": {"mergeQueue": {"trustedCheckApps": [_APP]}}}
        ),
        config_hash="pinned",
        repo_root=tmp_path,
        operator_owned=source_event == "pull_request_target",
    )
    state = primary_repo_state(ctx.tool_state)
    state.issue_number = 42
    state.checkout_sha = _PR
    state.reviewed_merge_base = _BASE
    packet = cast(
        "MergeEvidencePacket",
        SimpleNamespace(
            coverage=None,
            decision=SimpleNamespace(verdict="success", reason="approved"),
            findings=[],
            ignored_review_paths=[],
            run_health=None,
            reviewed_head_sha=_PR,
            triage=None,
        ),
    )

    await report_status_checks(ctx, run_succeeded=True, packet=packet)

    _, check = queue_event.checks
    assert check["head_sha"] == _PR
    assert check["conclusion"] == "success"
    assert parse_review_stamp(check["output"]["summary"]) == (expected if stamped else None)


async def test_policy_symlink_cannot_reuse_prior_approval(queue_event: _GitHub) -> None:
    await _evidence(queue_event)
    # Git's tree includes the symlink object, but not the contents it reads.
    policy = queue_event.responses[f"/repos/{_REPOSITORY}/git/trees/{'0' * 40}"]
    policy["tree"].append(_entry("learnings.md", "8" * 40, mode="120000"))

    result = await main_mod.main()

    assert not result.success
    assert (
        result.error
        == "The queue policy tree contains an entry that is not a regular file or directory"
    )
    assert queue_event.checks[0]["conclusion"] == "failure"
