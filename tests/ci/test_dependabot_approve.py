"""Code-owner approval for Dependabot pull requests (``dependabot-approve.yml``).

Fixtures mirror the real REST payloads (``pulls``, ``compare``, ``reviews`` and
the ``application/vnd.github.diff`` media type) and the shape of #1547: one
Dependabot commit, then a maintainer's "Update branch" merge. Nothing here
touches the network: the API is injected.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import pytest
from scripts.approve_dependabot_prs import (
    DIFF_MEDIA_TYPE,
    TOKEN_ENV,
    ApiError,
    canonical_diff,
    main,
    sweep,
)

from tests.ci.workflow_support import (
    WORKFLOWS,
    assert_third_party_uses_sha_pinned,
    job,
    load_workflow,
    workflow_on,
)

REPO = "alexhawat/mergeCraft"
APPROVER = "sevn-one"
DEPENDABOT_SHA = "d" * 40
MERGE_SHA = "e" * 40
MERGE_BASE = "b" * 40


def _diff(start: int, blob: str, *, new_from: str = "3fe1a0b", extra: str = "") -> str:
    """The #1547 Dockerfile hunk, at line ``start`` and blob id ``blob``."""
    lines = [
        "diff --git a/docker/Dockerfile b/docker/Dockerfile",
        f"index {blob}..{blob[::-1]} 100644",
        "--- a/docker/Dockerfile",
        "+++ b/docker/Dockerfile",
        f"@@ -{start},7 +{start},7 @@ RUN tar -xzf /tmp/gh-source.tar.gz",
        '         -ldflags="-s -w"',
        "         -o /out/gh ./cmd/gh",
        " ",
        "-FROM python:3.14-slim-bookworm@sha256:9ab8d9c",
        f"+FROM python:3.14-slim-bookworm@sha256:{new_from}",
        " ",
        " ARG SOURCE_DATE_EPOCH",
        ' ARG SOURCE_REVISION=""',
    ]
    text = "\n".join(lines) + "\n"
    return text + extra


_EXTRA_FILE = (
    "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
    "index 3333333..4444444 100644\n"
    "--- a/.github/workflows/ci.yml\n"
    "+++ b/.github/workflows/ci.yml\n"
    "@@ -1 +1 @@\n"
    "-name: CI\n"
    "+name: CI (edited in a merge)\n"
)


def _commit(
    sha: str,
    *,
    author: str = "dependabot[bot]",
    committer: str = "web-flow",
    verified: bool = True,
    parents: int = 1,
) -> dict[str, Any]:
    return {
        "sha": sha,
        "author": {"login": author},
        "committer": {"login": committer},
        "commit": {"verification": {"verified": verified, "reason": "valid"}},
        "parents": [{"sha": f"{index}" * 40} for index in range(parents)],
    }


def _pr(head_sha: str = MERGE_SHA, **overrides: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 1547,
        "state": "open",
        "draft": False,
        "user": {"login": "dependabot[bot]"},
        "base": {"ref": "main"},
        "head": {
            "sha": head_sha,
            "ref": "dependabot/docker/docker/main/python-3fe1a0b",
            "repo": {"full_name": REPO},
        },
    }
    pr.update(overrides)
    return pr


def _route(path: str) -> str:
    """Drop pagination parameters so a route is keyed by what it asks for."""
    base, _, query = path.partition("?")
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(query) if k not in ("per_page", "page")]
    return f"{base}?{urllib.parse.urlencode(sorted(kept))}" if kept else base


class _FakeApi:
    """In-memory REST API. ``fail`` / ``fail_posts`` hold routes that answer with an error."""

    def __init__(self, routes: dict[str, Any], texts: dict[str, str]) -> None:
        self.routes = routes
        self.texts = texts
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.fail: set[str] = set()
        self.fail_posts: set[str] = set()

    def get(self, path: str) -> Any:
        route = _route(path)
        if route in self.fail:
            raise ApiError(500, f"GET {route}: HTTP 500")
        if dict(urllib.parse.parse_qsl(path.partition("?")[2])).get("page", "1") != "1":
            return []
        if route not in self.routes:
            raise AssertionError(f"unexpected GET {route}")
        return self.routes[route]

    def get_text(self, path: str, accept: str) -> str:
        assert accept == DIFF_MEDIA_TYPE
        if path in self.fail:
            raise ApiError(406, f"GET {path}: HTTP 406 diff too large")
        return self.texts[path]

    def post(self, path: str, body: dict[str, Any]) -> Any:
        if path in self.fail_posts:
            raise ApiError(422, f"POST {path}: HTTP 422")
        self.posts.append((path, body))
        return {"id": 1, "state": "APPROVED"}


