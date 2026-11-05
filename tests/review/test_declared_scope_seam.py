"""The run reads the declared scope once, before the fast-path gate (#1056 part 3).

``main._record_scope_declaration(ctx)`` stores a ``ScopeDeclaration`` on
``ToolState.scope_declaration``. Sources, first declaration wins: the pull
request body, then the bodies of the issues the pull request closes
(``ToolState.linked_issues``: ``LinkedIssue`` rows from ``mergecraft.scm.types``,
read in order by ``.body``; ``()`` closes nothing, ``None`` was not read; the
GraphQL parsing is covered by the linked-issue tests; the dispatch regression
below exercises the run's read through the client boundary). A body with no
``Scope paths:`` block is not a declaration, so the next source is tried; a
declaration that broke a bound or listed no globs still wins, so a later source
can never widen it. A read that cannot happen leaves the field ``None`` and never
raises into the run.

The body is set on every place the run carries it (the raw payload dict, the
resolved payload, the tool context's payload and the pull-request event), so the
test does not depend on which one the seam reads.
"""

from __future__ import annotations

import inspect
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.config.trust_policy import bind_target_pull_request
from mergecraft.evidence.run_packet import classify_run_blast_radius, scope_signal_for_state
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.scm.types import LinkedIssue
from tests.support import run_main_harness

_BODY_SCOPE = "Implements the parser.\n\nScope paths:\n- src/mergecraft/requirements/**\n"
_ISSUE_SCOPE = "Plan.\n\nScope paths:\n- docs/**\n- tests/**\n"
_NO_SCOPE = "A description with no declared scope.\n- a list item\n"


@pytest.fixture
def main_mod() -> Any:
    return import_module("mergecraft.main")


def _linked_issues(bodies: tuple[str, ...] | None) -> tuple[LinkedIssue, ...] | None:
    """``LinkedIssue`` rows for ``bodies``, numbered from 101."""
    if bodies is None:
        return None
    return tuple(
        LinkedIssue(number=101 + index, author_login="maintainer", body=body)
        for index, body in enumerate(bodies)
    )


def _ctx(body: str | None, issues: tuple[str, ...] | None) -> Any:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    # The field the linked-issue read fills at run start.
    state.linked_issues = _linked_issues(issues)
    resolved = ResolvedPayload(
        event=PayloadEvent(trigger="pull_request", issue_number=3, is_pr=True, body=body)
    )
    return SimpleNamespace(
        settings=RepoSettings(),
        tool_state=state,
        payload={
            "event": {"trigger": "pull_request", "issue_number": 3, "is_pr": True, "body": body}
        },
        ctx_payload=resolved,
        tool_context=SimpleNamespace(
            payload=resolved,
            repo=SimpleNamespace(owner="acme", name="demo"),
            tool_state=state,
        ),
        gh_event={"pull_request": {"number": 3, "body": body}},
        pr_number=3,
        setup_hook_failure=None,
        settings_snapshot_operator_owned=True,
    )


async def _record(main_mod: Any, ctx: Any) -> None:
    outcome = main_mod._record_scope_declaration(ctx)
    if inspect.isawaitable(outcome):
        await outcome


def _declaration(ctx: Any) -> Any:
    return ctx.tool_state.scope_declaration


@pytest.mark.asyncio
async def test_the_pull_request_body_declaration_wins(main_mod: Any) -> None:
    ctx = _ctx(_BODY_SCOPE, (_ISSUE_SCOPE,))

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.declared is True
    assert declaration.globs == ("src/mergecraft/requirements/**",)
    assert declaration.source_ref == "pr_description"


@pytest.mark.asyncio
async def test_the_first_closing_issue_with_a_block_is_used_when_the_body_has_none(
    main_mod: Any,
) -> None:
    ctx = _ctx(_NO_SCOPE, (_NO_SCOPE, _ISSUE_SCOPE, "Scope paths:\n- other/**\n"))

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.globs == ("docs/**", "tests/**")
    assert declaration.source_ref.startswith("linked_issue")
    assert declaration.source_ref != "pr_description"


