"""Finalize-before-store: invalid structured output must not poison the cache."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.analyzers.finding import STRUCTURED_OUTPUT_REQUIRED_MSG, make_finding
from mergecraft.config.settings import RepoSettings
from mergecraft.offline_review import OfflineReviewResult, _finish_offline_result
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.review_result_cache import load_review_result, store_review_result
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

_PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _valid_structured_output() -> str:
    finding = make_finding(
        tool="mergecraft-agent",
        rule_id="CACHE-1",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="cached finding",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
    )
    return json.dumps({"findings": [finding.model_dump()]})


def _real_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_CACHE_DIR", str(tmp_path / "run-cache"))


def _nonempty_materialization(out_dir: Path) -> DiffMaterialization:
    diff_path = out_dir / "change.diff"
    diff_path.write_text(_PATCH, encoding="utf-8")
    return DiffMaterialization(
        path=diff_path,
        base_ref="HEAD",
        line_count=_PATCH.count("\n"),
        empty=False,
    )


def _patch_offline_harness(monkeypatch: pytest.MonkeyPatch) -> None:
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
        offline_mod,
        "apply_diff_line_budget",
        lambda text, *, max_lines: (text, None),
    )
    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        lambda **_kwargs: None,
    )


def test_finish_does_not_store_when_structured_output_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: success + empty structured_output + json_path must not call store."""
    stores: list[object] = []
    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.store_review_result",
        lambda key, result: stores.append((key, result)),
    )
    json_path = tmp_path / "findings.json"
    finished = _finish_offline_result(
        OfflineReviewResult(success=True, structured_output=None, outcome=RunOutcome.passed),
        json_path=json_path,
        scope_reduction=None,
        cache_key="review-result:should-not-store",
    )
    assert finished.success is False
    assert finished.outcome is RunOutcome.configuration_error
    assert STRUCTURED_OUTPUT_REQUIRED_MSG in (finished.error or "")
    assert stores == []
    assert not json_path.exists()


def test_finish_does_not_store_when_structured_output_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: success + unparsable structured_output must not cache a fake pass."""
    stores: list[object] = []
    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.store_review_result",
        lambda key, result: stores.append((key, result)),
    )
    finished = _finish_offline_result(
        OfflineReviewResult(
            success=True,
            structured_output="{not-valid-findings",
            outcome=RunOutcome.passed,
        ),
        json_path=tmp_path / "findings.json",
        scope_reduction=None,
        cache_key="review-result:invalid",
    )
    assert finished.success is False
    assert stores == []


def test_finish_stores_structured_output_after_successful_finalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: post-finalize payload includes ``structured_output``."""
    _isolate_cache(tmp_path, monkeypatch)
    json_path = tmp_path / "findings.json"
    payload = _valid_structured_output()
    finished = _finish_offline_result(
        OfflineReviewResult(
            success=True,
            structured_output=payload,
            outcome=RunOutcome.passed,
        ),
        json_path=json_path,
        scope_reduction=None,
        cache_key="review-result:ok",
    )
    assert finished.success is True
    loaded = load_review_result("review-result:ok")
    assert loaded is not None
    assert loaded.structured_output == payload
    assert json_path.is_file()
    written = json.loads(json_path.read_text(encoding="utf-8"))
    assert written["findings"]


