"""Decision-path coverage for ``mergecraft.scm.protocol`` (#431).

The happy path — a complete, all-async adapter — is already pinned by
``tests/scm/test_protocol.py`` and ``tests/scm/test_second_adapter.py``. What was
never exercised is the *other* way out of each decision in ``validate_provider``
and its helpers: an operation that is absent, not callable, or declared with the
wrong async-ness, and a declared operation set that no longer covers the GitHub
surface. Those are the branches that decide whether a broken adapter is allowed
to reach a review run.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from mergecraft.scm.protocol import (
    ScmProvider,
    mcp_generic_tool_names,
    protocol_operation_names,
    protocol_supports_github_operations,
    validate_provider,
)


def _async_stub(name: str) -> Any:
    """Build an ``async def`` method that records nothing and returns its name."""

    async def method(self: object, *args: Any, **kwargs: Any) -> str:
        _ = (self, args, kwargs)
        return name

    method.__name__ = name
    return method


def _sync_stub(name: str) -> Any:
    """Build a plain ``def`` method — the wrong shape for an async operation."""

    def method(self: object, *args: Any, **kwargs: Any) -> str:
        _ = (self, args, kwargs)
        return name

    method.__name__ = name
    return method


def _complete_provider_namespace() -> dict[str, Any]:
    return {name: _async_stub(name) for name in protocol_operation_names()}


def _make_provider(namespace: dict[str, Any]) -> object:
    return type("_GeneratedProvider", (), namespace)()


def test_complete_async_provider_reports_no_missing_operations() -> None:
    """A provider with every operation as ``async def`` validates clean."""
    report = validate_provider(_make_provider(_complete_provider_namespace()))

    assert report.complete is True
    assert report.missing == ()


def test_absent_operations_are_named_in_the_report() -> None:
    """A provider missing operations names exactly those, sorted, and is incomplete."""
    namespace = _complete_provider_namespace()
    del namespace["graphql"]
    del namespace["create_review"]

    report = validate_provider(_make_provider(namespace))

    assert report.complete is False
    assert report.missing == ("create_review", "graphql")


def test_non_callable_attribute_counts_as_a_missing_operation() -> None:
    """An attribute that shadows an operation with data is not an implementation."""
    namespace = _complete_provider_namespace()
    namespace["get_pull"] = {"number": 7}

    report = validate_provider(_make_provider(namespace))

    assert report.complete is False
    assert report.missing == ("get_pull",)


def test_sync_definition_of_an_async_operation_is_reported_as_expected_async() -> None:
    """A sync ``def`` where the protocol declares ``async def`` is rejected.

    Call sites ``await`` these operations. A sync implementation returns a plain
    value that ``await`` then chokes on at run time, so validation must catch it.
    """
    namespace = _complete_provider_namespace()
    namespace["list_pull_files"] = _sync_stub("list_pull_files")

    report = validate_provider(_make_provider(namespace))

    assert report.complete is False
    assert report.missing == ("list_pull_files (expected async)",)


def test_async_definition_of_a_sync_operation_is_reported_as_expected_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sync side of the async-ness check fires for a non-async declared op.

    Every operation on ``ScmProvider`` is async today, so this branch is only
    reachable once the operation set names something the protocol does not
    declare as a coroutine. Pinning it now means the day a sync helper joins the
    set, an ``async def`` implementation of it is still reported — rather than
    silently accepted because the check only ever ran in one direction.
    """
    extended = frozenset({*protocol_operation_names(), "repo_root"})
    monkeypatch.setattr("mergecraft.scm.protocol._PROTOCOL_OPERATIONS", extended)

    namespace = _complete_provider_namespace()
    namespace["repo_root"] = _async_stub("repo_root")

    report = validate_provider(_make_provider(namespace))

    assert report.complete is False
    assert report.missing == ("repo_root (expected sync)",)


