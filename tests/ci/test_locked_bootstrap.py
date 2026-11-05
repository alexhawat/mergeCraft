"""The CI bootstrap rejects a stale lock before dependency installation can repair it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from tests.ci.workflow_support import REPO_ROOT


def test_ci_bootstrap_rejects_stale_lock_without_rewriting(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv, "uv is required for the repository's bootstrap contract"
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname = "bootstrap-fixture"\nversion = "1.0"\nrequires-python = ">=3.11"\n[project.optional-dependencies]\ndev = []\n'
    )
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv"),
        "UV_PYTHON": sys.executable,
        "UV_OFFLINE": "1",
        "CI": "true",
    }
    subprocess.run([uv, "lock"], cwd=tmp_path, env=env, check=True, capture_output=True)
    lock = tmp_path / "uv.lock"
    before = lock.read_bytes()
    project.write_text(project.read_text().replace('version = "1.0"', 'version = "2.0"'))
    shutil.copyfile(REPO_ROOT / "Makefile", tmp_path / "Makefile")
    action = yaml.safe_load((REPO_ROOT / ".github/actions/bootstrap/action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if "make setup" in step.get("run", ""))
    # Execute the actual checked-in bootstrap shell, with the local uv on PATH.
    env["PATH"] = f"{Path(uv).parent}:{os.environ['PATH']}"
    run = subprocess.run(
        ["bash", "-ec", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode != 0, run.stdout + run.stderr
    assert "locked" in run.stderr
    assert lock.read_bytes() == before
    assert not list((tmp_path / "venv").rglob("*.dist-info"))
