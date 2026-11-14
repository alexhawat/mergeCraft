"""A failed checkout cannot combine a new revision with an earlier review's proof."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from tests.mcp.test_checkout import (
    _ctx_for,
    _git,
    _pin_publishers,
    _pr_repo_with_two_commits,
    _StubGitHub,
)

from mergecraft.ci.red_green import RedGreenEvidence
from mergecraft.config.settings_snapshot import assert_config_unchanged
from mergecraft.evidence.coverage import _read_evidence
from mergecraft.evidence.trajectory import ToolCallRecord
from mergecraft.mcp import checkout as checkout_module
from mergecraft.mcp.review import publish_pull_request_review
from mergecraft.mcp.tool_state import (
    AnalyzerRunState,
    ApprovalRecord,
    ReviewRecord,
    primary_repo_state,
)
from mergecraft.mcp.verdict import ensure_review_scope_for_terminal
from mergecraft.requirements.ingest import ScopeDeclaration
from mergecraft.security.review_integrity import TreeBaseline, hash_tree
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds


@pytest.mark.parametrize("failure", ["moving-fetch", "moving-files", "cancelled-files"])
async def test_checkout_retry_invalidates_old_scope_and_can_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _pin_publishers(monkeypatch, frozenset())
    monkeypatch.setattr("mergecraft.mcp.review_context.hydrate_review_context", AsyncMock())
    repo, old_sha, _ = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)

    def add_changed_config() -> str:
        work = tmp_path / "work"
        (work / ".mergecraft").mkdir()
        (work / ".mergecraft" / "config.yaml").write_text("# revision B\n{}\n")
        _git(work, "add", ".mergecraft/config.yaml")
        _git(work, "commit", "-m", "change config at revision B")
        _git(work, "push", str(tmp_path / "origin.git"), "feature:refs/pull/1/head")
        return checkout_module._run_git(["rev-parse", "HEAD"], cwd=str(work)).strip()

    new_sha = await asyncio.to_thread(add_changed_config)

    class Offline(_StubGitHub):
        failure: str | None = None
        read_during_checkout = False

        async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
            if self.read_during_checkout:
                ctx.tool_state.tool_calls.append(
                    ToolCallRecord(
                        sequence=50,
                        tool="Read",
                        signature="read-while-checkout-is-pending",
                        intent="read",
                        ok=True,
                        paths=["reviewed.py"],
                    )
                )
            return await super().get_pull(owner, repo, pull_number)

        async def get(self, path: str, **kwargs: Any) -> Any:
            if path.endswith("/files"):
                if self.failure == "cancelled-files":
                    raise asyncio.CancelledError
                if self.failure == "moving-files":
                    self._head_sha = old_sha
                return []
            return {}

    scm = Offline(head_sha=old_sha, reviews=[])
    await asyncio.to_thread(
        _git, tmp_path / "origin.git", "update-ref", "refs/pull/1/head", old_sha
    )
    ctx = _ctx_for(repo, scm, tmp_path, mode="Review", analyzers_mode="off")
    evidence_run_id = ctx.tool_state.evidence_run_id
    declaration = ScopeDeclaration(
        declared=True, globs=("*.py",), source_ref="pr_description", rejected=()
    )
    ctx.tool_state.scope_declaration = declaration
    ctx.budget_tracker = BudgetTracker(bounds=resolve_run_bounds(), tokens_used=27)
    ctx.tool_state.review_tree_baseline = TreeBaseline(
        root=repo, digest=await asyncio.to_thread(hash_tree, repo)
    )
    first = await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert not first.is_error, first.content
    assert ctx.tool_state.scope_declaration is declaration
    state = ctx.tool_state
    primary = primary_repo_state(state)
    assert primary.checkout_sha == old_sha
    assert primary.diff_path is not None
    old_diff = await asyncio.to_thread(Path(primary.diff_path).read_text)
    assert "new.py" not in old_diff
    pinned_settings = ctx.repo_settings_snapshot

    state.output = "old structured output"
    state.approval = ApprovalRecord(would_approve=True, sha=old_sha)
    state.pending_review_publication = {"commit_id": old_sha, "body": "old verdict"}
    state.prepared_run_packet = object()
    state.red_green = RedGreenEvidence(
        status="proven", test_count=1, artifact="old-receipt", run_url=None, detail="old SHA"
    )
    state.analyzer_run = AnalyzerRunState(ran=True)
    state.static_checks_ran = True
    state.verified_ids.add("old-verification")
    state.agent_findings.append({"body": "old finding"})
    state.tool_calls.append(
        ToolCallRecord(
            sequence=1,
            tool="Read",
            signature="old-read",
            intent="read",
            ok=True,
            paths=["reviewed.py"],
        )
    )
    old_read = state.tool_calls[-1]

    await asyncio.to_thread(
        _git, tmp_path / "origin.git", "update-ref", "refs/pull/1/head", new_sha
    )
    scm._head_sha = old_sha if failure == "moving-fetch" else new_sha
    scm.failure = failure
    real_git = checkout_module._run_git

    def fail_diff(args: list[str], **kwargs: Any) -> str:
        if args[:2] == ["diff", "--merge-base"]:
            raise RuntimeError("synthetic unavailable base")
        return real_git(args, **kwargs)

    with monkeypatch.context() as attempt:
        attempt.setattr(checkout_module, "_run_git", fail_diff)
        if failure == "cancelled-files":
            with pytest.raises(asyncio.CancelledError):
                await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": 1})
        else:
            failed = await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": 1})
            assert failed.is_error, failed.content
            assert "head changed" in str(failed.content)

    assert primary.checkout_sha is None
    assert primary.diff_path is None
    assert primary.incremental_changed_paths is None
    assert state.scope_provenance is None
    assert state.review_phase == "INIT"
    assert state.output is None
    assert state.checkout_scope_invalidated
    assert state.evidence_run_id == evidence_run_id
    assert state.approval is state.pending_review_publication is state.prepared_run_packet is None
    assert not state.agent_findings
    assert state.red_green is None
    assert state.analyzer_run is None
    assert not state.static_checks_ran
    assert not state.verified_ids
    assert state.coverage.authoritative_diff is None
    assert (
        old_read in state.tool_calls
    )  # audit history survives; old reads cannot prove a new scope
    assert _read_evidence(state, old_diff) == (False, {})
    assert state.scope_declaration is declaration
    assert ctx.repo_settings_snapshot is not None
    assert pinned_settings is not None
    assert ctx.repo_settings_snapshot.settings is pinned_settings.settings
    assert ctx.repo_settings_snapshot.policy is pinned_settings.policy
    assert_config_unchanged(ctx.repo_settings_snapshot)
    assert ctx.budget_tracker.tokens_used == 27
    for mode in ("Review", "IncrementalReview", None):
        state.selected_mode = mode
        with pytest.raises(ValueError, match="scope"):
            ensure_review_scope_for_terminal(state, "submit_review_verdict")
    state.selected_mode = "Review"
    with pytest.raises(ValueError, match="no validated terminal submission"):
        await publish_pull_request_review(ctx)

    scm.failure = None
    scm._head_sha = new_sha
    scm.read_during_checkout = True
    retried = await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert not retried.is_error, retried.content
    assert primary.checkout_sha == new_sha
    assert primary.diff_path is not None
    assert "new.py" in await asyncio.to_thread(Path(primary.diff_path).read_text)
    assert state.scope_provenance == "checkout"
    assert not state.checkout_scope_invalidated
    assert state.evidence_run_id == evidence_run_id
    await asyncio.to_thread(state.review_tree_baseline.verify)
    ensure_review_scope_for_terminal(state, "submit_review_verdict")
    assert any(call.signature == "read-while-checkout-is-pending" for call in state.tool_calls)
    assert _read_evidence(state, old_diff) == (False, {})
    state.tool_calls.append(
        ToolCallRecord(
            sequence=99,
            tool="Read",
            signature="new-read",
            intent="read",
            ok=True,
            paths=["reviewed.py"],
        )
    )
    assert _read_evidence(state, old_diff)[0]


async def test_published_receipt_prevents_recheckout_without_erasing_it(tmp_path: Path) -> None:
    ctx = _ctx_for(tmp_path, _StubGitHub(head_sha="a" * 40, reviews=[]), tmp_path, mode="Review")
    receipt = ReviewRecord(id=1, node_id="R1", reviewed_sha="a" * 40, verdict="approve")
    ctx.tool_state.review = receipt
    primary_repo_state(ctx.tool_state).checkout_sha = "a" * 40
    result = await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert result.is_error
    assert "published a review" in str(result.content)
    assert ctx.tool_state.review is receipt
    assert primary_repo_state(ctx.tool_state).checkout_sha == "a" * 40


@pytest.mark.parametrize(
    "refusal", ["dirty", "wrong-pr", "fork", "api-error", "cancelled", "published-during-lookup"]
)
async def test_preflight_refusal_preserves_the_existing_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    # The recovery cases above exercise a real checkout. Here a refusal must
    # never reach workspace mutation or replace any existing state field.
    from unittest.mock import Mock

    from mergecraft.mcp.verdict import register_review_scope

    old_sha = "a" * 40
    scm = _StubGitHub(head_sha=old_sha, reviews=[])
    monkeypatch.setattr(scm, "get", AsyncMock(return_value={}))
    ctx = _ctx_for(tmp_path, scm, tmp_path, mode="Review", analyzers_mode="off")
    ctx.gh_event = {"pull_request": {"number": 1}}
    state = ctx.tool_state
    primary_repo_state(state).checkout_sha = old_sha
    register_review_scope(state, diff_path=str(tmp_path / "old.diff"), provenance="checkout")
    fetch = Mock(side_effect=AssertionError("preflight refusal reached checkout mutation"))
    monkeypatch.setattr(checkout_module, "_fetch_head_with_retry", fetch)
    monkeypatch.setattr(checkout_module, "get_git_status", lambda cwd: "")
    state.output = "existing structured output"
    state.agent_findings = [{"body": "existing finding"}]
    state.analyzer_run = AnalyzerRunState(ran=True)
    state.verified_ids = {"existing-verification"}
    state.approval = ApprovalRecord(would_approve=True, sha=old_sha)
    state.pending_review_publication = {"commit_id": old_sha}
    state.prepared_run_packet = object()
    from dataclasses import fields

    saved_state = {field.name: getattr(state, field.name) for field in fields(state)}
    primary = primary_repo_state(state)
    saved_repo = {field.name: getattr(primary, field.name) for field in fields(primary)}
    get_pull = AsyncMock(wraps=scm.get_pull)
    monkeypatch.setattr(scm, "get_pull", get_pull)
    number = 1
    if refusal == "dirty":
        monkeypatch.setattr(checkout_module, "get_git_status", lambda cwd: " M reviewed.py")
    elif refusal == "wrong-pr":
        number = 2
    elif refusal == "fork":
        pr = await get_pull("acme", "demo", 1)
        pr["head"]["repo"] = {"full_name": "external/demo"}
        get_pull.return_value = pr
        get_pull.side_effect = None
        ctx.trust_tier = "trusted"
    elif refusal == "api-error":
        get_pull.side_effect = RuntimeError("PR lookup unavailable")
    elif refusal == "published-during-lookup":
        pr = await get_pull("acme", "demo", 1)
        receipt = ReviewRecord(id=1, node_id="R1", reviewed_sha=old_sha, verdict="approve")

        async def publish_during_lookup(*args: Any, **kwargs: Any) -> dict[str, Any]:
            state.review = receipt
            return pr

        get_pull.side_effect = publish_during_lookup
        saved_state["review"] = receipt
    else:
        get_pull.side_effect = asyncio.CancelledError
    if refusal == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": number})
    else:
        result = await checkout_module.checkout_pr_tool(ctx).execute({"pull_number": number})
        assert result.is_error, result.content
    for name, value in saved_state.items():
        assert getattr(state, name) is value, f"preflight refusal replaced {name}"
    for name, value in saved_repo.items():
        assert getattr(primary, name) is value, f"preflight refusal replaced repo.{name}"
    fetch.assert_not_called()