def test_cache_hit_with_json_path_finalizes_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: a cache hit still rewrites findings JSON (finalize on load)."""
    _isolate_cache(tmp_path, monkeypatch)
    payload = _valid_structured_output()
    store_review_result(
        "review-result:hit",
        OfflineReviewResult(
            success=True,
            structured_output=payload,
            outcome=RunOutcome.passed,
        ),
    )
    json_path = tmp_path / "out" / "findings.json"
    cached = load_review_result("review-result:hit")
    assert cached is not None
    finished = _finish_offline_result(
        cached,
        json_path=json_path,
        scope_reduction=None,
        cache_key=None,
    )
    assert finished.success is True
    assert json_path.is_file()
    assert json.loads(json_path.read_text(encoding="utf-8"))["findings"]


@pytest.mark.asyncio
async def test_offline_run_does_not_cache_empty_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: empty structured_output + ``json_path`` must not store; resume misses."""
    _isolate_cache(tmp_path, monkeypatch)
    _patch_offline_harness(monkeypatch)
    repo = _real_git_repo(tmp_path)
    stores: list[object] = []
    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.store_review_result",
        lambda key, result: stores.append((key, result)),
    )

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)

    async def _agent_empty(**kwargs: object) -> OfflineReviewResult:
        return OfflineReviewResult(
            success=True,
            output="looks fine",
            structured_output=None,
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_empty)

    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    json_path = tmp_path / "findings.json"
    first = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=json_path,
        use_cache=True,
        model="test-model",
    )
    assert first.success is False
    assert stores == []
    assert first.outcome is RunOutcome.configuration_error

    async def _agent_must_not_be_skipped(**kwargs: object) -> OfflineReviewResult:
        return OfflineReviewResult(
            success=False,
            error="agent re-ran because cache missed",
            outcome=RunOutcome.infra_error,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_must_not_be_skipped)
    second = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=json_path,
        use_cache=True,
        model="test-model",
    )
    assert second.success is False
    assert second.outcome is not RunOutcome.passed
    assert second.error == "agent re-ran because cache missed"


@pytest.mark.asyncio
async def test_offline_cache_hit_rewrites_findings_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: successful finalize is stored; ``--use-cache`` re-finalizes to json_path."""
    _isolate_cache(tmp_path, monkeypatch)
    _patch_offline_harness(monkeypatch)
    repo = _real_git_repo(tmp_path)
    payload = _valid_structured_output()

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)

    async def _agent_ok(**kwargs: object) -> OfflineReviewResult:
        return OfflineReviewResult(
            success=True,
            output="review",
            structured_output=payload,
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_ok)

    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    json_path = tmp_path / "findings.json"
    first = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=json_path,
        use_cache=True,
        model="test-model",
    )
    assert first.success is True
    assert json_path.is_file()
    json_path.unlink()

    async def _agent_must_not_run(**kwargs: object) -> OfflineReviewResult:
        raise AssertionError("cache hit must not re-run the agent")

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_must_not_run)
    second_path = tmp_path / "from-cache.json"
    second = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=second_path,
        use_cache=True,
        model="test-model",
    )
    assert second.success is True
    assert second.structured_output == payload
    assert second_path.is_file()
    assert json.loads(second_path.read_text(encoding="utf-8"))["findings"]


def _capture_cache_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[object], list[object]]:
    hashed: list[object] = []
    agent_models: list[object] = []
    real_key = __import__(
        "mergecraft.utils.review_result_cache", fromlist=["cache_key_for_diff_path"]
    ).cache_key_for_diff_path

    def _capture_key(path: Path, **kwargs: object) -> str:
        hashed.append(kwargs.get("model"))
        return real_key(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.cache_key_for_diff_path",
        _capture_key,
    )

    async def _agent_ok(**kwargs: object) -> OfflineReviewResult:
        agent_models.append(kwargs.get("model"))
        return OfflineReviewResult(
            success=True,
            output="review",
            structured_output=_valid_structured_output(),
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_ok)
    return hashed, agent_models


@pytest.mark.asyncio
async def test_cache_key_hashes_none_when_resolve_model_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: ``model=None`` hashes the same empty id the agent receives, not config slug."""
    _isolate_cache(tmp_path, monkeypatch)
    _patch_offline_harness(monkeypatch)
    repo = _real_git_repo(tmp_path)
    hashed_models: list[object] = []
    agent_models: list[object] = []

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    monkeypatch.setattr(offline_mod, "resolve_model", lambda slug=None, **_: None)
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve.resolve_effective_model_slug",
        lambda _settings: "config-opus",
    )
    if hasattr(offline_mod, "resolve_effective_model_slug"):
        monkeypatch.setattr(
            offline_mod, "resolve_effective_model_slug", lambda _settings: "config-opus"
        )

    real_key = __import__(
        "mergecraft.utils.review_result_cache", fromlist=["cache_key_for_diff_path"]
    ).cache_key_for_diff_path

    def _capture_key(path: Path, **kwargs: object) -> str:
        hashed_models.append(kwargs.get("model"))
        return real_key(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.cache_key_for_diff_path",
        _capture_key,
    )

    async def _agent_ok(**kwargs: object) -> OfflineReviewResult:
        agent_models.append(kwargs.get("model"))
        return OfflineReviewResult(
            success=True,
            output="review",
            structured_output=_valid_structured_output(),
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_ok)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=tmp_path / "findings.json",
        use_cache=True,
        model=None,
    )
    assert hashed_models
    assert hashed_models[0] in {None, ""}
    assert "config-opus" not in hashed_models
    assert agent_models
    assert agent_models[0] == hashed_models[0]


