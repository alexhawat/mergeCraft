"""MP1.2 — six public semantic tools.

Pins D3-D11: dedicated ``build_public_tools``, completed-review persistence,
MC- short ids, capabilities/policy read-only contracts, and explain payload keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.public_mcp_support import (
    PUBLIC_TOOL_NAMES,
    build_public_http_client,
    init_git_repo,
    minimal_valid_finding_dict,
    rpc_json,
    write_minimal_config,
)

import mergecraft.mcp.public as public_mod
from mergecraft.analyzers.finding import FINDING_SHORT_ID_PREFIX
from mergecraft.capabilities.manifest import capabilities_manifest
from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES
from mergecraft.review.completed import CompletedReview, load_completed_review
from mergecraft.review.snapshot import canonical_review_snapshot

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _tool_result_text(body: dict[str, Any]) -> dict[str, Any]:
    result = body.get("result")
    assert isinstance(result, dict), body
    content = result.get("content")
    assert isinstance(content, list), body
    assert content, body
    first = content[0]
    assert isinstance(first, dict), body
    assert first.get("type") == "text", body
    text = first.get("text")
    assert isinstance(text, str), body
    return json.loads(text)


def _call_public_tool(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from tests.mcp.public_mcp_support import MCP_PUBLIC_ENDPOINT

    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    _, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        auth_token=ctx.mcp_auth_token,
    )
    assert "result" in body, body
    return _tool_result_text(body)


def test_review_change_persists_completed_review(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "review_change",
        {"dry_run": True},
    )
    review_id = payload.get("review_id")
    assert isinstance(review_id, str), payload
    assert review_id, payload
    loaded = load_completed_review(review_id, repo_root=tmp_path)
    assert loaded is not None


def test_review_change_returns_short_ids(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "review_change",
        {"dry_run": True},
    )
    findings = payload.get("findings")
    assert isinstance(findings, list), payload
    if not findings:
        pytest.skip("dry_run produced no findings — short-id shape still required when present")
    for item in findings:
        assert isinstance(item, dict), item
        short_id = item.get("short_id")
        assert isinstance(short_id, str), item
        assert short_id.startswith(FINDING_SHORT_ID_PREFIX), item


def test_get_review_round_trips_completed_store(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.review.completed import persist_completed_review

    snapshot = canonical_review_snapshot(entry="cli")
    review_id = "mp1-review-round-trip"
    persist_completed_review(
        CompletedReview(
            review_id=review_id,
            snapshot=snapshot,
            manifest={"outcome": "clean"},
            findings=[],
        ),
        repo_root=tmp_path,
    )
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "get_review",
        {"review_id": review_id},
    )
    assert payload.get("review_id") == review_id


def test_inspect_finding_accepts_short_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.review.completed import persist_completed_review

    fingerprint = "a" * 64
    finding = minimal_valid_finding_dict(fingerprint, message="sample")
    short_id = finding["short_id"]
    review_id = "mp1-inspect-finding"
    snapshot = canonical_review_snapshot(entry="cli")
    persist_completed_review(
        CompletedReview(
            review_id=review_id,
            snapshot=snapshot,
            manifest={"outcome": "changes_requested"},
            findings=[finding],
        ),
        repo_root=tmp_path,
        evidence_packets={
            fingerprint: {
                "state": "unverified",
                "kinds": ["correctness"],
            }
        },
    )
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "inspect_finding",
        {"finding_id": short_id, "review_id": review_id},
    )
    assert payload.get("finding_id") == short_id


def test_explain_finding_matches_cli_explain_payload_keys(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.review.completed import persist_completed_review

    fingerprint = "b" * 64
    finding = minimal_valid_finding_dict(fingerprint, message="sample")
    short_id = finding["short_id"]
    review_id = "mp1-explain-finding"
    snapshot = canonical_review_snapshot(entry="cli")
    persist_completed_review(
        CompletedReview(
            review_id=review_id,
            snapshot=snapshot,
            manifest={"outcome": "changes_requested"},
            findings=[finding],
        ),
        repo_root=tmp_path,
        evidence_packets={
            fingerprint: {
                "state": "unverified",
                "kinds": ["correctness"],
            }
        },
    )
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "explain_finding",
        {"finding_id": short_id, "review_id": review_id},
    )
    for key in ("verb", "finding_id", "summary"):
        assert key in payload, payload
    assert payload["verb"] == "explain"
    assert payload.get("review_id") == review_id


def test_get_capabilities_matches_capabilities_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    payload = _call_public_tool(tmp_path, monkeypatch, "get_capabilities", {})
    expected = capabilities_manifest()
    for key in ("review_only", "modes", "allowed", "forbidden"):
        assert payload.get(key) == expected[key], (key, payload)


def test_get_policy_is_read_only(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.cli.mcp_serve import build_mcp_tool_context

    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    ctx = build_mcp_tool_context(cwd=tmp_path)
    tools = public_mod.build_public_tools(ctx)
    spec = next(tool for tool in tools if tool.name == "get_policy")
    schema = spec.input_schema
    assert schema.get("type") == "object"
    assert schema.get("additionalProperties") is False
    assert "properties" in schema
    for prop in schema["properties"]:
        assert not str(prop).lower().startswith("set_"), prop

    payload = _call_public_tool(tmp_path, monkeypatch, "get_policy", {})
    rule_ids = payload.get("policy_rule_ids")
    assert isinstance(rule_ids, list), payload
    assert set(rule_ids).issuperset(set(DEFAULT_GATE_POLICIES))
    policies = payload.get("policies")
    assert isinstance(policies, dict), payload
    assert set(policies).issuperset(set(DEFAULT_GATE_POLICIES))


def test_review_change_rejects_diff_outside_workspace(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    outside = tmp_path.parent / "outside-mcp.patch"
    outside.write_text("diff --git a/x b/x\n", encoding="utf-8")
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "review_change",
        {"diff": f"../{outside.name}", "dry_run": True},
    )
    assert payload.get("error") == "diff path must be inside the workspace"


def test_review_change_rejects_option_shaped_base(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    payload = _call_public_tool(
        tmp_path,
        monkeypatch,
        "review_change",
        {"base": "--output=/tmp/review", "dry_run": True},
    )
    assert payload.get("error") == ("base must not start with '-' (git could parse it as a flag)")


@pytest.mark.asyncio
async def test_review_change_forwards_serve_trust_tier(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.cli.mcp_serve import build_mcp_tool_context
    from mergecraft.offline_review import OfflineReviewResult

    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    ctx = build_mcp_tool_context(cwd=tmp_path, trust_override="trusted")
    captured: dict[str, object] = {}

    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        captured.update(kwargs)
        return OfflineReviewResult(success=True, output="ok")

    monkeypatch.setattr(
        "mergecraft.mcp.public.run_offline_diff_review",
        fake_run_offline_diff_review,
    )
    spec = public_mod.review_change_tool(ctx)
    await spec.execute({"dry_run": True})
    assert captured.get("trust_override") == "trusted"
    json_path = captured.get("json_path")
    assert isinstance(json_path, Path), captured
    assert json_path.suffix == ".json"


def test_public_tools_are_not_filtered_orchestrator_tools(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.cli.mcp_serve import build_mcp_tool_context
    from mergecraft.mcp.server import build_orchestrator_tools

    names = frozenset(public_mod.PUBLIC_TOOL_NAMES)
    assert names == PUBLIC_TOOL_NAMES
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    ctx = build_mcp_tool_context(cwd=tmp_path)
    public_specs = public_mod.build_public_tools(ctx)
    public_tool_names = {spec.name for spec in public_specs}
    assert public_tool_names == names
    orch_names = {spec.name for spec in build_orchestrator_tools(ctx)}
    public_only = names - orch_names
    assert public_only, "public catalog must not be a pure orchestrator subset"