def _api(
    *,
    pr: dict[str, Any] | None = None,
    commits: list[dict[str, Any]] | None = None,
    net: str | None = None,
    reviews: list[dict[str, Any]] | None = None,
    others: list[dict[str, Any]] | None = None,
) -> _FakeApi:
    """The #1547 shape by default: Dependabot's commit plus an Update-branch merge."""
    pr = pr or _pr()
    head = pr["head"]["sha"]
    if commits is None:
        commits = [
            _commit(DEPENDABOT_SHA),
            _commit(MERGE_SHA, author="alexhawat", parents=2),
        ]
    routes: dict[str, Any] = {
        f"repos/{REPO}": {"default_branch": "main"},
        "user": {"login": APPROVER},
        f"repos/{REPO}/pulls?base=main&state=open": [pr, *(others or [])],
        f"repos/{REPO}/pulls/{pr['number']}": pr,
        f"repos/{REPO}/pulls/{pr['number']}/reviews": reviews or [],
        f"repos/{REPO}/compare/main...{head}": {
            "status": "diverged",
            "total_commits": len(commits),
            "merge_base_commit": {"sha": MERGE_BASE},
            "commits": commits,
        },
    }
    texts = {
        f"repos/{REPO}/commits/{DEPENDABOT_SHA}": _diff(23, "1111111"),
        # Main moved the hunk down two lines and changed the blob ids.
        f"repos/{REPO}/compare/{MERGE_BASE}...{head}": net
        if net is not None
        else _diff(25, "5555555"),
    }
    return _FakeApi(routes, texts)


def _run(api: _FakeApi, **kwargs: Any) -> tuple[list[Any], list[str]]:
    return sweep(api, REPO, approver=APPROVER, **kwargs)


# --- canonical_diff -----------------------------------------------------------


def test_canonical_diff_ignores_line_numbers_and_blob_ids() -> None:
    assert canonical_diff(_diff(23, "1111111")) == canonical_diff(_diff(910, "9999999"))


def test_canonical_diff_sees_a_different_change() -> None:
    assert canonical_diff(_diff(23, "1111111")) != canonical_diff(
        _diff(23, "1111111", new_from="0000bad")
    )


def test_canonical_diff_sees_a_moved_change() -> None:
    """Context lines pin where a change sits, not just what it says."""
    moved = _diff(23, "1111111").replace("./cmd/gh", "./cmd/other")
    assert canonical_diff(moved) != canonical_diff(_diff(23, "1111111"))


def test_canonical_diff_sees_an_extra_file() -> None:
    assert len(canonical_diff(_diff(23, "1111111", extra=_EXTRA_FILE))) == 2


def test_canonical_diff_splits_on_newline_only() -> None:
    """A carriage return inside a changed line is content, not a line break."""
    crlf = _diff(23, "1111111").replace("3fe1a0b", "3fe1a0b\r")
    assert canonical_diff(crlf) != canonical_diff(_diff(23, "1111111"))
    assert len(canonical_diff(crlf)[0]) == len(canonical_diff(_diff(23, "1111111"))[0])


# --- approval ------------------------------------------------------------------


def test_approves_dependabot_commit_after_an_update_branch_merge() -> None:
    """#1547: Dependabot's commit, then a maintainer's clean "Update branch" merge."""
    api = _api()
    decisions, failures = _run(api)
    assert failures == []
    assert [d.approve for d in decisions] == [True]
    assert decisions[0].commit == DEPENDABOT_SHA
    [(path, body)] = api.posts
    assert path == f"repos/{REPO}/pulls/1547/reviews"
    assert body["event"] == "APPROVE"
    assert body["commit_id"] == MERGE_SHA, "the approval must name the head it checked"
    assert DEPENDABOT_SHA in body["body"]


def test_approves_a_lone_dependabot_commit() -> None:
    api = _api(pr=_pr(head_sha=DEPENDABOT_SHA), commits=[_commit(DEPENDABOT_SHA)])
    decisions, _ = _run(api)
    assert decisions[0].approve
    assert api.posts[0][1]["commit_id"] == DEPENDABOT_SHA


def test_review_body_links_the_run() -> None:
    api = _api()
    _run(api, run_url="https://github.com/o/r/actions/runs/1")
    assert "https://github.com/o/r/actions/runs/1" in api.posts[0][1]["body"]


def test_dry_run_decides_but_posts_nothing() -> None:
    api = _api()
    decisions, _ = _run(api, dry_run=True)
    assert decisions[0].approve
    assert api.posts == []


