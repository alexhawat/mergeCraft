"""CLI offline analyze stage must call the real analyzer pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.config.settings import AnalyzersSettings, RepoSettings
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

_PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _real_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _nonempty_materialization(out_dir: Path) -> DiffMaterialization:
    diff_path = out_dir / "change.diff"
    diff_path.write_text(_PATCH, encoding="utf-8")
    return DiffMaterialization(
        path=diff_path,
        base_ref="HEAD",
        line_count=_PATCH.count("\n"),
        empty=False,
    )


def _patch_harness(
    monkeypatch: pytest.MonkeyPatch, *, analyzers_enabled: bool
) -> list[dict[str, Any]]:
    settings = RepoSettings.model_construct(analyzers=AnalyzersSettings(enabled=analyzers_enabled))
    monkeypatch.setattr(
        "mergecraft.config.load_repo_settings",
        lambda root, load_learnings_files=False: settings,
    )
    monkeypatch.setattr(
        offline_mod, "load_repo_settings", lambda root, load_learnings_files=False: settings
    )
    monkeypatch.setattr(offline_mod, "resolve_offline_review_trust_tier", lambda **_: "trusted")
    monkeypatch.setattr(offline_mod, "apply_cli_trust_tier_env", lambda _: {})
    monkeypatch.setattr(offline_mod, "_apply_tracing_cli_overrides", lambda _: {})
    monkeypatch.setattr(
        "mergecraft.evidence.run_manifest.apply_local_telemetry_defaults",
        lambda **_: {},
    )
    monkeypatch.setattr(
        offline_mod,
        "apply_diff_line_budget",
        lambda text, *, max_lines: (text, None),
    )
    calls: list[dict[str, Any]] = []

    def _pipeline(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return type("State", (), {"ran": True, "reason": None})()

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    return calls


@pytest.mark.asyncio
async def test_offline_analyze_invokes_pipeline_when_analyzers_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: nonempty dry-run analyze calls ``run_analyzer_pipeline`` with trust + files."""
    calls = _patch_harness(monkeypatch, analyzers_enabled=True)
    repo = _real_git_repo(tmp_path)

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        dry_run=True,
    )
    assert result.success is True
    assert result.outcome is RunOutcome.passed
    assert calls, "enabled analyzers must invoke run_analyzer_pipeline"
    call = calls[0]
    assert call["repo_root"] == repo
    changed = call["changed_files"]
    assert "demo.py" in list(changed)
    assert call["tier"] == "trusted"


@pytest.mark.asyncio
async def test_offline_analyze_skips_pipeline_when_analyzers_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge: ``analyzers.enabled=False`` must not call the pipeline."""
    calls = _patch_harness(monkeypatch, analyzers_enabled=False)
    repo = _real_git_repo(tmp_path)

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        dry_run=True,
    )
    assert result.success is True
    assert calls == []
