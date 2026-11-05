"""Keep reviewed source identity separate from caller and durable storage."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.review.completed import load_completed_review
from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.source_resolve import AcquiredSource, AuthResolution

if TYPE_CHECKING:
    from mergecraft.utils.source_resolve import ReviewSource


def _repo(path: Path, label: str) -> str:
    path.mkdir()
    (path / ".mergecraft").mkdir()
    body = f"{{}} # {label}\n"
    (path / ".mergecraft" / "config.yaml").write_text(body)
    subprocess.run(["git", "init", "-qb", "main"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            label,
        ],
        cwd=path,
        check=True,
    )
    return body


@pytest.mark.parametrize("remote", [False, True])
def test_resolved_source_controls_snapshot_manifest_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: bool
) -> None:
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    _repo(caller, "caller")
    target_config = _repo(target, "reviewed")
    monkeypatch.chdir(caller)
    monkeypatch.setenv("MERGECRAFT_REVIEW_ID", "source-provenance")
    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    seen: list[Path] = []

    async def review(**kwargs: Any) -> OfflineReviewResult:
        # Only replace the provider-facing driver. Real source resolution,
        # snapshot update, CLI publication and durable storage still execute.
        seen.append(kwargs["cwd"])
        assert (kwargs["cwd"] / ".mergecraft" / "config.yaml").read_text() == target_config
        return OfflineReviewResult(
            success=True,
            output="Reviewed",
            structured_output='{"findings": []}',
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr("mergecraft.offline_review._run_offline_diff_review", review)
    source = str(target)
    expected_source = str(target)
    storage = target
    if remote:
        source = "https://github.com/example/reviewed.git"
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=target, check=True, capture_output=True, text=True
        ).stdout.strip()
        expected_source = f"{source}@{head}"
        storage = caller

        def acquire(source: ReviewSource, *, dest: Path) -> AcquiredSource:
            shutil.copytree(target, dest, dirs_exist_ok=True)
            return AcquiredSource(path=dest, workspace_root=dest)

        monkeypatch.setattr("mergecraft.utils.source_resolve.acquire", acquire)
        monkeypatch.setattr(
            "mergecraft.utils.source_resolve.resolve_auth_token",
            lambda **_: AuthResolution(token=None, source="anonymous"),
        )
    result = CliRunner().invoke(app, ["review", "--cwd", str(caller), "--repo", source])
    assert result.exit_code == 0, result.output
    assert len(seen) == 1
    completed = load_completed_review("source-provenance", repo_root=storage)
    assert completed is not None
    assert completed.snapshot.source == expected_source
    assert completed.manifest["config_hash"] == hashlib.sha256(target_config.encode()).hexdigest()
    other = target if remote else caller
    assert not (other / ".mergecraft" / "reviews").exists()
    if remote:
        assert seen[0] != caller
        assert seen[0] != target
        shutil.rmtree(seen[0])
