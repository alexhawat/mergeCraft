#!/usr/bin/env python3
"""Approve Dependabot pull requests as a code owner (``dependabot-approve.yml``).

``protect-main`` requires a code-owner approval on every pull request to
``main``. Neither rulesets nor CODEOWNERS can condition on the pull-request
author, and an App review (``github-actions[bot]``, the mergeCraft App) never
counts as a code-owner approval (``.github/CODEOWNERS``). So a Dependabot bump
waited on a human code owner like any other change. This sweep supplies that
approval for Dependabot pull requests only, with the token of a code-owner
*user* account. Required checks (``require-ci-on-main``), conversation
resolution and the human merge itself are unchanged.

A pull request is approved only when every one of these holds:

* it is open, not a draft, authored by ``dependabot[bot]``, targets the default
  branch and comes from a ``dependabot/`` branch of this repository;
* its commits are exactly one non-merge commit, authored by
  ``dependabot[bot]``, committed by GitHub (``web-flow``) and signature
  verified, plus any number of merge commits (the "Update branch" button);
* its net diff is that commit's diff, hunk for hunk with line numbers and blob
  ids set aside, so a merge commit (a conflict resolution, say) cannot carry a
  change of its own;
* no reviewer's latest review requests changes (that is how a human holds one
  back);
* the approver has not already approved the current head and did not author
  it (``require_last_push_approval`` would not count such an approval).

Anything else is skipped with the reason logged, and needs a normal code-owner
review. A human non-merge commit keeps a pull request ineligible until
Dependabot rewrites it (``@dependabot recreate``).

Module: scripts.approve_dependabot_prs
Depends: argparse, json, os, sys, urllib, dataclasses

Exports:
    ApiError — a GitHub REST call failed.
    HttpApi — the REST client used in Actions.
    canonical_diff — a unified diff reduced to what must match between two diffs.
    Decision — the outcome for one pull request.
    evaluate — decide one pull request: approve it, or the reason to skip it.
    sweep — evaluate every open Dependabot pull request and approve the eligible ones.
    main — CLI entry; exit 0 ok, 1 an approval failed, 2 GitHub refused the token or listing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

API_ROOT = "https://api.github.com"
DEPENDABOT = "dependabot[bot]"
WEB_FLOW = "web-flow"
BRANCH_PREFIX = "dependabot/"
TOKEN_ENV = "DEPENDABOT_APPROVER_TOKEN"
DIFF_MEDIA_TYPE = "application/vnd.github.diff"
WORKFLOW = ".github/workflows/dependabot-approve.yml"
_PAGE_SIZE = 100


class ApiError(RuntimeError):
    """A GitHub REST call failed (``status`` 0 when no HTTP response arrived)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class Api(Protocol):
    """The three REST calls the sweep needs; tests inject a fake."""

    def get(self, path: str) -> Any: ...

    def get_text(self, path: str, accept: str) -> str: ...

    def post(self, path: str, body: dict[str, Any]) -> Any: ...


Opener = Callable[..., Any]


class HttpApi:
    """Minimal GitHub REST client over ``urllib`` (stdlib only: no bootstrap)."""

    def __init__(self, token: str, *, opener: Opener = urllib.request.urlopen) -> None:
        self._token = token
        self._opener = opener

    def _request(
        self,
        method: str,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
        body: dict[str, Any] | None = None,
    ) -> bytes:
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mergecraft-dependabot-approve",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{API_ROOT}/{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener(request, timeout=30) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, f"{method} {path}: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(0, f"{method} {path}: {exc.reason}") from exc

    def get(self, path: str) -> Any:
        return json.loads(self._request("GET", path))

    def get_text(self, path: str, accept: str) -> str:
        return self._request("GET", path, accept=accept).decode("utf-8", "replace")

    def post(self, path: str, body: dict[str, Any]) -> Any:
        raw = self._request("POST", path, body=body)
        return json.loads(raw) if raw else None


def _paginate(api: Api, path: str) -> list[Any]:
    separator = "&" if "?" in path else "?"
    items: list[Any] = []
    page = 1
    while True:
        batch = api.get(f"{path}{separator}per_page={_PAGE_SIZE}&page={page}")
        items.extend(batch)
        if len(batch) < _PAGE_SIZE:
            return items
        page += 1