# --- what makes a pull request ineligible --------------------------------------


def test_skips_when_a_merge_commit_carries_a_change_of_its_own() -> None:
    """A conflict resolution can edit files; the net diff must still be Dependabot's."""
    api = _api(net=_diff(25, "5555555", extra=_EXTRA_FILE))
    decisions, _ = _run(api)
    assert not decisions[0].approve
    assert "net diff is not exactly" in decisions[0].reason
    assert api.posts == []


def test_skips_when_a_merge_commit_rewrites_dependabots_line() -> None:
    api = _api(net=_diff(25, "5555555", new_from="0000bad"))
    decisions, _ = _run(api)
    assert not decisions[0].approve
    assert api.posts == []


def test_skips_a_human_non_merge_commit() -> None:
    commits = [_commit(DEPENDABOT_SHA), _commit(MERGE_SHA, author="alexhawat")]
    decisions, _ = _run(_api(commits=commits))
    assert not decisions[0].approve
    assert "2 non-merge commits" in decisions[0].reason


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"author": "alexhawat"}, "not authored by dependabot[bot]"),
        ({"committer": "alexhawat"}, "not committed by GitHub"),
        ({"verified": False}, "no verified signature"),
    ],
)
def test_skips_a_commit_that_is_not_provably_dependabots(
    overrides: dict[str, Any], reason: str
) -> None:
    commits = [_commit(DEPENDABOT_SHA, **overrides), _commit(MERGE_SHA, parents=2)]
    api = _api(commits=commits)
    decisions, _ = _run(api)
    assert not decisions[0].approve
    assert reason in decisions[0].reason
    assert api.posts == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"user": {"login": "alexhawat"}}, "not authored by dependabot[bot]"),
        ({"state": "closed"}, "not open"),
        ({"draft": True}, "draft"),
        ({"base": {"ref": "pre-0.0.1"}}, "base is not main"),
        (
            {"head": {"sha": MERGE_SHA, "ref": "dependabot/x", "repo": {"full_name": "f/k"}}},
            "not in this repository",
        ),
        (
            {"head": {"sha": MERGE_SHA, "ref": "bump-python", "repo": {"full_name": REPO}}},
            "does not start with dependabot/",
        ),
    ],
)
def test_skips_a_pull_request_that_is_not_a_dependabot_one(
    overrides: dict[str, Any], reason: str
) -> None:
    api = _api(pr=_pr(**overrides))
    decisions, _ = sweep(api, REPO, approver=APPROVER, only=1547)
    assert not decisions[0].approve
    assert reason in decisions[0].reason
    assert api.posts == []


def test_listing_keeps_only_dependabot_pull_requests() -> None:
    human = _pr(number=1600, user={"login": "alexhawat"})
    decisions, _ = _run(_api(others=[human]))
    assert [d.number for d in decisions] == [1547]


def test_skips_when_a_reviewer_requested_changes() -> None:
    reviews = [{"user": {"login": "alexhawat"}, "state": "CHANGES_REQUESTED"}]
    decisions, _ = _run(_api(reviews=reviews))
    assert not decisions[0].approve
    assert decisions[0].reason == "alexhawat requested changes"


@pytest.mark.parametrize("later", ["APPROVED", "DISMISSED"])
def test_a_later_review_lifts_a_change_request(later: str) -> None:
    reviews = [
        {"user": {"login": "alexhawat"}, "state": "CHANGES_REQUESTED"},
        {"user": {"login": "alexhawat"}, "state": "COMMENTED"},
        {"user": {"login": "alexhawat"}, "state": later},
    ]
    decisions, _ = _run(_api(reviews=reviews))
    assert decisions[0].approve


def test_skips_when_already_approved_at_this_head() -> None:
    reviews = [{"user": {"login": APPROVER}, "state": "APPROVED", "commit_id": MERGE_SHA}]
    api = _api(reviews=reviews)
    decisions, _ = _run(api)
    assert not decisions[0].approve
    assert "already approved" in decisions[0].reason
    assert api.posts == []


def test_reapproves_when_the_approval_was_for_an_older_head() -> None:
    reviews = [{"user": {"login": APPROVER}, "state": "APPROVED", "commit_id": DEPENDABOT_SHA}]
    api = _api(reviews=reviews)
    decisions, _ = _run(api)
    assert decisions[0].approve
    assert len(api.posts) == 1


