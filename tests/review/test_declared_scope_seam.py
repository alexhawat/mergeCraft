"""The run reads the declared scope once, before the fast-path gate (#1056 part 3).

``main._record_scope_declaration(ctx)`` stores a ``ScopeDeclaration`` on
``ToolState.scope_declaration``. Sources, first declaration wins: the pull
request body, then the bodies of the issues the pull request closes
(``ToolState.linked_issues``: ``LinkedIssue`` rows from ``mergecraft.scm.types``,
read in order by ``.body``; ``()`` closes nothing, ``None`` was not read; the
GraphQL read that fills it is the linked-issue read's own concern and is not
exercised here). A body with no
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
from types import SimpleNamespace
from typing import Any

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

_BODY_SCOPE = "Implements the parser.\n\nScope paths:\n- src/mergecraft/requirements/**\n"
_ISSUE_SCOPE = "Plan.\n\nScope paths:\n- docs/**\n- tests/**\n"
_NO_SCOPE = "A description with no declared scope.\n- a list item\n"


@pytest.fixture
def main_mod() -> Any:
    return import_module("mergecraft.main")


def _linked_issues(bodies: tuple[str, ...] | None) -> tuple[Any, ...] | None:
    """``LinkedIssue`` rows for ``bodies`` (read lazily so the suite collects first)."""
    if bodies is None:
        return None
    linked_issue = getattr(import_module("mergecraft.scm.types"), "LinkedIssue")  # noqa: B009
    return tuple(
        linked_issue(number=101 + index, author_login="maintainer", body=body)
        for index, body in enumerate(bodies)
    )


def _ctx(body: str | None, issues: tuple[str, ...] | None) -> Any:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    # The field the linked-issue read fills at run start.
    setattr(state, "linked_issues", _linked_issues(issues))  # noqa: B010
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
    setattr(state, "linked_issues", _linked_issues(()))  # noqa: B010
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