def canonical_diff(text: str) -> list[tuple[str, ...]]:
    """Reduce a unified diff to the lines that must match: one tuple per file.

    Each tuple holds the file's header lines (``diff --git``, ``---``/``+++``,
    mode, rename and binary markers) and its hunk bodies, context included.
    Every ``@@`` line is reduced to ``@@`` and ``index`` lines are dropped. The
    same change diffed against a different base therefore reduces to the same
    value, while a change that is added, altered or moved does not. Lines are
    split on ``\\n`` only, as Git does.
    """
    files: list[tuple[str, ...]] = []
    current: list[str] | None = None
    for line in text.rstrip("\n").split("\n"):
        if line.startswith("diff --git "):
            if current is not None:
                files.append(tuple(current))
            current = [line]
        elif current is None or line.startswith("index "):
            continue  # preamble before the first file; blob ids differ per base
        elif line.startswith("@@"):
            current.append("@@")
        else:
            current.append(line)
    if current is not None:
        files.append(tuple(current))
    return files


@dataclass(frozen=True)
class Decision:
    """What the sweep decided for one pull request."""

    number: int
    head_sha: str
    approve: bool
    reason: str
    commit: str = ""  # the Dependabot commit an approval vouches for


def _login(value: Any) -> str:
    return str((value or {}).get("login") or "")


def _review_blocker(reviews: Sequence[dict[str, Any]], approver: str, head_sha: str) -> str:
    """Return why existing reviews rule out an approval, or ``""``."""
    latest: dict[str, dict[str, Any]] = {}
    for review in reviews:
        login = _login(review.get("user"))
        # A comment does not change where a reviewer stands; GitHub agrees.
        if login and review.get("state") not in ("COMMENTED", "PENDING"):
            latest[login] = review
    for login, review in sorted(latest.items()):
        if review.get("state") == "CHANGES_REQUESTED":
            return f"{login} requested changes"
    mine = latest.get(approver)
    if mine and mine.get("state") == "APPROVED" and mine.get("commit_id") == head_sha:
        return f"already approved by {approver} at this head"
    return ""


def _commit_blocker(commit: dict[str, Any]) -> str:
    short = str(commit.get("sha", ""))[:7]
    if _login(commit.get("author")) != DEPENDABOT:
        return f"commit {short} is not authored by {DEPENDABOT}"
    if _login(commit.get("committer")) != WEB_FLOW:
        return f"commit {short} was not committed by GitHub ({WEB_FLOW})"
    verification = (commit.get("commit") or {}).get("verification") or {}
    if verification.get("verified") is not True:
        return f"commit {short} has no verified signature"
    return ""


def evaluate(
    api: Api, repository: str, pr: dict[str, Any], *, default_branch: str, approver: str
) -> Decision:
    """Decide one pull request. Raises ``ApiError`` when GitHub cannot be read."""
    number = int(pr["number"])
    head = pr.get("head") or {}
    head_sha = str(head.get("sha") or "")

    def skip(reason: str) -> Decision:
        return Decision(number, head_sha, approve=False, reason=reason)

    if _login(pr.get("user")) != DEPENDABOT:
        return skip(f"not authored by {DEPENDABOT}")
    if pr.get("state") != "open":
        return skip("not open")
    if pr.get("draft"):
        return skip("draft")
    if (pr.get("base") or {}).get("ref") != default_branch:
        return skip(f"base is not {default_branch}")
    if (head.get("repo") or {}).get("full_name") != repository:
        return skip("head branch is not in this repository")
    if not str(head.get("ref") or "").startswith(BRANCH_PREFIX):
        return skip(f"head branch does not start with {BRANCH_PREFIX}")

    reviews = _paginate(api, f"repos/{repository}/pulls/{number}/reviews")
    blocker = _review_blocker(reviews, approver, head_sha)
    if blocker:
        return skip(blocker)

    # Pin every read to this head: a push mid-sweep can only cause a skip, and
    # an approval names commit_id, so it can never land on a newer head.
    base = urllib.parse.quote(default_branch, safe="")
    compare = api.get(f"repos/{repository}/compare/{base}...{head_sha}")
    commits = list(compare.get("commits") or [])
    if int(compare.get("total_commits", len(commits))) != len(commits):
        return skip("too many commits to inspect")
    merge_base = str((compare.get("merge_base_commit") or {}).get("sha") or "")
    if not merge_base:
        return skip("no merge base with the default branch")
    own = [commit for commit in commits if len(commit.get("parents") or []) == 1]
    if len(own) != 1:
        return skip(f"{len(own)} non-merge commits; expected exactly one, from {DEPENDABOT}")
    blocker = _commit_blocker(own[0])
    if blocker:
        return skip(blocker)
    head_commit = next((commit for commit in commits if commit.get("sha") == head_sha), None)
    if head_commit is None:
        return skip("head commit missing from the comparison")
    if _login(head_commit.get("author")) == approver:
        return skip(f"{approver} authored the head commit, so its approval would not count")

    dependabot_sha = str(own[0]["sha"])
    theirs = canonical_diff(
        api.get_text(f"repos/{repository}/commits/{dependabot_sha}", DIFF_MEDIA_TYPE)
    )
    if not theirs:
        return skip(f"commit {dependabot_sha[:7]} has an empty diff")
    net = canonical_diff(
        api.get_text(f"repos/{repository}/compare/{merge_base}...{head_sha}", DIFF_MEDIA_TYPE)
    )
    if net != theirs:
        return skip(f"net diff is not exactly commit {dependabot_sha[:7]}")
    return Decision(
        number,
        head_sha,
        approve=True,
        reason=f"only change is {DEPENDABOT}'s verified commit {dependabot_sha[:7]}",
        commit=dependabot_sha,
    )


