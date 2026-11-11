"""#1363 — the PR coverage delta waits for CI's artifact instead of re-measuring coverage."""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_SCRIPT = REPO_ROOT / "scripts" / "ci_fetch_coverage_artifact.sh"


def _fetch(tmp_path: Path, runs: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "runs.json").write_text(json.dumps({"workflow_runs": runs}), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'case "$2" in\n'
        f'  */actions/runs\\?*) cat "{tmp_path}/runs.json" ;;\n'
        "  */artifacts\\?*) echo '{\"artifacts\": []}' ;;\n"
        "esac\n",
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
            "MERGECRAFT_COVERAGE_ARTIFACT_STATUS": "any",
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([], 1),
        ([{"id": 1, "status": "in_progress"}], 1),
        ([{"id": 1, "status": "completed"}, {"id": 2, "status": "queued"}], 1),
        ([{"id": 1, "status": "completed"}], 3),
        ([{"id": 1, "status": "completed"}, {"id": 2, "status": "completed"}], 3),
    ],
)
def test_exit_status_separates_not_yet_from_never(
    tmp_path: Path, runs: list[dict[str, object]], expected: int
) -> None:
    assert _fetch(tmp_path, runs).returncode == expected


def test_head_wait_outlasts_a_busy_runner_pool_and_stops_when_ci_has_finished() -> None:
    steps = job(load_workflow("integration.yml"), "integration-pr")["steps"]
    head = next(s for s in steps if s.get("name") == "Fetch head coverage from ci.yml artifact")
    base = next(s for s in steps if str(s.get("name", "")).startswith("Fetch base coverage"))
    assert "seq 1 300" in head["run"], "a 6 minute wait gave up and re-ran the coverage gate"
    assert '"${rc}" -eq 3' in head["run"]
    assert '"${rc}" -eq 3' in base["run"]
    assert head["env"]["MERGECRAFT_COVERAGE_ARTIFACT_STATUS"] == "any"
    assert base["env"]["MERGECRAFT_COVERAGE_ARTIFACT_STATUS"] == "any"
