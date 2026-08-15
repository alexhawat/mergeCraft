"""HA4.1 RED suite — class-derived agent toolsets (D14).

Every assertion builds a real toolset through ``mcp/server.py`` and inspects
``ToolSpec`` objects. Role filters replace the ``mutates`` heuristic for
gating; ``mutates`` keeps its existing uses (deny-list non-empty pin below).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools, build_orchestrator_tools
from mergecraft.mcp.shared import ToolSpec
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

# D14 — ten closed values. Role toolsets derive from these, not from mutates.
CLOSED_TOOL_CLASSES = frozenset(
    {
        "scope",
        "repository-read",
        "analysis",
        "verification",
        "review-read",
        "review-write",
        "github-mutation",
        "repository-mutation",
        "shell",
        "terminal-protocol",
    }
)

REVIEWER_ALLOWED_CLASSES = frozenset({"scope", "repository-read", "analysis", "review-read"})
VERIFIER_ALLOWED_CLASSES = frozenset({"repository-read", "analysis", "verification"})
MUTATION_CLASSES = frozenset(
    {
        "github-mutation",
        "repository-mutation",
        "shell",
        "terminal-protocol",
        "review-write",
    }
)

_HA42 = pytest.mark.xfail(reason="green after HA4.2: tool classes", strict=False)


def _tool_ctx(
    tmp_path: Path,
    *,
    shell: Literal["disabled", "restricted", "enabled"] = "restricted",
    push: Literal["disabled", "restricted", "enabled"] = "restricted",
    signed_commits: bool = True,
) -> ToolContext:
    """Full-surface context so a class cannot hide behind a disabled flag."""
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell=shell,
            push=push,
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=signed_commits,
        xrepo=XrepoConfig(mode="explicit", read=["other"], write=["other"]),
        static_checks_enabled=True,
    )


@pytest.fixture
def tool_ctx(tmp_path: Path) -> ToolContext:
    return _tool_ctx(tmp_path)


def _class_value(spec: ToolSpec) -> str:
    """Read ``ToolSpec.tool_class``; unclassified tools fail the assertion."""
    value = getattr(spec, "tool_class", None)
    assert value is not None, f"{spec.name!r} shipped unclassified"
    return str(value)


def _assert_real_toolspecs(tools: list[ToolSpec]) -> None:
    assert tools, "toolset must not be empty"
    assert all(isinstance(spec, ToolSpec) for spec in tools)


@_HA42
def test_every_registered_tool_declares_a_class(tool_ctx: ToolContext) -> None:
    """No tool ships unclassified — ``tool_class`` is required, no default."""
    orchestrator = build_orchestrator_tools(tool_ctx)
    common = build_common_tools(tool_ctx)
    _assert_real_toolspecs(orchestrator)
    _assert_real_toolspecs(common)

    unclassified = [
        spec.name for spec in (*orchestrator, *common) if getattr(spec, "tool_class", None) is None
    ]
    assert not unclassified, f"unclassified tools: {sorted(set(unclassified))}"

    from mergecraft.mcp.shared import ToolClass

    declared = {str(member) for member in ToolClass}
    assert declared == CLOSED_TOOL_CLASSES
    for spec in (*orchestrator, *common):
        assert isinstance(spec.tool_class, ToolClass)
        assert _class_value(spec) in declared


@_HA42
def test_reviewer_receives_no_mutation_tool(tool_ctx: ToolContext) -> None:
    """H4 — reviewer toolset is class-filtered, never a mutation class."""
    _assert_real_toolspecs(build_orchestrator_tools(tool_ctx))

    from mergecraft.mcp.server import build_reviewer_tools

    reviewer = build_reviewer_tools(tool_ctx)
    _assert_real_toolspecs(reviewer)
    leaked = [spec.name for spec in reviewer if _class_value(spec) in MUTATION_CLASSES]
    assert not leaked, f"reviewer received mutation tools: {leaked}"
    for spec in reviewer:
        assert _class_value(spec) in REVIEWER_ALLOWED_CLASSES, (
            f"reviewer received {spec.name!r} with class {_class_value(spec)!r}"
        )


@_HA42
def test_verifier_receives_no_mutation_tool(tool_ctx: ToolContext) -> None:
    """Verifier toolset is class-filtered, never a mutation class."""
    _assert_real_toolspecs(build_orchestrator_tools(tool_ctx))

    from mergecraft.mcp.server import build_verifier_tools

    verifier = build_verifier_tools(tool_ctx)
    _assert_real_toolspecs(verifier)
    leaked = [spec.name for spec in verifier if _class_value(spec) in MUTATION_CLASSES]
    assert not leaked, f"verifier received mutation tools: {leaked}"
    for spec in verifier:
        assert _class_value(spec) in VERIFIER_ALLOWED_CLASSES, (
            f"verifier received {spec.name!r} with class {_class_value(spec)!r}"
        )


@_HA42
def test_reviewer_and_verifier_toolsets_differ(tool_ctx: ToolContext) -> None:
    """H4 core — reviewer and verifier are no longer identical toolsets."""
    _assert_real_toolspecs(build_orchestrator_tools(tool_ctx))

    from mergecraft.mcp.server import build_reviewer_tools, build_verifier_tools

    reviewer = build_reviewer_tools(tool_ctx)
    verifier = build_verifier_tools(tool_ctx)
    _assert_real_toolspecs(reviewer)
    _assert_real_toolspecs(verifier)

    reviewer_names = {spec.name for spec in reviewer}
    verifier_names = {spec.name for spec in verifier}
    assert reviewer_names != verifier_names

    reviewer_classes = {_class_value(spec) for spec in reviewer}
    verifier_classes = {_class_value(spec) for spec in verifier}
    assert reviewer_classes != verifier_classes
    assert "scope" in reviewer_classes
    assert "scope" not in verifier_classes
    assert "verification" in verifier_classes
    assert "verification" not in reviewer_classes


def _read_only_toolsets(ctx: ToolContext) -> tuple[list[ToolSpec], list[ToolSpec]]:
    from mergecraft.mcp.server import build_reviewer_tools, build_verifier_tools

    reviewer = build_reviewer_tools(ctx)
    verifier = build_verifier_tools(ctx)
    _assert_real_toolspecs(reviewer)
    _assert_real_toolspecs(verifier)
    return reviewer, verifier


@_HA42
def test_no_read_only_role_receives_terminal_protocol(tool_ctx: ToolContext) -> None:
    """H5 — ``terminal-protocol`` (e.g. ``submit_review_verdict``) is orchestrator-only.

    VP1 may not be merged: if no tool of that class is registered, the
    intersection is empty and the assertion still holds.
    """
    _assert_real_toolspecs(build_orchestrator_tools(tool_ctx))
    reviewer, verifier = _read_only_toolsets(tool_ctx)
    for role, tools in (("reviewer", reviewer), ("verifier", verifier)):
        leaked = [spec.name for spec in tools if _class_value(spec) == "terminal-protocol"]
        assert not leaked, f"{role} received terminal-protocol: {leaked}"
        assert "submit_review_verdict" not in {spec.name for spec in tools}


@_HA42
def test_no_read_only_role_receives_github_mutation(tool_ctx: ToolContext) -> None:
    """Read-only roles never receive ``github-mutation`` even when common tools include it."""
    registered = build_orchestrator_tools(tool_ctx)
    _assert_real_toolspecs(registered)
    # Guard-deletion proof: the orchestrator surface *does* carry github-mutation
    # tools (comments, issues, labels). Deleting the class filter and returning
    # that surface to a read-only role must fail this test.
    assert any(_class_value(spec) == "github-mutation" for spec in registered)

    reviewer, verifier = _read_only_toolsets(tool_ctx)
    for role, tools in (("reviewer", reviewer), ("verifier", verifier)):
        leaked = [spec.name for spec in tools if _class_value(spec) == "github-mutation"]
        assert not leaked, f"{role} received github-mutation: {leaked}"


@_HA42
def test_no_read_only_role_receives_shell(tool_ctx: ToolContext) -> None:
    """Read-only roles never receive ``shell``, even when the run has shell=restricted."""
    registered = build_orchestrator_tools(tool_ctx)
    _assert_real_toolspecs(registered)
    assert any(_class_value(spec) == "shell" for spec in registered), (
        "restricted-shell run must register a shell-class tool so the filter is testable"
    )

    reviewer, verifier = _read_only_toolsets(tool_ctx)
    for role, tools in (("reviewer", reviewer), ("verifier", verifier)):
        leaked = [spec.name for spec in tools if _class_value(spec) == "shell"]
        assert not leaked, f"{role} received shell: {leaked}"
        names = {spec.name for spec in tools}
        assert "shell" not in names
        assert "kill_background" not in names


@_HA42
def test_orchestrator_receives_only_policy_allowed_classes(tmp_path: Path) -> None:
    """Orchestrator: all classes except ``repository-mutation`` when push is restricted."""
    from mergecraft.mcp.shared import ToolClass

    declared = {str(member) for member in ToolClass}
    assert declared == CLOSED_TOOL_CLASSES

    restricted = build_orchestrator_tools(_tool_ctx(tmp_path, push="restricted"))
    _assert_real_toolspecs(restricted)
    allowed_when_restricted = declared - {"repository-mutation"}
    for spec in restricted:
        assert _class_value(spec) in allowed_when_restricted, (
            f"orchestrator received {spec.name!r} with class {_class_value(spec)!r} "
            "under push=restricted"
        )

    enabled = build_orchestrator_tools(_tool_ctx(tmp_path, push="enabled"))
    _assert_real_toolspecs(enabled)
    for spec in enabled:
        assert _class_value(spec) in declared
    assert "repository-mutation" in {_class_value(spec) for spec in enabled}, (
        "push=enabled must admit repository-mutation; otherwise the restricted exclusion is vacuous"
    )


@_HA42
def test_shell_disabled_run_exposes_no_execution_tool(tmp_path: Path) -> None:
    """``shell=disabled`` exposes no tool whose class is ``shell`` on any role."""
    ctx = _tool_ctx(tmp_path, shell="disabled")
    orchestrator = build_orchestrator_tools(ctx)
    _assert_real_toolspecs(orchestrator)

    from mergecraft.mcp.server import build_reviewer_tools, build_verifier_tools

    for role, tools in (
        ("orchestrator", orchestrator),
        ("reviewer", build_reviewer_tools(ctx)),
        ("verifier", build_verifier_tools(ctx)),
    ):
        _assert_real_toolspecs(tools)
        leaked = [spec.name for spec in tools if _class_value(spec) == "shell"]
        assert not leaked, f"{role} exposed shell-class tools under shell=disabled: {leaked}"
        names = {spec.name for spec in tools}
        assert "shell" not in names
        assert "kill_background" not in names


def test_deny_list_derivation_is_not_empty(tool_ctx: ToolContext) -> None:
    """Regression pin: ``agents/gates.py`` refuses to start with an empty deny list.

    Passes today against the ``mutates=True`` derivation. After HA4.2 the same
    pin holds against the class-complement derivation — deleting the empty-list
    guard (or stripping every mutating classification) must fail this test.
    """
    registered = build_orchestrator_tools(tool_ctx)
    _assert_real_toolspecs(registered)
    registered_names = {spec.name for spec in registered}

    subagent_denied = subagent_denied_tool_names(tool_ctx)
    assert subagent_denied, (
        "subagent deny list derived empty — the gates.py empty-list guard is gone "
        "or no tool is classified as denied"
    )
    assert set(subagent_denied) <= registered_names

    verifier_denied = verifier_denied_tool_names(tool_ctx)
    assert verifier_denied, (
        "verifier deny list derived empty — the gates.py empty-list guard is gone "
        "or no tool is classified as denied"
    )
    assert set(verifier_denied) <= registered_names
