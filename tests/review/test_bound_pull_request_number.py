"""A run that binds its pull request also records that pull request's number (#1056 part 3).

A ``workflow_dispatch`` that names a pull request carries no ``pull_request``, so
the run starts with no pull request number; ``_resolve_credentials`` then fetches
the pull request and binds it into the event (``bind_target_pull_request``). If
only the event is replaced, ``ctx.pr_number`` stays ``None``, the closing-issue
read returns at once, and a ``Scope paths:`` block in a closing issue is ignored:
the run records ``scope.unknown`` and is never ``eligible``.

These tests drive the real ``_resolve_credentials`` with a scripted GitHub client
(the binding fetch and the closing-issue read), then the scope seam, for a
dispatch, a ``@mergecraft review`` comment and a ``pull_request`` control. The
pull request number on ``ctx`` and on the run state is the one the run starts
with, exactly as ``_setup_run`` sets it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mergecraft.main as main_mod
from mergecraft.config.settings import RepoSettings
from mergecraft.main import RunContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.scm.github import GitHubScmAdapter
from mergecraft.scm.types import LinkedIssue
from mergecraft.utils.github import RunContextData

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_PR_BODY_NO_SCOPE = "Fixes the parser.\n\nNo scope block here.\n"
_ISSUE_SCOPE = "Plan.\n\nScope paths:\n- src/mergecraft/requirements/**\n- tests/**\n"


def _pull(number: int) -> dict[str, Any]:
    repo = {"full_name": "acme/demo", "fork": False}
    return {
        "number": number,
        "body": _PR_BODY_NO_SCOPE,
        "head": {"ref": "feature", "sha": "a" * 40, "repo": repo},
        "base": {"ref": "main", "sha": "b" * 40, "repo": repo},
    }


class _ScriptedClient:
    """Answers the binding fetch and the closing-issue read; records each call."""

    def __init__(self, *, pull: dict[str, Any], issues: tuple[LinkedIssue, ...]) -> None:
        self.pull = pull
        self.issues = issues
        self.get_pull_calls: list[tuple[str, str, int]] = []
        self.closing_issues_calls: list[tuple[str, str, int]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        self.get_pull_calls.append((owner, repo, pull_number))
        return dict(self.pull)

    async def closing_issues(
        self, owner: str, repo: str, number: int
    ) -> tuple[LinkedIssue, ...] | None:
        self.closing_issues_calls.append((owner, repo, number))
        return self.issues

    async def aclose(self) -> None:
        return None


class _FakeTokenRef:
    mcp_token = "ghs_fake_mcp_token"
    git_token = "ghs_fake_git_token"
    read_token: str | None = None

    async def aclose(self) -> None:
        return None


def _run_context_data() -> RunContextData:
    return RunContextData.model_validate(
        {
            "repo": {"owner": "acme", "name": "demo", "data": {}},
            "repoSettings": RepoSettings().model_dump(by_alias=True),
            "apiToken": "",
            "oss": True,
            "plan": "none",
        }
    )


async def _drive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    event: dict[str, Any],
    event_name: str,
    start_pr_number: int | None,
    client: _ScriptedClient,
    payload: dict[str, Any] | None = None,
) -> RunContext:
    """Run start as the real run does it: ``_setup_run``'s number, then credentials."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    scm = GitHubScmAdapter(client)  # type: ignore[arg-type]
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    if start_pr_number is not None:
        tool_state.pr_number = start_pr_number
    ctx = RunContext(
        settings=RepoSettings(),
        tool_state=tool_state,
        run_context=_run_context_data(),
        gh_event=event,
        pr_number=start_pr_number,
        payload=payload if payload is not None else {"push": "restricted", "shell": "restricted"},
        scm=scm,
    )

    async def _fake_resolve_tokens(**_kwargs: Any) -> _FakeTokenRef:
        return _FakeTokenRef()

    monkeypatch.setattr(main_mod, "resolve_tokens", _fake_resolve_tokens)
    monkeypatch.setattr(main_mod, "GitHubClient", lambda *a, **k: client)
    monkeypatch.setattr(main_mod, "create_github_scm", lambda *a, **k: scm)
    await main_mod._resolve_credentials(ctx)
    await main_mod._record_scope_declaration(ctx)
    return ctx


def _issues() -> tuple[LinkedIssue, ...]:
    return (
        LinkedIssue(number=11, author_login="maintainer", body="No block."),
        LinkedIssue(number=12, author_login="maintainer", body=_ISSUE_SCOPE),
    )


def _assert_scope_from_the_closing_issue(ctx: RunContext) -> None:
    assert ctx.tool_state is not None
    declaration = ctx.tool_state.scope_declaration
    assert declaration is not None
    assert declaration.declared is True
    assert declaration.globs == ("src/mergecraft/requirements/**", "tests/**")
    assert declaration.source_ref.startswith("linked_issue")


async def test_a_dispatch_naming_a_pull_request_records_its_number_and_closing_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _ScriptedClient(pull=_pull(7), issues=_issues())
    prompt = "Review pull request #7. Please review."

    ctx = await _drive(
        monkeypatch,
        tmp_path,
        event={"action": "workflow_dispatch", "inputs": {}},
        event_name="workflow_dispatch",
        start_pr_number=None,
        client=client,
        payload={"push": "restricted", "shell": "restricted", "prompt": prompt},
    )

    assert ctx.tool_state is not None
    assert ("acme", "demo", 7) in client.get_pull_calls
    assert isinstance(ctx.gh_event, dict)
    assert ctx.gh_event["pull_request"]["number"] == 7
    assert ctx.pr_number == 7
    assert ctx.tool_state.pr_number == 7
    assert client.closing_issues_calls == [("acme", "demo", 7)]
    assert ctx.tool_state.linked_issues == _issues()
    _assert_scope_from_the_closing_issue(ctx)


async def test_a_review_comment_on_a_pull_request_records_its_number_and_closing_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _ScriptedClient(pull=_pull(7), issues=_issues())
    event = {
        "action": "created",
        "issue": {
            "number": 7,
            "body": _PR_BODY_NO_SCOPE,
            "pull_request": {"url": "https://api.github.com/repos/acme/demo/pulls/7"},
        },
        "comment": {"author_association": "OWNER", "body": "@mergecraft review"},
    }

    ctx = await _drive(
        monkeypatch,
        tmp_path,
        event=event,
        event_name="issue_comment",
        start_pr_number=7,
        client=client,
    )

    assert ctx.tool_state is not None
    assert ("acme", "demo", 7) in client.get_pull_calls
    assert ctx.pr_number == 7
    assert ctx.tool_state.pr_number == 7
    assert client.closing_issues_calls == [("acme", "demo", 7)]
    _assert_scope_from_the_closing_issue(ctx)


async def test_a_pull_request_event_keeps_its_own_number_and_is_not_rebound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _ScriptedClient(pull=_pull(99), issues=_issues())
    event = {"action": "synchronize", "number": 7, "pull_request": _pull(7)}

    ctx = await _drive(
        monkeypatch,
        tmp_path,
        event=event,
        event_name="pull_request",
        start_pr_number=7,
        client=client,
    )

    assert ctx.tool_state is not None
    assert client.get_pull_calls == []
    assert ctx.pr_number == 7
    assert ctx.tool_state.pr_number == 7
    assert client.closing_issues_calls == [("acme", "demo", 7)]
    _assert_scope_from_the_closing_issue(ctx)