@pytest.mark.asyncio
async def test_cache_key_and_agent_share_resolved_model_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: a ``resolve_model`` slug is hashed and passed to the agent."""
    _isolate_cache(tmp_path, monkeypatch)
    _patch_offline_harness(monkeypatch)
    repo = _real_git_repo(tmp_path)
    hashed_models: list[object] = []
    agent_models: list[object] = []

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    monkeypatch.setattr(offline_mod, "resolve_model", lambda slug=None, **_: "resolved-opus")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve.resolve_effective_model_slug",
        lambda _settings: "config-sonnet",
    )

    real_key = __import__(
        "mergecraft.utils.review_result_cache", fromlist=["cache_key_for_diff_path"]
    ).cache_key_for_diff_path

    def _capture_key(path: Path, **kwargs: object) -> str:
        hashed_models.append(kwargs.get("model"))
        return real_key(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.cache_key_for_diff_path",
        _capture_key,
    )

    async def _agent_ok(**kwargs: object) -> OfflineReviewResult:
        agent_models.append(kwargs.get("model"))
        return OfflineReviewResult(
            success=True,
            output="review",
            structured_output=_valid_structured_output(),
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_ok)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=tmp_path / "findings.json",
        use_cache=True,
        model=None,
    )
    assert hashed_models == ["resolved-opus"]
    assert agent_models == ["resolved-opus"]


@pytest.mark.asyncio
async def test_resolved_model_cache_keys_do_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge: same diff, ``model=None`` vs a different resolved slug must miss."""
    _isolate_cache(tmp_path, monkeypatch)
    _patch_offline_harness(monkeypatch)
    repo = _real_git_repo(tmp_path)
    keys: list[str] = []

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)

    real_key = __import__(
        "mergecraft.utils.review_result_cache", fromlist=["cache_key_for_diff_path"]
    ).cache_key_for_diff_path

    def _capture_key(path: Path, **kwargs: object) -> str:
        key = real_key(path, **kwargs)  # type: ignore[arg-type]
        keys.append(key)
        return key

    monkeypatch.setattr(
        "mergecraft.utils.review_result_cache.cache_key_for_diff_path",
        _capture_key,
    )

    async def _agent_ok(**kwargs: object) -> OfflineReviewResult:
        return OfflineReviewResult(
            success=True,
            output="review",
            structured_output=_valid_structured_output(),
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent_ok)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)

    monkeypatch.setattr(offline_mod, "resolve_model", lambda slug=None, **_: "model-a")
    await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=tmp_path / "a.json",
        use_cache=True,
        model=None,
    )
    monkeypatch.setattr(offline_mod, "resolve_model", lambda slug=None, **_: "model-b")
    await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        json_path=tmp_path / "b.json",
        use_cache=True,
        model=None,
    )
    assert len(keys) == 2
    assert keys[0] != keys[1]