@pytest.mark.asyncio
async def test_a_run_without_a_pull_request_body_reads_the_closing_issues(
    main_mod: Any,
) -> None:
    ctx = _ctx(None, (_ISSUE_SCOPE,))

    await _record(main_mod, ctx)

    assert _declaration(ctx).globs == ("docs/**", "tests/**")


@pytest.mark.asyncio
async def test_an_invalid_body_declaration_is_not_widened_by_a_closing_issue(
    main_mod: Any,
) -> None:
    ctx = _ctx("Scope paths:\n- **\n", (_ISSUE_SCOPE,))

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.declared is True
    assert declaration.globs == ()
    assert declaration.rejected == ("**",)
    assert declaration.source_ref == "pr_description"


@pytest.mark.asyncio
async def test_an_empty_body_declaration_is_not_replaced_by_a_closing_issue(
    main_mod: Any,
) -> None:
    ctx = _ctx("Scope paths:\n\nNothing listed yet.\n", (_ISSUE_SCOPE,))

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.declared is True
    assert declaration.globs == ()
    assert declaration.source_ref == "pr_description"


@pytest.mark.asyncio
async def test_no_block_anywhere_records_an_undeclared_scope(main_mod: Any) -> None:
    ctx = _ctx(_NO_SCOPE, (_NO_SCOPE,))

    await _record(main_mod, ctx)

    assert hasattr(ctx.tool_state, "scope_declaration")
    assert getattr(_declaration(ctx), "declared", False) is False
    assert getattr(_declaration(ctx), "globs", ()) == ()


@pytest.mark.asyncio
async def test_unread_closing_issues_still_honour_the_body(main_mod: Any) -> None:
    ctx = _ctx(_BODY_SCOPE, None)

    await _record(main_mod, ctx)

    assert _declaration(ctx).globs == ("src/mergecraft/requirements/**",)


@pytest.mark.asyncio
async def test_a_crlf_body_is_read(main_mod: Any) -> None:
    ctx = _ctx(_BODY_SCOPE.replace("\n", "\r\n"), ())

    await _record(main_mod, ctx)

    assert _declaration(ctx).globs == ("src/mergecraft/requirements/**",)


@pytest.mark.asyncio
async def test_a_run_without_tool_state_is_left_alone(main_mod: Any) -> None:
    ctx = _ctx(_BODY_SCOPE, ())
    ctx.tool_state = None

    await _record(main_mod, ctx)

    assert ctx.tool_state is None


