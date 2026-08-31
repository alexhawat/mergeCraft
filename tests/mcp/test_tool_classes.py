"""HA4 suite — class-derived agent toolsets (D14).

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


def test_reviewer_receives_no_mutation_tool(tool_ctx: ToolContext) -> None:
    """H4 / D9 / C6 — reviewer toolset is class-filtered; named mutations are the exception.

    ``create_pull_request_review`` (D9 publication), ``report_progress``
    (no-action path, REVIEW_WRITE), and ``record_finding_verdict`` (C6 verdict
    persistence, REVIEW_WRITE + mutates=True) are admitted on the primary
    reviewer via ``PRIMARY_MUTATING_ALLOWLIST``; all other mutation classes stay
    off. ``submit_review_verdict`` (TERMINAL_PROTOCOL, mutates=False) is
    admitted via class; it is deliberately orchestrator-only from the subagent
    perspective but the primary reviewer IS the orchestrator on /mcp/reviewer.
    """
    _assert_real_toolspecs(build_orchestrator_tools(tool_ctx))

    from mergecraft.mcp.server import build_reviewer_tools

    reviewer = build_reviewer_tools(tool_ctx)
    _assert_real_toolspecs(reviewer)
    leaked = [spec.name for spec in reviewer if _class_value(spec) in MUTATION_CLASSES]
    assert set(leaked) <= {
        "create_pull_request_review",
        "report_progress",
        "record_finding_verdict",
        "record_reviewer_dispatch_error",
        "record_reviewer_dispatch_run",
        "submit_review_verdict",
    }, f"reviewer received unexpected mutation tools: {leaked}"
    # Allowed non-base classes on the primary reviewer (deliberate C6 / D9 admissions).
    PRIMARY_EXTRA_ALLOWED_CLASSES = frozenset({"review-write", "terminal-protocol", "verification"})
    for spec in reviewer:
        allowed = REVIEWER_ALLOWED_CLASSES | PRIMARY_EXTRA_ALLOWED_CLASSES
        assert _class_value(spec) in allowed, (
            f"reviewer received {spec.name!r} with unexpected class {_class_value(spec)!r}"
        )


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
    # Primary reviewer now includes VERIFICATION (verify_agent_findings, C6) and
    # TERMINAL_PROTOCOL (submit_review_verdict, playbook step 10).
    assert "verification" in reviewer_classes
    assert "terminal-protocol" in reviewer_classes
    assert "terminal-protocol" not in verifier_classes


def _read_only_toolsets(ctx: ToolContext) -> tuple[list[ToolSpec], list[ToolSpec]]:
    from mergecraft.mcp.server import build_reviewer_tools, build_verifier_tools

    reviewer = build_reviewer_tools(ctx)
    verifier = build_verifier_tools(ctx)
    _assert_real_toolspecs(reviewer)
    _assert_real_toolspecs(verifier)
    return reviewer, verifier


def test_verifier_does_not_receive_terminal_protocol(tool_ctx: ToolContext) -> None:
    """H5 — ``terminal-protocol`` (``submit_review_verdict``) stays off the verifier.

    The primary reviewer IS allowed ``submit_review_verdict`` on /mcp/reviewer
    (playbook step 10, C6); that is intentional and tested in
    ``test_reviewer_receives_no_mutation_tool``. The verifier must still be
    denied it so the judge cannot self-submit a review.
    """
    _assert_real_toolspecs(build_orchestrator_tools(tool_ctx))
    reviewer, verifier = _read_only_toolsets(tool_ctx)
    # Verifier must not have any terminal-protocol tools.
    leaked = [spec.name for spec in verifier if _class_value(spec) == "terminal-protocol"]
    assert not leaked, f"verifier received terminal-protocol: {leaked}"
    assert "submit_review_verdict" not in {spec.name for spec in verifier}
    # Primary reviewer DOES have submit_review_verdict (deliberate C6 admission).
    assert "submit_review_verdict" in {spec.name for spec in reviewer}


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


def test_repository_mutation_class_for_push() -> None:
    """Direct pin: push tools are repository-mutation only when push is enabled.

    Deleting ``repository_mutation_class_for_push`` (or swapping the two
    branches) must fail this test even if orchestrator filtering still looks
    right via another path.
    """
    from mergecraft.mcp.shared import ToolClass, repository_mutation_class_for_push

    assert repository_mutation_class_for_push("enabled") is ToolClass.REPOSITORY_MUTATION
    assert repository_mutation_class_for_push("restricted") is ToolClass.GITHUB_MUTATION


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


def test_record_finding_verdict_is_absent_from_verifier_surface(tool_ctx: ToolContext) -> None:
    """Verdict persistence is orchestrator-only — the verifier prompt returns a verdict."""
    from mergecraft.mcp.server import build_verifier_tools

    verifier_names = {spec.name for spec in build_verifier_tools(tool_ctx)}
    orchestrator_names = {spec.name for spec in build_orchestrator_tools(tool_ctx)}
    assert "record_finding_verdict" not in verifier_names
    assert "record_finding_verdict" in orchestrator_names
    assert "verify_agent_findings" in verifier_names
    assert "record_finding_verdict" in verifier_denied_tool_names(tool_ctx)


def test_read_only_roles_exclude_mutating_tools_except_checkout_pr(tool_ctx: ToolContext) -> None:
    """Class membership is not enough: mutates=True tools stay off read-only surfaces.

    ``checkout_pr`` and ``establish_review_scope`` are the HA4.2 / D14 / W4
    exceptions on the reviewer. D9 also admits ``create_pull_request_review`` on
    the primary reviewer only. The session tools ``set_output``, ``select_mode``,
    and ``report_progress`` are admitted on the primary reviewer via
    ``PRIMARY_MUTATING_ALLOWLIST``; subagents still deny them. Verifier gets no
    mutating tool.
    """
    reviewer, verifier = _read_only_toolsets(tool_ctx)
    reviewer_mutating = [spec.name for spec in reviewer if spec.mutates]
    assert "checkout_pr" in reviewer_mutating
    assert set(reviewer_mutating) <= {
        "checkout_pr",
        "establish_review_scope",
        "create_pull_request_review",
        "set_output",
        "select_mode",
        "report_progress",
        # C6: verdict persistence — REVIEW_WRITE + mutates=True, primary only.
        "record_finding_verdict",
    }
    assert not [spec.name for spec in verifier if spec.mutates]

    subagent_denied = subagent_denied_tool_names(tool_ctx)
    verifier_denied = verifier_denied_tool_names(tool_ctx)
    for name in ("set_output", "start_dependency_installation", "select_mode"):
        assert name in subagent_denied
        assert name in verifier_denied
    assert "checkout_pr" not in subagent_denied
    assert "checkout_pr" in verifier_denied


def test_live_verifier_mcp_lists_class_filtered_tools(tool_ctx: ToolContext) -> None:
    """Runtime ``tools/list`` on the live verifier endpoint is class-filtered (H4)."""
    import json
    from urllib.request import Request, urlopen

    from mergecraft.mcp.server import MCP_ENDPOINT, MCP_VERIFIER_ENDPOINT, start_mcp_http_server

    url, stop = start_mcp_http_server(tool_ctx)
    try:
        verifier_url = url[: -len(MCP_ENDPOINT)] + MCP_VERIFIER_ENDPOINT
        list_body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        headers = {"Content-Type": "application/json"}
        token = getattr(tool_ctx, "mcp_auth_token", None)
        if isinstance(token, str) and token:
            headers["Authorization"] = f"Bearer {token}"
        orchestrator_token = getattr(tool_ctx, "mcp_orchestrator_auth_token", None)
        orchestrator_headers = {"Content-Type": "application/json"}
        if isinstance(orchestrator_token, str) and orchestrator_token:
            orchestrator_headers["Authorization"] = f"Bearer {orchestrator_token}"
        with urlopen(
            Request(verifier_url, data=list_body, headers=headers, method="POST"),
            timeout=5,
        ) as resp:
            listed = json.loads(resp.read().decode())
        names = {entry["name"] for entry in listed["result"]["tools"]}
        assert "verify_agent_findings" in names
        assert "record_finding_verdict" not in names
        assert "push_branch" not in names
        assert "checkout_pr" not in names

        with urlopen(
            Request(url, data=list_body, headers=orchestrator_headers, method="POST"),
            timeout=5,
        ) as resp:
            orchestrator = json.loads(resp.read().decode())
        orch_names = {entry["name"] for entry in orchestrator["result"]["tools"]}
        assert "record_finding_verdict" in orch_names
        assert "push_branch" in orch_names

        call_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "record_finding_verdict", "arguments": {}},
            }
        ).encode()
        with urlopen(
            Request(verifier_url, data=call_body, headers=headers, method="POST"),
            timeout=5,
        ) as resp:
            called = json.loads(resp.read().decode())
        assert called["error"]["code"] == -32601
        assert "record_finding_verdict" in called["error"]["message"]
    finally:
        stop()


def test_live_reviewer_mcp_lists_class_filtered_tools(tool_ctx: ToolContext) -> None:
    """Runtime ``tools/list`` on the live reviewer endpoint is class-filtered (H4 / C6).

    Session tools ``set_output``, ``select_mode``, and ``report_progress`` are
    admitted on the primary reviewer via ``PRIMARY_MUTATING_ALLOWLIST``.
    C6 tools ``submit_review_verdict`` (TERMINAL_PROTOCOL), ``verify_agent_findings``
    (VERIFICATION), and ``record_finding_verdict`` (REVIEW_WRITE + mutates, in
    PRIMARY_MUTATING_ALLOWLIST) are now also admitted on the primary reviewer.
    ``push_branch`` and other repo mutations stay off (D9).
    """
    import json
    from urllib.request import Request, urlopen

    from mergecraft.mcp.server import MCP_ENDPOINT, MCP_REVIEWER_ENDPOINT, start_mcp_http_server

    url, stop = start_mcp_http_server(tool_ctx)
    try:
        reviewer_url = url[: -len(MCP_ENDPOINT)] + MCP_REVIEWER_ENDPOINT
        list_body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        headers = {"Content-Type": "application/json"}
        token = getattr(tool_ctx, "mcp_auth_token", None)
        if isinstance(token, str) and token:
            headers["Authorization"] = f"Bearer {token}"
        with urlopen(
            Request(reviewer_url, data=list_body, headers=headers, method="POST"),
            timeout=5,
        ) as resp:
            listed = json.loads(resp.read().decode())
        names = {entry["name"] for entry in listed["result"]["tools"]}
        assert "checkout_pr" in names
        assert "git" in names
        for present in (
            "set_output",
            "select_mode",
            "report_progress",
            # C6 tools admitted on primary reviewer (not subagents, not verifier).
            "submit_review_verdict",
            "verify_agent_findings",
            "record_finding_verdict",
            # D7/D15 roster dispatch attribution (REVIEW_WRITE, mutates=False).
            "record_reviewer_dispatch_run",
            "record_reviewer_dispatch_error",
        ):
            assert present in names, f"{present!r} must be on primary /mcp/reviewer"
        for denied in (
            "start_dependency_installation",
            "push_branch",
        ):
            assert denied not in names
    finally:
        stop()