def _review_body(decision: Decision, run_url: str) -> str:
    lines = [
        f"Automated code-owner approval for a Dependabot pull request (`{WORKFLOW}`).",
        "",
        f"The only change here is {DEPENDABOT}'s verified commit {decision.commit}; any "
        "other commit is a merge that adds nothing of its own. Required checks still "
        "gate the merge, and a person still merges it. To hold this one back, request "
        "changes.",
    ]
    if run_url:
        lines += ["", f"Run: {run_url}"]
    return "\n".join(lines)


def sweep(
    api: Api,
    repository: str,
    *,
    approver: str,
    only: int | None = None,
    dry_run: bool = False,
    run_url: str = "",
) -> tuple[list[Decision], list[str]]:
    """Evaluate open Dependabot pull requests and approve the eligible ones.

    Returns every decision and the approvals that failed. A pull request that
    cannot be read is skipped, not failed; listing errors propagate.
    """
    default_branch = str(api.get(f"repos/{repository}")["default_branch"])
    if only is not None:
        pulls = [api.get(f"repos/{repository}/pulls/{only}")]
    else:
        base = urllib.parse.quote(default_branch, safe="")
        listed = _paginate(api, f"repos/{repository}/pulls?state=open&base={base}")
        pulls = [pr for pr in listed if _login(pr.get("user")) == DEPENDABOT]
    decisions: list[Decision] = []
    failures: list[str] = []
    for pr in sorted(pulls, key=lambda item: int(item["number"])):
        try:
            decision = evaluate(
                api, repository, pr, default_branch=default_branch, approver=approver
            )
        except ApiError as exc:
            head_sha = str((pr.get("head") or {}).get("sha") or "")
            decision = Decision(int(pr["number"]), head_sha, False, f"could not inspect: {exc}")
        decisions.append(decision)
        if not decision.approve or dry_run:
            continue
        try:
            api.post(
                f"repos/{repository}/pulls/{decision.number}/reviews",
                {
                    "commit_id": decision.head_sha,
                    "event": "APPROVE",
                    "body": _review_body(decision, run_url),
                },
            )
        except ApiError as exc:
            failures.append(f"#{decision.number}: approval failed: {exc}")
    return decisions, failures


def _run_url(environ: Mapping[str, str]) -> str:
    server = environ.get("GITHUB_SERVER_URL", "")
    repository = environ.get("GITHUB_REPOSITORY", "")
    run_id = environ.get("GITHUB_RUN_ID", "")
    if server and repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return ""


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    api_factory: Callable[[str], Api] = HttpApi,
) -> int:
    parser = argparse.ArgumentParser(
        description="Approve eligible Dependabot pull requests as a code owner."
    )
    parser.add_argument("--repository", required=True, help="owner/name")
    parser.add_argument("--pr", type=int, default=None, help="only this pull request")
    parser.add_argument("--dry-run", action="store_true", help="decide, but approve nothing")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ

    token = env.get(TOKEN_ENV, "")
    if not token:
        print(
            f"::notice::{TOKEN_ENV} is not configured, so nothing was approved. "
            "Setup: .github/CONTRIBUTING.md, 'Dependabot code-owner approval'."
        )
        return 0
    api = api_factory(token)
    try:
        approver = _login(api.get("user"))
    except ApiError as exc:
        print(f"::error::GitHub refused the approver token: {exc}", file=sys.stderr)
        return 2
    try:
        decisions, failures = sweep(
            api,
            args.repository,
            approver=approver,
            only=args.pr,
            dry_run=args.dry_run,
            run_url=_run_url(env),
        )
    except ApiError as exc:
        print(f"::error::could not list pull requests: {exc}", file=sys.stderr)
        return 2

    verb = "would approve" if args.dry_run else "approved"
    print(f"approver: {approver}; {len(decisions)} Dependabot pull request(s)")
    for decision in decisions:
        outcome = verb if decision.approve else "skipped"
        print(f"#{decision.number} {outcome}: {decision.reason}")
    for failure in failures:
        print(f"::error::{failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
