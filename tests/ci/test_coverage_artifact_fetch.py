"""#1363 — the PR coverage delta waits for CI's artifact instead of re-measuring coverage."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from typing import TYPE_CHECKING

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_SCRIPT = REPO_ROOT / "scripts" / "ci_fetch_coverage_artifact.sh"


_CI = ".github/workflows/ci.yml"
_CICD = ".github/workflows/ci-cd.yml"
_INTEGRATION = ".github/workflows/integration.yml"
_SELF_RUN = 900


def _run(run_id: int, status: str, path: str = _CI, artifact: bool = False) -> dict[str, object]:
    return {"id": run_id, "status": status, "path": path, "artifact": artifact}


def _fetch(tmp_path: Path, runs: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    api = {"workflow_runs": [{k: v for k, v in r.items() if k != "artifact"} for r in runs]}
    (tmp_path / "runs.json").write_text(json.dumps(api), encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "cov.zip", "w") as archive:
        archive.writestr("coverage.json", '{"totals": {}}')
    cases = ""
    for r in runs:
        listing = [{"id": 7, "name": "mergecraft-coverage-json", "expired": False}]
        body = json.dumps({"artifacts": listing if r["artifact"] else []})
        cases += f"  */actions/runs/{r['id']}/artifacts*) echo '{body}' ;;\n"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'case "$2" in\n'
        f'  */actions/runs\\?*) cat "{tmp_path}/runs.json" ;;\n'
        f'  */artifacts/7/zip) cat "{tmp_path}/cov.zip" ;;\n' + cases + "esac\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return subprocess.run(
        ["bash", str(_SCRIPT), "a" * 40, str(tmp_path / "out.json")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "acme/demo",
            "GH_TOKEN": "fixture",
            "GITHUB_RUN_ID": str(_SELF_RUN),
            "MERGECRAFT_COVERAGE_ARTIFACT_STATUS": "any",
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        # publisher still running: keep waiting
        ([_run(1, "in_progress")], 1),
        ([_run(1, "queued"), _run(2, "completed")], 1),
        # publisher finished with the artifact: found
        ([_run(1, "completed", artifact=True)], 0),
        ([_run(1, "in_progress", artifact=True)], 0),
        # publisher finished without it (failed or cancelled): stop at once
        ([_run(1, "completed")], 3),
        ([_run(1, "completed"), _run(2, "completed")], 3),
        # only the polling Integration run itself, or other workflows, in the list
        ([_run(_SELF_RUN, "in_progress", _INTEGRATION)], 3),
        ([_run(5, "in_progress", _INTEGRATION)], 3),
        ([_run(_SELF_RUN, "in_progress", _INTEGRATION), _run(1, "completed")], 3),
        ([_run(_SELF_RUN, "in_progress", _INTEGRATION), _run(1, "in_progress")], 1),
        # our own run id is never a publisher, even on a publisher path
        ([_run(_SELF_RUN, "in_progress")], 3),
        # ci-cd publishes the base coverage on main
        ([_run(1, "in_progress", _CICD)], 1),
        ([_run(1, "completed", _CICD)], 3),
    ],
)
def test_exit_status_tracks_whether_a_publisher_can_still_deliver(
    tmp_path: Path, runs: list[dict[str, object]], expected: int
) -> None:
    result = _fetch(tmp_path, runs)
    assert result.returncode == expected, result.stderr
    if expected == 0:
        assert json.loads((tmp_path / "out.json").read_text())["totals"] == {}


def test_head_wait_outlasts_a_busy_runner_pool_and_stops_when_ci_has_finished() -> None:
    steps = job(load_workflow("integration.yml"), "integration-pr")["steps"]
    head = next(s for s in steps if s.get("name") == "Fetch head coverage from ci.yml artifact")
    base = next(s for s in steps if str(s.get("name", "")).startswith("Fetch base coverage"))
    assert "seq 1 300" in head["run"], "a 6 minute wait gave up and re-ran the coverage gate"
    assert '"${rc}" -eq 3' in head["run"]
    assert '"${rc}" -eq 3' in base["run"]
    assert head["env"]["MERGECRAFT_COVERAGE_ARTIFACT_STATUS"] == "any"
    assert base["env"]["MERGECRAFT_COVERAGE_ARTIFACT_STATUS"] == "any"
