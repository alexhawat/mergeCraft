"""CI wiring for advisory eval rescore delta (#1164)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from mergecraft.evals.rescore_delta import touches_reviewer_surface


def test_ci_workflow_mentions_eval_rescore_delta_job() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "eval-rescore-delta:" in text
    assert "ci_touches_reviewer_surface.py" in text


def test_reviewer_surface_helper_matches_modes_path() -> None:
    assert touches_reviewer_surface(["src/mergecraft/modes/Review.py"])


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("fail_base", [False, True])
def test_rescore_script_runs_older_base_cli_and_restores_checkout(
    tmp_path: Path, detached: bool, fail_base: bool
) -> None:
    """Execute the script across real checkouts with the pre-PR CLI contract."""
    from tests.analyzers.test_self_silencing import _commit_change, _git

    cli = """\
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

assert sys.argv[1:4] == ["run", "mergecraft", "eval"]
if sys.argv[4] == "rescore-delta":
    print("Pass-rate: 0.0 percentage points")
    sys.exit(0)
parser = argparse.ArgumentParser()
parser.add_argument("--json", action="store_true")
parser.add_argument("--results-dir", type=Path, required=True)
HEAD_OPTION
args = parser.parse_args(sys.argv[5:])
if os.environ.get("FAIL_BASE") == "1" and not hasattr(args, "no_update_latest"):
    sys.exit(7)
sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
payload = json.dumps({"commit": sha})
if not getattr(args, "no_update_latest", False):
    (args.results_dir / "latest.json").write_text(payload)
print(payload)
"""
    latest = "evals/results/latest.json"
    repo, _ = _commit_change(
        tmp_path,
        {"cli.py": cli.replace("HEAD_OPTION", ""), latest: "base baseline\n"},
        {
            "cli.py": cli.replace(
                "HEAD_OPTION", 'parser.add_argument("--no-update-latest", action="store_true")'
            ),
            latest: "head baseline\n",
        },
    )
    base = _git(repo, "rev-parse", "HEAD^").strip()
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    if detached:
        _git(repo, "checkout", "--detach", head)
    original_ref = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} cli.py "$@"\n')
    uv.chmod(0o755)
    results_dir = tmp_path / "results"
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", str(Path("scripts/eval_rescore_delta_pr.sh").resolve()), "main", "HEAD"],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "RESULTS_DIR": str(results_dir),
            "GITHUB_STEP_SUMMARY": str(summary),
            "FAIL_BASE": "1" if fail_base else "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (7 if fail_base else 0), result.stderr
    assert _git(repo, "rev-parse", "HEAD").strip() == head
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == original_ref
    assert _git(repo, "status", "--porcelain") == ""
    assert (repo / latest).read_text() == "head baseline\n"
    if not fail_base:
        assert json.loads((results_dir / "rescore-base.json").read_text())["commit"] == base
        assert json.loads((results_dir / "rescore-head.json").read_text())["commit"] == head
        assert "Pass-rate" in summary.read_text()


def test_rescore_delta_cli_prints_summary_on_stdout(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from mergecraft.cli.app import app
    from mergecraft.evals.benchmark import write_result_set
    from tests.evals.test_rescore_delta import _minimal_result

    runner = CliRunner()
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    base_set = _minimal_result(commit="base", rows=[])
    head_set = _minimal_result(commit="head", rows=[])
    write_result_set(base_set, results_dir=tmp_path, filename="base.json", update_latest=False)
    write_result_set(head_set, results_dir=tmp_path, filename="head.json", update_latest=False)

    result = runner.invoke(
        app,
        [
            "eval",
            "rescore-delta",
            "--baseline",
            str(base_path),
            "--candidate",
            str(head_path),
            "--output",
            str(tmp_path / "delta.json"),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Pass-rate" in result.stdout
    assert "Pass-rate" not in result.stderr or result.stdout.count("Pass-rate") >= 1