def test_skips_when_the_approver_pushed_the_head() -> None:
    """``require_last_push_approval`` would not count the pusher's own approval."""
    commits = [_commit(DEPENDABOT_SHA), _commit(MERGE_SHA, author=APPROVER, parents=2)]
    decisions, _ = _run(_api(commits=commits))
    assert not decisions[0].approve
    assert "authored the head commit" in decisions[0].reason


def test_skips_when_the_comparison_is_truncated() -> None:
    api = _api()
    api.routes[f"repos/{REPO}/compare/main...{MERGE_SHA}"]["total_commits"] = 300
    decisions, _ = _run(api)
    assert decisions[0].reason == "too many commits to inspect"


def test_an_unreadable_diff_skips_that_pull_request_only() -> None:
    api = _api(others=[_pr(number=1548, head_sha=MERGE_SHA)])
    api.routes[f"repos/{REPO}/pulls/1548/reviews"] = []
    api.fail.add(f"repos/{REPO}/compare/{MERGE_BASE}...{MERGE_SHA}")
    decisions, failures = _run(api)
    assert failures == []
    assert [d.approve for d in decisions] == [False, False]
    assert all("could not inspect" in d.reason for d in decisions)


# --- CLI -----------------------------------------------------------------------


def _main(api: _FakeApi, *argv: str, token: str = "ghp_test") -> int:
    environ = {TOKEN_ENV: token} if token else {}
    return main(["--repository", REPO, *argv], environ=environ, api_factory=lambda _t: api)


def test_main_without_a_token_is_a_notice_not_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(_token: str) -> _FakeApi:
        raise AssertionError("no API client without a token")

    assert main(["--repository", REPO], environ={}, api_factory=refuse) == 0
    assert "::notice::" in capsys.readouterr().out


def test_main_reports_each_decision(capsys: pytest.CaptureFixture[str]) -> None:
    api = _api()
    assert _main(api) == 0
    out = capsys.readouterr().out
    assert f"approver: {APPROVER}" in out
    assert "#1547 approved:" in out


def test_main_dry_run_says_would_approve(capsys: pytest.CaptureFixture[str]) -> None:
    api = _api()
    assert _main(api, "--dry-run") == 0
    assert "#1547 would approve:" in capsys.readouterr().out
    assert api.posts == []


def test_main_refused_token_exits_2() -> None:
    api = _api()
    api.fail.add("user")
    assert _main(api) == 2


def test_main_failed_approval_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    api = _api()
    api.fail_posts.add(f"repos/{REPO}/pulls/1547/reviews")
    assert _main(api) == 1
    assert "#1547: approval failed" in capsys.readouterr().err


# --- the workflow --------------------------------------------------------------

_WORKFLOW = "dependabot-approve.yml"


def test_workflow_runs_only_the_default_branch_definition() -> None:
    """``pull_request`` would run a PR's own copy of this file with the token."""
    triggers = workflow_on(load_workflow(_WORKFLOW))
    assert set(triggers) == {"schedule", "workflow_dispatch"}


def test_token_lives_in_the_main_only_environment() -> None:
    doc = load_workflow(_WORKFLOW)
    approve = job(doc, "approve")
    assert approve["environment"] == "dependabot-approval"
    assert "refs/heads/main" in approve["if"]
    for name, spec in doc["jobs"].items():
        uses_secret = TOKEN_ENV in json.dumps(spec)
        assert uses_secret == (name == "approve"), name


def test_no_other_workflow_reads_the_token() -> None:
    readers = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if f"secrets.{TOKEN_ENV}" in path.read_text(encoding="utf-8")
    ]
    assert readers == [_WORKFLOW]


def test_workflow_checks_out_only_the_script_without_credentials() -> None:
    steps = job(load_workflow(_WORKFLOW), "approve")["steps"]
    checkout = steps[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["sparse-checkout"] == "scripts/approve_dependabot_prs.py"
    assert "scripts/approve_dependabot_prs.py" in steps[1]["run"]
    assert "ref" not in checkout["with"], "never check out a pull-request head"


def test_workflow_permissions_are_read_only() -> None:
    doc = load_workflow(_WORKFLOW)
    assert doc["permissions"] == {"contents": "read"}
    assert job(doc, "approve")["permissions"] == {"contents": "read"}
    assert job(doc, "candidates")["permissions"] == {"pull-requests": "read"}


def test_workflow_inputs_reach_the_shell_through_env() -> None:
    run = job(load_workflow(_WORKFLOW), "approve")["steps"][1]["run"]
    assert "${{" not in run


def test_workflow_third_party_uses_are_sha_pinned() -> None:
    assert_third_party_uses_sha_pinned(_WORKFLOW)
