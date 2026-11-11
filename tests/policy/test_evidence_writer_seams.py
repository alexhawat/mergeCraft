"""The writers behind the evidence producers' tool-state seams, driven for real.

The producers are pure over three ``ToolState`` fields; these tests drive the code
that fills them, so a producer can never be green over a field nothing writes:

* ``main._read_linked_issues(ctx)`` fills ``ToolState.linked_issues`` once at run
  start from ``GitHubClient.closing_issues(owner, repo, number)`` — a tuple of
  ``mergecraft.scm.types.LinkedIssue`` (``number``, ``author_login``, ``body``),
  ``()`` for a pull request that closes nothing, ``None`` for anything not fully
  read (no pull request, a failed or malformed answer, more than one page).
* ``GitHubClient.closing_issues`` asks GraphQL for ``closingIssuesReferences``
  with ``first: 25`` and ``pageInfo { hasNextPage }``, and each issue's
  ``number``, ``body`` and ``author { login }``.
* ``checkout_pr`` records ``ToolState.linked_repo_base_manifest`` and
  ``ToolState.linked_repo_review`` from the base manifest it reads and the
  linked-repo review it runs.

The linked-issue writers are written before they exist, so those tests are red
until they land.
"""

from __future__ import annotations

import importlib
import json
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.scm.github import create_github_scm
from mergecraft.utils.github import GitHubClient
from tests.support.github_fakes import StrictGitHubClient

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _GraphQL(StrictGitHubClient):
    """A client whose GraphQL answers with a canned ``data`` object, or raises."""

    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        super().__init__(token="test-token")
        self.answer = answer
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append({"query": query, **dict(variables or {})})
        if self.error is not None:
            raise self.error
        return dict(self.answer or {})


def _page(nodes: list[Any], *, next_page: bool = False) -> dict[str, Any]:
    return {
        "repository": {
            "pullRequest": {
                "closingIssuesReferences": {
                    "pageInfo": {"hasNextPage": next_page},
                    "nodes": nodes,
                }
            }
        }
    }


def _node(number: int, body: str | None, login: str) -> dict[str, Any]:
    return {"number": number, "body": body, "author": {"login": login}}


def _run_ctx(client: GitHubClient, *, pr: int | None = 7) -> Any:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    return SimpleNamespace(
        tool_state=state,
        run_context=SimpleNamespace(repo=SimpleNamespace(owner="acme", name="demo")),
        pr_number=pr,
        scm=create_github_scm("test-token", client=client),
    )


def _triples(issues: Any) -> list[tuple[int, str, str]]:
    return [(issue.number, issue.author_login, issue.body) for issue in issues]


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


# ---------------------------------------------------------------------------
# run start: main._read_linked_issues
# ---------------------------------------------------------------------------


async def test_run_start_records_each_closing_issue_with_its_author() -> None:
    """Two closing issues become two ``LinkedIssue`` rows, in GitHub's order."""
    main = importlib.import_module("mergecraft.main")
    client = _GraphQL(
        _page([_node(12, "## Acceptance criteria", "octo-author"), _node(13, None, "second")])
    )
    ctx = _run_ctx(client)

    await main._read_linked_issues(ctx)

    issues = ctx.tool_state.linked_issues
    assert issues is not None
    assert isinstance(issues, tuple)
    assert _triples(issues) == [(12, "octo-author", "## Acceptance criteria"), (13, "second", "")]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert (call["owner"], call["repo"], call["number"]) == ("acme", "demo", 7)


async def test_run_start_records_an_empty_tuple_when_nothing_is_closed() -> None:
    """Closing no issue is a known answer, distinct from not having read."""
    main = importlib.import_module("mergecraft.main")
    ctx = _run_ctx(_GraphQL(_page([])))

    await main._read_linked_issues(ctx)

    assert ctx.tool_state.linked_issues == ()


@pytest.mark.parametrize(
    "client",
    [
        _GraphQL(error=RuntimeError("GraphQL errors: boom")),
        _GraphQL(_page([_node(12, "body", "octo-author")], next_page=True)),
        _GraphQL({"repository": None}),
        _GraphQL(_page(["not an issue"])),
    ],
    ids=["graphql-failure", "has-next-page", "no-pull-request-object", "malformed-node"],
)
async def test_run_start_leaves_linked_issues_unread_on_any_doubt(client: _GraphQL) -> None:
    """A failed, partial or malformed read is ``None``, never a shorter list."""
    main = importlib.import_module("mergecraft.main")
    ctx = _run_ctx(client)
    ctx.tool_state.linked_issues = ()

    await main._read_linked_issues(ctx)

    assert ctx.tool_state.linked_issues is None
    assert len(client.calls) == 1, "the read must have been attempted"


async def test_run_start_without_a_pull_request_reads_nothing() -> None:
    """No pull request, no closing references: no call, and the field stays unread."""
    main = importlib.import_module("mergecraft.main")
    client = _GraphQL(_page([_node(12, "body", "octo-author")]))
    ctx = _run_ctx(client, pr=None)

    await main._read_linked_issues(ctx)

    assert ctx.tool_state.linked_issues is None
    assert client.calls == []


