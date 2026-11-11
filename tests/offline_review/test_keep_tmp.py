"""An offline review's temp directory is removed at exit unless ``MERGECRAFT_KEEP_TMP`` is set.

The directory holds the materialized diff, prompts, agent scratch and (by
default) the evidence packet. It is removed by an exit hook, not on return,
because the CLI still prints and persists paths inside it after the review.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils import git_setup
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec
from tests.offline_review.test_result_cache import (
    _isolate_cache,
    _nonempty_materialization,
    _patch_offline_harness,
    _real_git_repo,
    _valid_structured_output,
)


async def _review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    write_artifacts: Callable[[Path], OfflineReviewResult] | None = None,
) -> tuple[OfflineReviewResult, Path, Path, list[Callable[[], None]]]:
    """Run the real offline lifecycle with a stub agent; return the result and its temp dir."""
    hooks: list[Callable[[], None]] = []
    monkeypatch.setattr(git_setup, "_cleanup_at_exit", {})
    monkeypatch.setattr(git_setup, "_cleanup_registered", False)
    monkeypatch.setattr(git_setup.atexit, "register", hooks.append)
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
        if write_artifacts is not None:
            return write_artifacts(Path(kwargs["tmpdir"]))
        return OfflineReviewResult(
            success=True, structured_output=_valid_structured_output(), outcome=RunOutcome.passed
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
    return result, Path(seen["tmpdir"]), Path(seen["materialization"].path), hooks


@pytest.mark.asyncio
async def test_the_review_temp_dir_is_removed_at_exit_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MERGECRAFT_KEEP_TMP", raising=False)

    result, out_dir, diff, hooks = await _review(tmp_path, monkeypatch)

    assert result.success is True
    assert out_dir.name.startswith("mergecraft-diff-review-")
    # Still there on return: the CLI prints and reads the diff afterwards.
    assert diff.is_file()
    assert diff.is_relative_to(out_dir)
    assert hooks == [git_setup._remove_scheduled_directories]

    for hook in hooks:
        hook()

    assert not out_dir.exists()


@pytest.mark.asyncio
async def test_keep_tmp_keeps_the_review_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MERGECRAFT_KEEP_TMP", "1")

    result, out_dir, diff, hooks = await _review(tmp_path, monkeypatch)

    assert result.success is True
    assert hooks == []
    git_setup._remove_scheduled_directories()
    assert out_dir.is_dir()
    assert diff.is_file()
    assert diff.is_relative_to(out_dir)
    shutil.rmtree(out_dir)


def _write_run_artifacts(tmpdir: Path, *, packet: bool) -> OfflineReviewResult:
    """Write what a real run leaves, at the paths the production resolvers return."""
    from types import SimpleNamespace

    from mergecraft.evidence.run_packet import resolve_packet_path
    from mergecraft.evidence.verdict_capture import resolve_capture_dir

    scratch = tmpdir / "home" / "agent-scratch.txt"
    scratch.parent.mkdir(parents=True)
    scratch.write_text("scratch", encoding="utf-8")
    capture = resolve_capture_dir(tmpdir=str(tmpdir)) / "judge-verdicts.jsonl"
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text("{}\n", encoding="utf-8")
    result = OfflineReviewResult(
        success=True, structured_output=_valid_structured_output(), outcome=RunOutcome.passed
    )
    if packet:
        packet_path = resolve_packet_path(tmpdir=str(tmpdir), change_slug="local-repo")
        packet_path.write_text("{}", encoding="utf-8")
        result.evidence_packet_path = str(packet_path)
    shadow = offline_mod._jev_shadow_artifact_path(
        result,
        SimpleNamespace(out_dir=tmpdir),  # type: ignore[arg-type]
    )
    shadow.write_text("{}\n", encoding="utf-8")
    result.jev_shadow_path = str(shadow)
    return result


def _missing(paths: list[str]) -> list[str]:
    return [path for path in paths if not Path(path).is_file()]


@pytest.mark.parametrize("packet", [True, False], ids=["with_packet", "without_packet"])
@pytest.mark.asyncio
async def test_default_cleanup_keeps_the_artifacts_a_result_points_to(
    packet: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The packet, the Jev shadow log and captured verdicts outlive the exit hook."""
    monkeypatch.delenv("MERGECRAFT_KEEP_TMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)

    result, out_dir, diff, hooks = await _review(
        tmp_path,
        monkeypatch,
        write_artifacts=lambda tmpdir: _write_run_artifacts(tmpdir, packet=packet),
    )
    for hook in hooks:
        hook()

    durable = [result.jev_shadow_path, out_dir / "evidence" / "judge-verdicts.jsonl"]
    if packet:
        durable.append(result.evidence_packet_path)
    assert all(path is not None for path in durable)
    assert _missing([str(path) for path in durable]) == []
    assert not diff.exists()
    assert not (out_dir / "home").exists()
    shutil.rmtree(out_dir)
