"""Offline audit reproducers for main 55cf88e33c318a8b03a251fb0f8b6dad9d999141.

Run from the audit checkout with PYTHONDONTWRITEBYTECODE=1 and PYTHONPATH=src.
The accompanying Markdown memo gives a Make invocation using an existing
interpreter. No pytest, install, model, network, real browser, or consumer-test
execution is needed. Only disposable fixtures are written. These assertions
describe the audited defects: a future fix should make the relevant assertion
fail, prompting reclassification rather than removal of the evidence.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def emit(probe: str, **values: object) -> None:
    print(json.dumps({"probe": probe, **values}, sort_keys=True))  # noqa: T201 -- probe output is the script's purpose


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def init_repo(repo: Path) -> None:
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (repo / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "tracked.py")
    git(
        repo,
        "-c",
        "user.name=Offline Audit Fixture",
        "-c",
        "user.email=offline-audit@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "fixture",
    )


def run_probes(temp_root: Path) -> None:
    # Imports and CLI calls run inside the cleared credential environment.
    from loguru import logger
    from typer.testing import CliRunner

    from mergecraft.ci import local_evidence
    from mergecraft.cli.app import app
    from mergecraft.cli.config_surface_cmd import validate_repo_config_or_raise
    from mergecraft.config import load_repo_settings
    from mergecraft.offline_review import _OfflineDiffReviewRun
    from mergecraft.utils.offline_diff import materialize_diff
    from mergecraft.utils.source_resolve import (
        ResolvedWorkspace,
        SourceResolverSpec,
        materialize_resolved_diff,
    )
    from mergecraft.verify.models import VerificationInput
    from mergecraft.verify.runner import run_verify_behavior

    logger.remove()
    runner = CliRunner()

    # C3: local YAML is an overlay, not a replacement of unrelated base keys.
    config_repo = temp_root / "config-repo"
    config_dir = config_repo / ".mergecraft"
    config_dir.mkdir(parents=True)
    committed = config_dir / "config.yaml"
    committed.write_text("shell: disabled\n", encoding="utf-8")
    (config_dir / "config.local.yaml").write_text("models: []\n", encoding="utf-8")
    control = load_repo_settings(root=config_repo, load_learnings_files=False)
    assert control.shell == "disabled"
    committed.write_text("shell: disabled\nrunBounds: [\n", encoding="utf-8")
    validation = runner.invoke(app, ["config", "validate", "--cwd", str(config_repo)])
    validate_repo_config_or_raise(cwd=config_repo)
    runtime = load_repo_settings(root=config_repo, load_learnings_files=False)
    assert validation.exit_code == 0
    assert runtime.shell == "restricted"
    emit(
        "C3_lower_layer_config",
        valid_base_shell=control.shell,
        malformed_base_shell=runtime.shell,
        validate_exit=validation.exit_code,
        review_preflight_accepted=True,
        runtime_loaded=True,
    )

    # C1: ordinary ignored dependency files are not changed source files.
    repo = temp_root / "repo"
    init_repo(repo)
    (repo / ".venv").mkdir()
    (repo / ".venv" / "installed").write_text("fixture\n", encoding="utf-8")
    status = git(repo, "status", "--porcelain")
    materialization = materialize_diff(cwd=repo, out_dir=temp_root / "default-diff", base="main")
    result = runner.invoke(app, ["review", "--cwd", str(repo), "--base", "main", "--dry-run"])
    assert status == ""
    assert materialization.empty
    assert any(".venv/" in row for row in materialization.coverage_limitations)
    assert result.exit_code == 20
    emit(
        "C1_clean_ignored",
        git_status=status,
        empty=materialization.empty,
        limitations=list(materialization.coverage_limitations),
        cli_exit=result.exit_code,
    )

    # C2: eligible oversized source is excluded, but --unstaged loses the reason.
    (repo / "big.py").write_text("x = 1\n" * 70_000, encoding="utf-8")
    materialization = materialize_resolved_diff(
        workspace=ResolvedWorkspace(cwd=repo, git_common_dir=None, cloned=False),
        spec=SourceResolverSpec(cwd=repo, unstaged=True),
        out_dir=temp_root / "unstaged-diff",
    )
    result = asyncio.run(
        _OfflineDiffReviewRun.review(
            SimpleNamespace(materialization=materialization, json_path=None, scope_reduction=None)
        )
    )
    assert materialization.empty
    assert materialization.coverage_limitations == ()
    assert result.success
    assert str(result.outcome) == "passed"
    emit(
        "C2_unstaged_excluded",
        empty=materialization.empty,
        limitations=list(materialization.coverage_limitations),
        success=result.success,
        outcome=str(result.outcome),
    )

    # R3: real CLI dispatch, but an empty external diff and --dry-run avoid agents.
    empty_diff = temp_root / "empty.diff"
    empty_diff.write_text("", encoding="utf-8")
    for output_format in ("jsonl", "sarif"):
        result = runner.invoke(
            app,
            [
                "review",
                "--cwd",
                str(repo),
                "--diff",
                str(empty_diff),
                "--output-format",
                output_format,
                "--dry-run",
            ],
        )
        error_present = "--output is required" in result.stdout + result.stderr
        assert result.exit_code == 0
        assert error_present
        emit(
            "R3_missing_output",
            output_format=output_format,
            cli_exit=result.exit_code,
            error_present=error_present,
        )

    # C4: real runner until the subprocess boundary; no application is launched.
    target = temp_root / "verification-target"
    target.mkdir()
    spec = VerificationInput(
        mode="verify",
        repo_path=str(target),
        startup_command="python app.py",
        base="other-branch",
        base_url="http://127.0.0.1:1",
        issue_or_pr="",
        acceptance_criteria=[],
        auth={"strategy": "mock"},
        credential_env_names=[],
        artifacts_dir="",
        viewport={"width": 1280, "height": 720},
        device_targets=[],
        allowed_network=[],
        forbidden_network=[],
        prior_screenshots=[],
        repro_notes="",
    )
    spawn = AsyncMock(return_value=SimpleNamespace(returncode=0))
    with (
        patch("mergecraft.verify.runner.asyncio.create_subprocess_exec", spawn),
        patch("mergecraft.verify.runner.asyncio.sleep", new=AsyncMock()),
    ):
        result = asyncio.run(run_verify_behavior(spec, offline=True, shell="enabled"))
    assert spawn.call_count == 1
    assert "cwd" not in spawn.call_args.kwargs
    assert Path(spec.repo_path) != Path.cwd()
    emit(
        "C4_verify_repo",
        supplied_repo=str(target),
        subprocess_cwd=spawn.call_args.kwargs.get("cwd"),
        inherited_cwd=str(Path.cwd()),
        status=result.status,
    )

    # C5: record selected toolchain; no sandbox, coverage, or consumer tests run.
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"synthetic failure")

    scratch = temp_root / "coverage-scratch"
    scratch.mkdir()
    logger.remove()
    with (
        patch(
            "mergecraft.ci.local_evidence.shutil.which", return_value="/consumer/.venv/bin/coverage"
        ),
        patch(
            "mergecraft.ci.local_evidence._sandboxed_argv", side_effect=lambda argv, **kwargs: argv
        ),
        patch("mergecraft.ci.local_evidence.tempfile.mkdtemp", return_value=str(scratch)),
        patch("mergecraft.ci.local_evidence.subprocess.run", side_effect=fake_run),
    ):
        available = local_evidence._coverage_toolchain_available()
        artifact = local_evidence._execute_coverage(target, timeout_seconds=1)
    assert available
    assert "/consumer/.venv/bin/coverage" not in calls[0]
    assert calls[0][1:4] == ["-m", "coverage", "run"]
    emit(
        "C5_coverage_interpreter",
        path_toolchain_available=available,
        selected_python=calls[0][0],
        path_coverage_used=False,
        cli_env_has_coverage=importlib.util.find_spec("coverage") is not None,
        cli_env_has_pytest=importlib.util.find_spec("pytest") is not None,
        artifact=str(artifact),
    )


def main() -> None:
    # Do not inspect or print actual credentials. Disable global Git configuration
    # and all inherited provider/tracing configuration for disposable fixtures.
    safe_env = {
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    with (
        patch.dict(os.environ, safe_env, clear=True),
        tempfile.TemporaryDirectory(prefix="mergecraft-cli-audit-") as temp_dir,
    ):
        run_probes(Path(temp_dir))


if __name__ == "__main__":
    main()
