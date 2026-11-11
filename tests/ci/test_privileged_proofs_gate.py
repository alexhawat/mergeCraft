"""#1300 — the privileged boundary proofs block merge through a required job, path-filtered."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, as_list, job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_SCRIPT = REPO_ROOT / "scripts" / "ci_touches_privileged_surface.py"
_PROOFS = (
    "make test-filtered-egress",
    "make test-sandbox-privileged",
    "make test-uid-drop-privileged",
)


def _touches(paths: list[str]) -> bool:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import ci_touches_privileged_surface as module

    return module.touches_privileged_surface(paths)


@pytest.mark.parametrize(
    "path",
    [
        "src/mergecraft/analyzers/sandbox.py",
        "src/mergecraft/analyzers/egress_userspace.py",
        "src/mergecraft/analyzers/egress.py",
        "src/mergecraft/analyzers/run.py",
        "src/mergecraft/analyzers/execution.py",
        "src/mergecraft/analyzers/detect.py",
        "src/mergecraft/analyzers/resolve.py",
        "src/mergecraft/analyzers/trust.py",
        "src/mergecraft/security/broker.py",
        "src/mergecraft/utils/privilege.py",
        "docker/Dockerfile",
        "docker/e2e/run_in_image_privilege.sh",
        ".github/workflows/ci.yml",
        "tests/analyzers/test_filtered_egress.py",
    ],
)
def test_protected_paths_select_the_proofs(path: str) -> None:
    assert _touches(["README.md", path])


@pytest.mark.parametrize(
    "path",
    ["docs/guide.md", "src/mergecraft/cli/main.py", "src/mergecraft/analyzers/registry.py"],
)
def test_unrelated_paths_skip_the_proofs(path: str) -> None:
    assert not _touches([path])


def test_empty_diff_runs_the_proofs() -> None:
    assert _touches([])


def _classify(tmp_path: Path, event: str, name: str) -> tuple[str, str]:
    out = tmp_path / name
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--event", event, "--base", "main"],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_OUTPUT": str(out)},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), out.read_text(encoding="utf-8").strip()


def test_non_pull_request_events_and_unreadable_diffs_always_run(tmp_path: Path) -> None:
    assert _classify(tmp_path, "push", "a") == ("true", "run=true")
    # tmp_path is not a repository, so the diff cannot be read: never skip.
    assert _classify(tmp_path, "pull_request", "b") == ("true", "run=true")


def _vcs(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


def test_pull_request_diff_decides(tmp_path: Path) -> None:
    _vcs(tmp_path, "init", "-q", "-b", "main")
    _vcs(tmp_path, "config", "user.email", "t@example.com")
    _vcs(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.md").write_text("a")
    _vcs(tmp_path, "add", ".")
    _vcs(tmp_path, "commit", "-q", "-m", "base")
    _vcs(tmp_path, "checkout", "-q", "-b", "pr")
    (tmp_path / "b.md").write_text("b")
    _vcs(tmp_path, "add", ".")
    _vcs(tmp_path, "commit", "-q", "-m", "docs")
    assert _classify(tmp_path, "pull_request", "o1")[0] == "false"
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "Dockerfile").write_text("FROM scratch")
    _vcs(tmp_path, "add", ".")
    _vcs(tmp_path, "commit", "-q", "-m", "image")
    assert _classify(tmp_path, "pull_request", "o2")[0] == "true"


def test_required_static_job_needs_the_proofs_job_and_it_is_not_continue_on_error() -> None:
    ci = load_workflow("ci.yml")
    assert "privileged-proofs" in as_list(job(ci, "static")["needs"])
    proofs = job(ci, "privileged-proofs")
    assert not proofs.get("continue-on-error", False)
    runs = [str(step.get("run", "")) for step in proofs["steps"]]
    for target in _PROOFS:
        step = next(s for s in proofs["steps"] if target in str(s.get("run", "")))
        assert step["if"] == "steps.surface.outputs.run == 'true'"
        assert not step.get("continue-on-error", False)
    assert any("ci_touches_privileged_surface.py" in run and "show" in run for run in runs)
    assert any("python3 -I" in run for run in runs)


def test_integration_workflow_no_longer_carries_a_non_required_copy() -> None:
    assert "filtered-egress" not in load_workflow("integration.yml")["jobs"]


def test_a_skipped_proofs_job_cannot_pass_a_code_pr() -> None:
    """The guard accepts a skip only for an image-only PR; the job itself never skips otherwise."""
    guard = job(load_workflow("ci.yml"), "static")["steps"][0]["run"]
    needs = as_list(job(load_workflow("ci.yml"), "static")["needs"])

    def code(result: str) -> int:
        results: dict[str, Any] = {n: {"result": "success"} for n in needs}
        results["privileged-proofs"] = {"result": result}
        results["changes"] = {
            "result": "success",
            "outputs": {"code": "true", "image_only": "false"},
        }
        env = {
            **os.environ,
            "REQUIRED_JOB_RESULTS": json.dumps(results),
            "EVENT_NAME": "pull_request",
        }
        return subprocess.run(
            ["bash", "-ec", guard], env=env, capture_output=True, text=True, check=False
        ).returncode

    assert code("success") == 0
    assert code("failure") == 1
    assert code("skipped") == 1
