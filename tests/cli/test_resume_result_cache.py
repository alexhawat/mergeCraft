"""``--resume`` is the local review-result cache, not ``resume_review``."""

from __future__ import annotations

import inspect
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import mergecraft.offline_review as offline_mod
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.config.settings import RepoSettings
from mergecraft.offline_review import _run_offline_diff_review, run_offline_diff_review
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_offline_review_hot_path_does_not_export_resume_review() -> None:
    """Unit: ``offline_review`` must not export ``resume_review``."""
    assert not hasattr(offline_mod, "resume_review")


def _real_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_offline_review_hot_path_does_not_call_resume_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit: ``_run_offline_diff_review`` must not call ``resume_review``."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline review must not call resume_review")

    monkeypatch.setattr("mergecraft.reliability.recovery.resume_review", _boom)
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
    repo = _real_git_repo(tmp_path)
    patch = (
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
    )

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        diff_path = out_dir / "change.diff"
        diff_path.write_text(patch, encoding="utf-8")
        return DiffMaterialization(
            path=diff_path,
            base_ref="HEAD",
            line_count=patch.count("\n"),
            empty=False,
        )

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        dry_run=True,
    )


def test_review_help_documents_resume_as_local_result_cache() -> None:
    """Happy: ``review --help`` describes ``--resume`` as the same cache as ``--use-cache``."""
    result = runner.invoke(app, ["review", "--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    compact = " ".join(help_text.split()).casefold()
    assert "--resume" in compact
    assert "--use-cache" in compact
    assert "result cache" in compact
    assert "does not restore" in compact
    assert "a live agent" in compact
    assert "checkpoint" in compact


def test_run_offline_diff_review_has_no_distinct_resume_parameter() -> None:
    """Unit: ``--resume`` is the same read policy as ``--use-cache`` (one bool)."""
    params = inspect.signature(run_offline_diff_review).parameters
    assert "use_cache" in params
    assert "resume" not in params


def test_run_offline_diff_review_body_has_no_distinct_resume_parameter() -> None:
    """Unit: the private runner also has only ``use_cache`` (CLI folds ``--resume``)."""
    params = inspect.signature(_run_offline_diff_review).parameters
    assert "use_cache" in params
    assert "resume" not in params
