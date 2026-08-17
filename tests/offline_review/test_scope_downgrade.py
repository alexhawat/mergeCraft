"""Pin the D12 scope-reduction downgrade across every terminal branch.

mergeCraft review (PR #242, finding ``2e1cb9c2153087658c3481bd``) found the
empty-diff early return in ``run_offline_diff_review`` hardcoded
``RunOutcome.passed`` and skipped the ``outcome_with_scope_reduction`` helper
— silently green-washing a fully truncated (or fully filtered) diff as a
clean pass. The dry-run, structured, and unstructured branches all apply the
downgrade; the empty-diff branch did not.

These tests pin the wiring by driving the private ``_run_offline_diff_review``
body with monkeypatched materialization + scope-reduction — the *exact* path
the reviewer described.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.config.settings import RepoSettings
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.run_bounds import ScopeReduction
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec


def _empty_materialization(out_dir: Path) -> DiffMaterialization:
    diff_path = out_dir / "empty.diff"
    diff_path.write_text("", encoding="utf-8")
    return DiffMaterialization(
        path=diff_path,
        base_ref="HEAD",
        line_count=0,
        empty=True,
    )


def _oversized_materialization(out_dir: Path) -> DiffMaterialization:
    body = "\n".join(f"+line {i}" for i in range(2000))
    diff_path = out_dir / "truncated.diff"
    diff_path.write_text(
        f"diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -0,0 +1,2000 @@\n{body}\n",
        encoding="utf-8",
    )
    return DiffMaterialization(
        path=diff_path,
        base_ref="HEAD",
        line_count=2000,
        empty=False,
    )


def _real_git_repo(tmp_path: Path) -> Path:
    """Create a real git repo so the ``(cwd / ".git").exists()`` check passes."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _settings_with_max_diff_lines(max_lines: int) -> object:
    from mergecraft.utils.run_bounds import RunBounds

    class _S:
        run_bounds = RunBounds(
            token_budget=2_000_000,
            cost_budget_usd=50.0,
            tool_call_budget=500,
            run_timeout_s=3600.0,
            context_retrieval_timeout_s=30.0,
            max_diff_lines=max_lines,
            external_operation_timeout_s=600.0,
        )

    return _S()


@pytest.mark.asyncio
async def test_empty_diff_with_scope_reduction_is_downgraded_to_inconclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``materialization.empty=True`` *and* ``scope_reduction`` set reports
    ``RunOutcome.inconclusive`` (D12), not ``passed``.

    mergecraft-finding ``2e1cb9c2153087658c3481bd``.
    """
    repo = _real_git_repo(tmp_path)
    monkeypatch.setattr(
        "mergecraft.config.load_repo_settings",
        lambda root, load_learnings_files=False: RepoSettings.model_construct(),
    )
    monkeypatch.setattr(offline_mod, "resolve_offline_review_trust_tier", lambda **_: "trusted")
    monkeypatch.setattr(offline_mod, "apply_cli_trust_tier_env", lambda _: {})
    monkeypatch.setattr(offline_mod, "_apply_tracing_cli_overrides", lambda _: {})
    monkeypatch.setattr(
        "mergecraft.evidence.run_manifest.apply_local_telemetry_defaults",
        lambda **_: {},
    )
    monkeypatch.setattr(
        offline_mod, "resolve_run_bounds", lambda **_: _settings_with_max_diff_lines(0).run_bounds
    )

    # Capture the resolved bounds for the patched materialization.
    captured: dict[str, DiffMaterialization] = {}

    def _capture_materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        materialization = _oversized_materialization(out_dir)
        captured["materialization"] = materialization
        return materialization

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _capture_materialize)

    # Force ``apply_diff_line_budget`` to fully truncate the diff to empty so
    # ``scope_reduction`` is non-None *and* ``materialization.empty=True`` —
    # the wiring gap the review called out.
    reduction = ScopeReduction(
        original_lines=2000,
        kept_lines=0,
        omitted_paths=["x.py"],
        reason="oversize → fully truncated in the test",
    )

    def _truncate_to_empty(
        text: str,
        *,
        max_lines: int,
    ) -> tuple[str, ScopeReduction]:
        return "", reduction

    monkeypatch.setattr(offline_mod, "apply_diff_line_budget", _truncate_to_empty)

    # The agent must never run on the empty-diff branch.
    async def _no_agent(*args: object, **kwargs: object):
        raise AssertionError("agent must not be invoked on the empty-diff early return")

    monkeypatch.setattr(offline_mod, "_run_agent_review", _no_agent)

    workspace = ResolvedWorkspace(
        cwd=repo,
        git_common_dir=repo / ".git",
        cloned=False,
    )
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)

    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
    )

    assert result.empty_diff is True
    assert result.scope_reduction is reduction
    assert result.outcome is RunOutcome.inconclusive, (
        "empty diff with omitted scope must report inconclusive, never passed — "
        "D12 (silent pass on hidden scope) regression"
    )
