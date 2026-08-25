"""MP1.6 — public MCP tool-selection and jailbreak evals."""

from __future__ import annotations

from tests.evals.support_mcp_public import case_by_id, require_callable

from mergecraft.capabilities.manifest import FORBIDDEN_CAPABILITIES, capabilities_manifest


def test_review_this_change_selects_review_change() -> None:
    case = case_by_id("review-this-change")
    select_tool = require_callable("select_public_tool")
    chosen = select_tool(case["prompt"])
    assert chosen == case["expected_tool"]


def test_what_does_mc_abc_mean_selects_inspect_or_explain() -> None:
    case = case_by_id("what-does-mc-abc-mean")
    select_tool = require_callable("select_public_tool")
    chosen = select_tool(case["prompt"])
    assert chosen in {"inspect_finding", "explain_finding"}


def test_reload_review_selects_get_review() -> None:
    case = case_by_id("reload-review")
    select_tool = require_callable("select_public_tool")
    chosen = select_tool(case["prompt"])
    assert chosen == case["expected_tool"]


def test_commit_this_fix_does_not_select_a_write_tool() -> None:
    case = case_by_id("commit-this-fix")
    select_tool = require_callable("select_public_tool")
    chosen = select_tool(case["prompt"])
    forbidden = set(case.get("forbidden_tools") or [])
    assert chosen is None or chosen not in forbidden


def test_forbidden_capabilities_remain_forbidden_in_get_capabilities_payload() -> None:
    payload = capabilities_manifest()
    forbidden = set(payload.get("forbidden") or [])
    for capability in FORBIDDEN_CAPABILITIES:
        assert capability in forbidden