class _CredentialPhaseGitHub(StrictGitHubClient):
    """The client ``_resolve_credentials`` installs: binds the PR, answers closing issues."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.closing_calls: list[tuple[str, str, int]] = []
        self.pull_calls: list[int] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        from tests.test_main_phases import _pull_metadata

        self.pull_calls.append(pull_number)
        return _pull_metadata(number=pull_number, fork=False)

    async def closing_issues(self, owner: str, repo: str, number: int) -> Any:
        from tests.support.policy_evidence_fixtures import linked_issue

        self.closing_calls.append((owner, repo, number))
        return (linked_issue("## Acceptance criteria\n\n- [ ] refunds", number=12),)


async def test_the_credential_phase_reads_the_closing_issues_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real run-start phase calls the read, so the field is never dead in production."""
    from mergecraft.config.settings import RepoSettings
    from mergecraft.main import RunContext
    from mergecraft.scm.github import GitHubScmAdapter
    from tests.test_main_phases import (
        _comment_on_pr_event,
        _FakeTokenRef,
        _run_context_data,
    )

    main = importlib.import_module("mergecraft.main")
    client = _CredentialPhaseGitHub()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")

    async def _fake_resolve_tokens(**_kwargs: Any) -> _FakeTokenRef:
        return _FakeTokenRef()

    monkeypatch.setattr(main, "resolve_tokens", _fake_resolve_tokens)
    monkeypatch.setattr(main, "GitHubClient", lambda *a, **k: client)
    monkeypatch.setattr(main, "create_github_scm", lambda *a, **k: GitHubScmAdapter(client))
    ctx = RunContext(
        settings=RepoSettings(),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        run_context=_run_context_data(),
        gh_event=_comment_on_pr_event(number=7),
        payload={"push": "restricted", "shell": "restricted"},
        scm=GitHubScmAdapter(client),
    )
    ctx.pr_number = 7
    assert ctx.tool_state is not None
    assert ctx.tool_state.linked_issues is None

    await main._resolve_credentials(ctx)

    assert client.closing_calls == [("acme", "demo", 7)]
    issues = ctx.tool_state.linked_issues
    assert issues is not None
    assert [(issue.number, issue.author_login) for issue in issues] == [(12, "octo-author")]


# ---------------------------------------------------------------------------
# GitHubClient.closing_issues over a real transport
# ---------------------------------------------------------------------------


def _transport_client(answer: dict[str, Any], seen: list[dict[str, Any]]) -> GitHubClient:
    def _respond(request: httpx.Request) -> httpx.Response:
        seen.append(
            {"method": request.method, "path": request.url.path, **json.loads(request.content)}
        )
        return httpx.Response(200, json={"data": answer})

    raw = httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(_respond)
    )
    return GitHubClient("test-token", client=raw)


async def test_closing_issues_asks_for_one_bounded_page_with_authors() -> None:
    """The query names the closing references, 25 per page, and each issue's author."""
    seen: list[dict[str, Any]] = []
    client = _transport_client(_page([_node(12, "body", "octo-author")]), seen)

    issues = await client.closing_issues("acme", "demo", 7)

    assert issues is not None
    assert _triples(issues) == [(12, "octo-author", "body")]
    assert len(seen) == 1
    request = seen[0]
    assert (request["method"], request["path"]) == ("POST", "/graphql")
    query = " ".join(str(request["query"]).split())
    for fragment in ("closingIssuesReferences", "hasNextPage", "number", "body", "author", "login"):
        assert fragment in query, f"the query must ask for {fragment}: {query}"
    variables = request["variables"]
    assert variables["first"] == 25
    assert (variables["owner"], variables["repo"], variables["number"]) == ("acme", "demo", 7)


async def test_closing_issues_refuses_a_second_page() -> None:
    """More closing issues than one page is "not fully read", never the first page."""
    seen: list[dict[str, Any]] = []
    client = _transport_client(_page([_node(12, "body", "octo-author")], next_page=True), seen)

    assert await client.closing_issues("acme", "demo", 7) is None
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# checkout_pr records the linked-repo state the xrepo producer reads
# ---------------------------------------------------------------------------


async def test_checkout_records_the_base_manifest_and_the_linked_repo_review(
    tmp_path: Path,
) -> None:
    """A real checkout of a repository whose base declares a linked repository."""
    from tests.mcp.test_checkout import _checkout, _ctx_for, _StubGitHub
    from tests.xrepo.support import write_linked_repos_manifest

    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "evidence-tests@example.test")
    _git(work, "config", "user.name", "Evidence Tests")
    _git(work, "config", "commit.gpgsign", "false")
    write_linked_repos_manifest(
        work, repos=[{"owner": "acme", "name": "contracts", "commit": "c" * 40}]
    )
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "base with a linked-repo manifest")
    _git(work, "branch", "-M", "base")
    _git(work, "checkout", "-b", "feature")
    (work / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "feature")
    head = _git(work, "rev-parse", "HEAD")
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    ctx = _ctx_for(clone, _StubGitHub(head_sha=head, reviews=[]), tmp_path, mode="Review")
    assert ctx.tool_state.linked_repo_base_manifest is None
    assert ctx.tool_state.linked_repo_review is None

    await _checkout(ctx)

    base = ctx.tool_state.linked_repo_base_manifest
    review = ctx.tool_state.linked_repo_review
    assert base is not None
    assert base.unreadable_reason is None
    assert [entry.slug for entry in base.manifest.repos] == ["acme/contracts"]
    assert review is not None
    assert [entry.slug for entry in review.manifest.repos] == ["acme/contracts"]
    producers = importlib.import_module("mergecraft.policy.evidence_producers")
    evidence = await producers.collect_policy_evidence(ctx, required_keys=["xrepo"])
    # No operator grant covers acme/contracts, so the review omitted it: the producer
    # read the recorded review rather than inventing a clean one.
    assert "acme/contracts" in evidence.absent["xrepo"]
