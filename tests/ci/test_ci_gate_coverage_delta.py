"""W1.2 — coverage delta gate contracts (wave 16, green after W3)."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from tests.ci.support_ci_gate_coverage import (
    base_measure_block,
    break_coverage_measure,
    clone_local_repo,
    git,
    install_bare_origin,
    noop_coverage_measure,
    resolve_push_branch,
    run_coverage_delta_gate,
    script_text,
    seed_passing_coverage_json,
    worktree_path,
)
from tests.ci.test_coverage_delta_wrapper import (
    _BASE_MEASURE_MARKER,
    _base_worktree_block,
)

if TYPE_CHECKING:
    from pathlib import Path

_INTEGRATION_TIMEOUT = 180


def _bootstrap_broken_base(scratch: Path, tmp_path: Path, base_ref: str = "broken-base") -> None:
    install_bare_origin(scratch, tmp_path)
    break_coverage_measure(scratch / "Makefile")
    git(scratch, "checkout", "-b", base_ref)
    git(scratch, "add", "Makefile")
    git(scratch, "commit", "-m", "break base coverage-measure")
    git(scratch, "push", "-u", "origin", base_ref)
    git(scratch, "checkout", "-b", "feature-head")
    git(scratch, "checkout", f"{base_ref}^", "--", "Makefile")
    noop_coverage_measure(scratch / "Makefile")
    seed_passing_coverage_json(scratch / "coverage.json")
    git(scratch, "add", "Makefile")
    git(scratch, "commit", "-m", "fast head coverage gate for integration tests")
    git(scratch, "push", "-u", "origin", "feature-head")


def test_base_measure_block_markers_remain_parseable() -> None:
    """D7 — ``BASE_WORKTREE_MEASURE_BLOCK`` stays where the wrapper test expects."""
    block = _base_worktree_block(script_text())
    assert "make coverage-measure" in block or "coverage-gate:" in block
    assert _BASE_MEASURE_MARKER in script_text()


def test_base_measure_block_exports_uv_project_environment() -> None:
    """Regression guard — ``UV_PROJECT_ENVIRONMENT`` export must survive W3 edits."""
    block = base_measure_block()
    assert 'export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"' in block
    assert "${UV_PROJECT_ENVIRONMENT:-" not in block


def test_base_measure_block_keeps_pre_th_inline_fallback() -> None:
    """Regression guard — pre-TH inline measure fallback must survive W3 edits."""
    block = base_measure_block()
    assert "grep -q '^coverage-measure:' Makefile" in block
    assert "--cov-report=json:coverage.json" in block


def test_head_coverage_gate_stays_unguarded_outside_subshell() -> None:
    """D5 guard — head ``make coverage-gate`` must not be wrapped in a tolerant guard."""
    text = script_text()
    tail = text.split(")\n", 1)[-1]
    assert re.search(r"^make coverage-gate\s*$", tail, re.MULTILINE), (
        "head make coverage-gate must remain a hard gate after the subshell"
    )
    assert "make coverage-gate ||" not in tail


def test_successful_base_measurement_still_runs_delta_comparison() -> None:
    """Regression guard — a healthy base must still reach the delta comparison tail."""
    text = script_text()
    assert "if [[ -f coverage-base.json ]]; then" in text
    assert "check_coverage_delta.py" in text


def test_worktree_cleaned_up_when_base_measurement_fails(tmp_path: Path) -> None:
    """The trap must remove the base worktree even when measurement fails."""
    scratch = clone_local_repo(tmp_path)
    _bootstrap_broken_base(scratch, tmp_path)
    wt = worktree_path(scratch)

    run_coverage_delta_gate(scratch, base_ref="broken-base", timeout=_INTEGRATION_TIMEOUT)

    assert not wt.exists()


def test_broken_base_measurement_exits_zero_without_base_json(tmp_path: Path) -> None:
    """D4 — a red base is a signal, not a script-killing pre-gate."""
    scratch = clone_local_repo(tmp_path)
    _bootstrap_broken_base(scratch, tmp_path)

    result = run_coverage_delta_gate(scratch, base_ref="broken-base", timeout=_INTEGRATION_TIMEOUT)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (scratch / "coverage-base.json").is_file()


def test_skipped_delta_emits_warning_with_reason(tmp_path: Path) -> None:
    """D6 — a skipped delta must be visible, not silent."""
    scratch = clone_local_repo(tmp_path)
    _bootstrap_broken_base(scratch, tmp_path)

    result = run_coverage_delta_gate(scratch, base_ref="broken-base", timeout=_INTEGRATION_TIMEOUT)
    combined = (result.stdout + result.stderr).lower()

    assert result.returncode == 0, combined
    assert "warn" in combined or "::warning" in combined
    assert "base" in combined or "broken-base" in combined
    assert "measure" in combined or "coverage" in combined


def test_base_measure_block_tolerates_setup_failures() -> None:
    """Regression guard — uv sync / setup-local-analyzers failures must not abort the gate."""
    block = base_measure_block()
    assert "set +e" in block
    assert "measure_ok=false" in block
    assert "uv}" in block or "${UV:-uv}" in block
    assert "setup-local-analyzers" in block


def test_install_bare_origin_pushes_from_detached_head(tmp_path: Path) -> None:
    """Detached HEAD must not push the literal branch name ``HEAD``."""
    scratch = clone_local_repo(tmp_path)
    install_bare_origin(scratch, tmp_path)
    git(scratch, "checkout", "--detach", "HEAD")
    branch = resolve_push_branch(scratch, fallback="detached-ci-gate-head")
    assert branch == "detached-ci-gate-head"
    git(scratch, "push", "-u", "origin", branch)


def test_base_uv_sync_failure_still_warns_and_skips_delta(tmp_path: Path) -> None:
    """Base ``uv sync`` failure must reach the warn-and-skip path, not abort under set -e."""
    import shutil

    real_uv = shutil.which("uv")
    assert real_uv is not None, "uv must be on PATH for this integration test"
    wrapper = tmp_path / "uv"
    wrapper.write_text(
        f"""#!/usr/bin/env bash
case "$PWD" in
  *".ci-mergecraft-base-coverage"*)
    echo "uv sync failed (test)" >&2
    exit 1
    ;;
esac
exec {real_uv} "$@"
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    scratch = clone_local_repo(tmp_path)
    _bootstrap_broken_base(scratch, tmp_path)

    result = run_coverage_delta_gate(
        scratch,
        base_ref="broken-base",
        extra_env={"UV": str(wrapper), "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"},
        timeout=_INTEGRATION_TIMEOUT,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert not (scratch / "coverage-base.json").is_file()
    assert "warn" in combined.lower() or "::warning" in combined.lower()


def test_head_coverage_regression_still_fails_when_base_skips(tmp_path: Path) -> None:
    """D5 — relaxing only the base must not disable the head ratchet."""
    scratch = clone_local_repo(tmp_path)
    _bootstrap_broken_base(scratch, tmp_path)
    bad = {
        "totals": {"percent_covered": 0.0, "num_statements": 100, "covered_lines": 0},
        "files": {},
    }
    (scratch / "coverage.json").write_text(json.dumps(bad), encoding="utf-8")

    result = run_coverage_delta_gate(scratch, base_ref="broken-base", timeout=_INTEGRATION_TIMEOUT)
    combined = (result.stdout + result.stderr).lower()

    assert result.returncode != 0, "head coverage regression must still fail the gate"
    assert not (scratch / "coverage-base.json").is_file()
    assert "coverage-gate" in combined or "ratchet" in combined or "fail_under" in combined