def test_a_declared_operation_absent_from_the_protocol_is_not_treated_as_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Names in the operation set but not on ``ScmProvider`` default to sync.

    ``_async_protocol_operations`` reads async-ness off ``ScmProvider`` itself.
    A name with no protocol member must be skipped rather than assumed async;
    otherwise a sync helper added to the set would be demanded as a coroutine
    from every adapter.
    """
    extended = frozenset({*protocol_operation_names(), "repo_root"})
    monkeypatch.setattr("mergecraft.scm.protocol._PROTOCOL_OPERATIONS", extended)

    namespace = _complete_provider_namespace()
    namespace["repo_root"] = _sync_stub("repo_root")

    report = validate_provider(_make_provider(namespace))

    assert report.complete is True
    assert report.missing == ()


def test_github_surface_coverage_is_reported_true_for_the_shipped_protocol() -> None:
    """The declared operation set covers the whole GitHub REST + MCP surface."""
    assert protocol_supports_github_operations() is True


@pytest.mark.parametrize(
    ("dropped", "label"),
    [("download_workflow_run_logs", "rest"), ("resolve_review_thread", "mcp-write")],
)
def test_github_surface_coverage_is_false_when_an_operation_is_dropped(
    monkeypatch: pytest.MonkeyPatch, dropped: str, label: str
) -> None:
    """Dropping either half of the surface flips the guard to False.

    ``protocol_supports_github_operations`` ANDs a REST check with an MCP check.
    One case per operand proves neither side is dead: a REST-only regression and
    an MCP-write-only regression are both caught.
    """
    reduced = frozenset(protocol_operation_names() - {dropped})
    monkeypatch.setattr("mergecraft.scm.protocol._PROTOCOL_OPERATIONS", reduced)

    assert protocol_supports_github_operations() is False, label


def test_generic_mcp_tools_are_never_declared_as_protocol_operations() -> None:
    """Generic-tool names must stay out of the operation set.

    ``mcp_generic_tool_names`` lists MCP tools implemented with generic REST /
    GraphQL calls. ``GitLabScmAdapter`` grows one stub method per name in
    ``protocol_operation_names()``; adding a generic tool there would give every
    adapter a namesake method that nothing implements or dispatches to.
    """
    generic = mcp_generic_tool_names()

    assert generic == frozenset(
        {"get_issue_events", "get_check_suite_logs", "get_review_comments", "checkout_pr"}
    )
    assert generic & protocol_operation_names() == frozenset()


async def test_every_protocol_operation_is_an_inert_declaration() -> None:
    """``ScmProvider`` declares operations; it must never implement one.

    D10 is "declare, don't fake": a provider that cannot do something raises
    ``UnsupportedScmCapability`` rather than fabricating a GitHub-shaped result.
    That only holds while the protocol bodies stay empty — a concrete default on
    ``ScmProvider`` (a GitHub-flavoured fallback, a hollow ``{}``) would be
    inherited by any adapter subclassing it and would fake success instead.
    """
    inert = type("_InertProvider", (ScmProvider,), {})()

    assert inert.capabilities is None
    assert await inert.aclose() is None

    for name in sorted(protocol_operation_names()):
        operation = getattr(inert, name)
        bound = inspect.signature(operation)
        args = [
            "x"
            for parameter in bound.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        kwargs = {
            parameter.name: "x"
            for parameter in bound.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind is inspect.Parameter.KEYWORD_ONLY
        }
        assert await operation(*args, **kwargs) is None, f"{name} carries an implementation"


async def test_adapters_do_not_inherit_the_protocol_stubs() -> None:
    """Shipped adapters implement ``ScmProvider`` structurally, never by inheritance.

    ``validate_provider`` cannot tell an inherited empty stub from a real method,
    so a subclassing adapter would pass validation while returning ``None`` from
    every unimplemented operation. ``GitLabScmAdapter`` avoids that by raising
    ``UnsupportedScmCapability`` from generated stubs instead.
    """
    from mergecraft.scm.errors import UnsupportedScmCapability
    from mergecraft.scm.github import GitHubScmAdapter
    from mergecraft.scm.gitlab import GitLabScmAdapter

    inert = type("_InertProvider", (ScmProvider,), {})()
    assert validate_provider(inert).complete is True, (
        "inherited stubs validate as complete — adapters must not subclass ScmProvider"
    )

    assert ScmProvider not in GitLabScmAdapter.__mro__
    assert ScmProvider not in GitHubScmAdapter.__mro__

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    with pytest.raises(UnsupportedScmCapability):
        await adapter.get_pull("acme", "demo", 7)
