"""An offline review always asks for structured findings, with or without a JSON file.

The result is parsed as findings either way. When no ``json_path`` was given,
``set_output`` used to take a plain string and the prompt asked for a markdown
``review``; a model that followed the prompt then failed the findings parse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.analyzers.finding import findings_output_schema
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec
from tests.offline_review.test_result_cache import (
    _isolate_cache,
    _nonempty_materialization,
    _patch_offline_harness,
    _real_git_repo,
    _valid_structured_output,
)


async def _run_without_json_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured_output: str
) -> tuple[OfflineReviewResult, dict[str, Any]]:
    _isolate_cache(tmp_path, monkeypatch)
    _patch_offline_harness(monkeypatch)
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
    seen: dict[str, Any] = {}

    async def _agent(**kwargs: Any) -> OfflineReviewResult:
        seen.update(kwargs)
        return OfflineReviewResult(
            success=True, structured_output=structured_output, outcome=RunOutcome.passed
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _agent)
    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False),
        spec=SourceResolverSpec(cwd=repo, invocation_root=repo),
        review_root=repo,
        json_path=None,
        use_cache=False,
        model="test-model",
    )
    return result, seen


@pytest.mark.asyncio
async def test_without_json_path_the_agent_gets_the_findings_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, seen = await _run_without_json_path(tmp_path, monkeypatch, _valid_structured_output())

    assert seen["output_schema"] == findings_output_schema()
    assert "Call `set_output` with structured findings" in str(seen["prompt"])
    assert "`set_output` with key `review`" not in str(seen["prompt"])


@pytest.mark.asyncio
async def test_without_json_path_structured_findings_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = await _run_without_json_path(tmp_path, monkeypatch, _valid_structured_output())

    assert result.success is True
    assert result.outcome is RunOutcome.passed