@pytest.mark.asyncio
async def test_a_failing_read_leaves_the_scope_unknown_and_never_raises(
    main_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = import_module("mergecraft.requirements.ingest")

    def _boom(body: str) -> Any:
        msg = "parser exploded"
        raise RuntimeError(msg)

    monkeypatch.setattr(ingest, "parse_scope_paths", _boom)
    monkeypatch.setattr(main_mod, "parse_scope_paths", _boom, raising=False)
    ctx = _ctx(_BODY_SCOPE, (_ISSUE_SCOPE,))

    await _record(main_mod, ctx)

    assert hasattr(ctx.tool_state, "scope_declaration")
    assert ctx.tool_state.scope_declaration is None


def test_a_fresh_run_state_has_no_scope_declaration() -> None:
    state = init_tool_state(owner="acme", name="demo", dir=".")

    assert hasattr(state, "scope_declaration")
    assert state.scope_declaration is None


# ── wiring: recorded before the fast-path gate decides ───────────────────────


@pytest.mark.asyncio
async def test_the_declaration_is_recorded_before_the_fast_path_gate(
    main_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(_BODY_SCOPE, ())
    seen: list[Any] = []

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    async def _gate(run_ctx: Any) -> Any:
        seen.append(getattr(run_ctx.tool_state, "scope_declaration", "missing"))
        return main_mod.SkipAgentReview(reason="stop after the gate")

    monkeypatch.setattr(main_mod, "_apply_overrides_and_setup_git", _noop)
    monkeypatch.setattr(main_mod, "ingest_ci_sarif_from_action_env", _noop)
    monkeypatch.setattr(main_mod, "_run_setup_script_phase", _noop)
    monkeypatch.setattr(main_mod, "_triage_gate", _gate)

    outcome = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(outcome, main_mod.SkipAgentReview)
    assert len(seen) == 1
    assert getattr(seen[0], "globs", None) == ("src/mergecraft/requirements/**",)


# ── comment-triggered runs: the comment is never a source ────────────────────

_COMMENT_SCOPE = "@mergecraft review\n\nScope paths:\n- **/*.py\n- src/**\n"


def _comment_ctx(gh_event: dict[str, Any], trigger: str, comment: str) -> Any:
    """A comment-triggered run: the resolved payload's body is the comment, as in production."""
    state = init_tool_state(owner="acme", name="demo", dir=".")
    state.linked_issues = _linked_issues(())
    resolved = ResolvedPayload(
        event=PayloadEvent(trigger=trigger, issue_number=3, is_pr=True, body=comment)
    )
    return SimpleNamespace(
        settings=RepoSettings(),
        tool_state=state,
        payload={"event": {"trigger": trigger, "issue_number": 3, "is_pr": True, "body": comment}},
        ctx_payload=resolved,
        tool_context=SimpleNamespace(
            payload=resolved,
            repo=SimpleNamespace(owner="acme", name="demo"),
            tool_state=state,
        ),
        gh_event=gh_event,
        pr_number=3,
        setup_hook_failure=None,
        settings_snapshot_operator_owned=True,
    )


@pytest.mark.asyncio
async def test_an_issue_comment_run_reads_the_pull_request_body_not_the_comment(
    main_mod: Any,
) -> None:
    event = {
        "issue": {"number": 3, "body": _BODY_SCOPE, "pull_request": {"url": "https://x"}},
        "comment": {"body": _COMMENT_SCOPE},
    }
    ctx = _comment_ctx(event, "issue_comment_created", _COMMENT_SCOPE)

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.globs == ("src/mergecraft/requirements/**",)
    assert declaration.source_ref == "pr_description"


@pytest.mark.asyncio
async def test_a_review_comment_run_reads_the_pull_request_body_not_the_comment(
    main_mod: Any,
) -> None:
    event = {
        "pull_request": {"number": 3, "body": _BODY_SCOPE},
        "comment": {"body": _COMMENT_SCOPE},
    }
    ctx = _comment_ctx(event, "pull_request_review_comment_created", _COMMENT_SCOPE)

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.globs == ("src/mergecraft/requirements/**",)
    assert declaration.source_ref == "pr_description"


@pytest.mark.asyncio
async def test_a_pr_comment_run_records_the_declaration_in_the_issue_body(main_mod: Any) -> None:
    """The ``issue.body`` of a comment on a pull request is the pull request's own body."""
    event = {
        "issue": {"number": 3, "body": _BODY_SCOPE, "pull_request": {"url": "https://x"}},
        "comment": {"body": "@mergecraft review"},
    }
    ctx = _comment_ctx(event, "issue_comment_created", "@mergecraft review")

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.declared is True
    assert declaration.globs == ("src/mergecraft/requirements/**",)
    assert declaration.source_ref == "pr_description"


@pytest.mark.asyncio
async def test_a_block_only_in_the_comment_declares_nothing(main_mod: Any) -> None:
    event = {
        "issue": {"number": 3, "body": _NO_SCOPE, "pull_request": {"url": "https://x"}},
        "comment": {"body": _COMMENT_SCOPE},
    }
    ctx = _comment_ctx(event, "issue_comment_created", _COMMENT_SCOPE)

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.declared is False
    assert declaration.globs == ()


# ── bound events: the PR body is fetched when the event does not carry it ────
#
# On the comment trigger and a PR-naming ``workflow_dispatch`` the run binds the
# target pull request into the event with only ``number``/``head``/``base``
# (``config.trust_policy.bind_target_pull_request``), so the body is not there.
# The seam then reads the pull request through the SCM (``get_pull``) once; a
# failed read leaves the declaration unknown (``None``); an event that carries
# ``body`` is used as is, with no read.

_BOUND_PULL: dict[str, Any] = {
    "number": 3,
    "head": {"ref": "feat", "sha": "c" * 40, "repo": {"full_name": "acme/demo"}},
    "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "acme/demo"}},
}


def _comment_on_pr(body: str, comment: str) -> dict[str, Any]:
    """An ``issue_comment`` event on pull request #3, as GitHub delivers it."""
    return {
        "action": "created",
        "issue": {
            "number": 3,
            "body": body,
            "pull_request": {"url": "https://api.github.com/repos/acme/demo/pulls/3"},
        },
        "comment": {"author_association": "OWNER", "body": comment},
    }


def _dispatch_naming_pr() -> dict[str, Any]:
    """A ``workflow_dispatch`` whose review prompt names pull request #3."""
    return {"action": "workflow_dispatch", "inputs": {"prompt": "Review pull request #3."}}


def _bound(event: dict[str, Any], *, body: str | None) -> dict[str, Any]:
    """Bind the target pull request into ``event`` the way the run does at start."""
    return bind_target_pull_request(event, {**_BOUND_PULL, "body": body})


class _PullScm:
    """Answers ``get_pull`` with ``body`` (or raises ``error``) and records each call."""

    def __init__(self, body: str | None, *, error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        self.calls.append((owner, repo, pull_number))
        if self.error is not None:
            raise self.error
        return {**_BOUND_PULL, "body": self.body}


def _bound_ctx(
    gh_event: dict[str, Any],
    trigger: str,
    resolved_body: str | None,
    scm: _PullScm,
    *,
    issues: tuple[str, ...] = (),
) -> Any:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    state.linked_issues = _linked_issues(issues)
    resolved = ResolvedPayload(
        event=PayloadEvent(trigger=trigger, issue_number=3, is_pr=True, body=resolved_body)
    )
    repo = SimpleNamespace(owner="acme", name="demo")
    return SimpleNamespace(
        settings=RepoSettings(),
        tool_state=state,
        payload={"event": {"trigger": trigger, "issue_number": 3, "is_pr": True}},
        ctx_payload=resolved,
        scm=scm,
        run_context=SimpleNamespace(repo=repo),
        tool_context=SimpleNamespace(payload=resolved, repo=repo, scm=scm, tool_state=state),
        gh_event=gh_event,
        pr_number=3,
        setup_hook_failure=None,
        settings_snapshot_operator_owned=True,
    )


@pytest.mark.asyncio
async def test_a_bound_event_reads_the_pull_request_body_through_the_scm(main_mod: Any) -> None:
    scm = _PullScm(_BODY_SCOPE)
    event = _bound(_comment_on_pr(_BODY_SCOPE, "@mergecraft review"), body=_BODY_SCOPE)
    assert "body" not in event["pull_request"]
    ctx = _bound_ctx(event, "issue_comment_created", "@mergecraft review", scm)

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert declaration.declared is True
    assert declaration.globs == ("src/mergecraft/requirements/**",)
    assert declaration.source_ref == "pr_description"
    assert scm.calls == [("acme", "demo", 3)]


@pytest.mark.asyncio
async def test_a_bound_workflow_dispatch_reads_the_pull_request_body_through_the_scm(
    main_mod: Any,
) -> None:
    scm = _PullScm(_BODY_SCOPE)
    event = _bound(_dispatch_naming_pr(), body=_BODY_SCOPE)
    ctx = _bound_ctx(event, "workflow_dispatch", None, scm)

    await _record(main_mod, ctx)

    assert _declaration(ctx).globs == ("src/mergecraft/requirements/**",)
    assert _declaration(ctx).source_ref == "pr_description"
    assert len(scm.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_in_event", [False, True], ids=["composed-prompt", "event-input"])
async def test_workflow_dispatch_loads_closing_issue_scope_before_the_gate(
    main_mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt_in_event: bool
) -> None:
    """Drive raw dispatch -> PR binding -> closing issues -> scope through ``main()``."""
    closing_calls: list[tuple[str, str, int]] = []
    gate_pr_numbers: list[tuple[int | None, int | None]] = []
    issue = LinkedIssue(number=101, author_login="maintainer", body=_ISSUE_SCOPE)

    class DispatchGitHub(run_main_harness.FakeGitHubClient):
        async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
            assert (owner, repo, pull_number) == ("acme", "demo", 3)
            return {**_BOUND_PULL, "body": _NO_SCOPE}

        async def closing_issues(
            self, owner: str, repo: str, number: int
        ) -> tuple[LinkedIssue, ...]:
            closing_calls.append((owner, repo, number))
            return (issue,)

    async def capture_gate(ctx: Any) -> None:
        gate_pr_numbers.append((ctx.pr_number, ctx.tool_state.pr_number))

    monkeypatch.setattr(run_main_harness, "FakeGitHubClient", DispatchGitHub)
    monkeypatch.setattr(main_mod, "_triage_gate", capture_gate)
    prompt = "Review pull request #3. Please review."
    record = await run_main_harness.run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="workflow_dispatch",
        event_payload={"inputs": {"prompt": prompt if prompt_in_event else ""}},
        prompt=prompt if not prompt_in_event else "review the diff",
    )

    assert record.raised is None
    assert record.result is not None
    assert record.result.success
    assert closing_calls == [("acme", "demo", 3)]
    assert gate_pr_numbers == [(3, 3)]
    state = record.tool_context.tool_state
    assert state.linked_issues == (issue,)
    assert state.scope_declaration.globs == ("docs/**", "tests/**")
    assert state.scope_declaration.source_ref == "linked_issue#101"
    classification = classify_run_blast_radius(
        "diff --git a/docs/guide.md b/docs/guide.md\n"
        "--- a/docs/guide.md\n+++ b/docs/guide.md\n@@ -1 +1 @@\n-old\n+new\n",
        scope=scope_signal_for_state(state),
    )
    assert classification is not None
    assert "scope.within" in {reason.code for reason in classification.reasons}
    assert {gate.gate: gate.passed for gate in classification.checklist}["scope"] is True


@pytest.mark.asyncio
async def test_a_failed_pull_request_read_leaves_the_scope_unknown(main_mod: Any) -> None:
    scm = _PullScm(None, error=RuntimeError("GitHub answered 502"))
    event = _bound(_comment_on_pr(_BODY_SCOPE, "@mergecraft review"), body=_BODY_SCOPE)
    # A closing issue's block must not stand in for a pull request body that could
    # not be read: that body might have declared a narrower scope.
    ctx = _bound_ctx(
        event, "issue_comment_created", "@mergecraft review", scm, issues=(_ISSUE_SCOPE,)
    )

    await _record(main_mod, ctx)

    assert len(scm.calls) == 1
    assert hasattr(ctx.tool_state, "scope_declaration")
    assert ctx.tool_state.scope_declaration is None


@pytest.mark.asyncio
async def test_an_event_that_carries_the_body_is_not_fetched(main_mod: Any) -> None:
    scm = _PullScm("Scope paths:\n- other/**\n")
    event = {"pull_request": {**_BOUND_PULL, "body": _BODY_SCOPE}}
    ctx = _bound_ctx(event, "pull_request_synchronize", _BODY_SCOPE, scm)

    await _record(main_mod, ctx)

    assert _declaration(ctx).globs == ("src/mergecraft/requirements/**",)
    assert scm.calls == []


@pytest.mark.asyncio
async def test_a_bound_comment_run_never_reads_the_comment(main_mod: Any) -> None:
    scm = _PullScm(_NO_SCOPE)
    event = _bound(_comment_on_pr(_NO_SCOPE, _COMMENT_SCOPE), body=_NO_SCOPE)
    ctx = _bound_ctx(event, "issue_comment_created", _COMMENT_SCOPE, scm)

    await _record(main_mod, ctx)

    declaration = _declaration(ctx)
    assert len(scm.calls) == 1
    assert declaration.declared is False
    assert declaration.globs == ()
