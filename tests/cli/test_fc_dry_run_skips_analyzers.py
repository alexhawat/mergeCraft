"""W5 FC — #401 ``review --dry-run`` skips analyzer catalog (D10).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md``
Authoring wave: **W5** (FC RED). Implementation: **W6** (skip analyze when ``dry_run``).

``--dry-run`` must still materialize the diff and return/print the offline review
prompt. It must **not** invoke ``run_analyzer_pipeline`` or ``run_offline_analyze``
when analyzers are enabled. Cross-wave contracts use ``strict=False`` xfails.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import mergecraft.offline_review as offline_mod
from mergecraft.cli.app import app
from mergecraft.config.settings import AnalyzersSettings, RepoSettings
from mergecraft.review import ReviewEngine
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
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


def _patch_enabled_analyzers(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = RepoSettings.model_construct(analyzers=AnalyzersSettings(enabled=True))
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


class _OrderTap:
    """Wrap a positional ``ReviewRun`` so each stage appends to ``order``."""

    def __init__(self, inner: object, order: list[str]) -> None:
        self._inner = inner
        self._order = order

    async def materialize(self) -> object:
        self._order.append("materialize")
        return await self._inner.materialize()  # type: ignore[union-attr]

    async def analyze(self) -> object:
        self._order.append("analyze")
        return await self._inner.analyze()  # type: ignore[union-attr]

    async def review(self) -> object:
        self._order.append("review")
        return await self._inner.review()  # type: ignore[union-attr]

    async def publish(self, review_out: object) -> object:
        self._order.append("publish")
        return await self._inner.publish(review_out)  # type: ignore[union-attr]


@pytest.mark.xfail(
    reason="green after W6: dry-run skips analyzer catalog (#401)",
    strict=False,
)
def test_review_dry_run_skips_run_analyzer_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error (#401): enabled analyzers + ``--dry-run`` must not call ``run_analyzer_pipeline``."""
    pipeline_calls: list[dict[str, Any]] = []

    def _pipeline(**kwargs: object) -> object:
        pipeline_calls.append(dict(kwargs))
        return type("State", (), {"ran": True, "reason": None})()

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    _patch_enabled_analyzers(monkeypatch)
    patch = tmp_path / "change.diff"
    patch.write_text(_PATCH, encoding="utf-8")
    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert result.exception is None, result.exception
    assert pipeline_calls == []


@pytest.mark.xfail(
    reason="green after W6: dry-run skips analyzer catalog (#401)",
    strict=False,
)
def test_review_dry_run_skips_run_offline_analyze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error (#401): enabled analyzers + ``--dry-run`` must not call ``run_offline_analyze``."""
    offline_calls: list[dict[str, Any]] = []

    async def _offline_analyze(**kwargs: object) -> object:
        offline_calls.append(dict(kwargs))
        return None

    monkeypatch.setattr("mergecraft.review.offline_stages.run_offline_analyze", _offline_analyze)
    _patch_enabled_analyzers(monkeypatch)
    patch = tmp_path / "change.diff"
    patch.write_text(_PATCH, encoding="utf-8")
    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert result.exception is None, result.exception
    assert offline_calls == []


def test_review_dry_run_still_materializes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy (#401): ``--dry-run`` still runs materialize before review short-circuit."""
    order: list[str] = []
    original = ReviewEngine.run

    async def wrapped(self: ReviewEngine, driver: object, /, **kwargs: Any) -> object:
        return await original(self, _OrderTap(driver, order), **kwargs)

    monkeypatch.setattr(ReviewEngine, "run", wrapped)
    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        lambda **_kwargs: None,
    )
    patch = tmp_path / "change.diff"
    patch.write_text(_PATCH, encoding="utf-8")
    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert result.exception is None, result.exception
    assert order[0] == "materialize"
    assert "demo.py" in (result.stdout + result.stderr)


def test_review_dry_run_returns_offline_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy (#401): ``--dry-run`` prints/returns the offline review prompt (review short-circuit)."""
    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        lambda **_kwargs: None,
    )
    patch = tmp_path / "change.diff"
    patch.write_text(_PATCH, encoding="utf-8")
    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert result.exception is None, result.exception
    out = result.stdout + result.stderr
    assert "create_pull_request_review" in out
    assert "select_mode" in out
    assert "demo.py" in out


@pytest.mark.xfail(
    reason="green after W6: dry-run skips analyzer catalog (#401)",
    strict=False,
)
@pytest.mark.asyncio
async def test_offline_diff_review_dry_run_skips_pipeline_when_analyzers_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration (#401): ``_run_offline_diff_review`` dry-run skips pipeline when enabled."""
    calls: list[dict[str, Any]] = []

    def _pipeline(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return type("State", (), {"ran": True, "reason": None})()

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    _patch_enabled_analyzers(monkeypatch)
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
    assert "create_pull_request_review" in result.output
    assert calls == []
