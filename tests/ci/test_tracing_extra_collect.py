"""CI contracts for the optional ``[tracing]`` extra collection (TH8 / D14)."""

from __future__ import annotations

import subprocess

from tests.ci.workflow_support import REPO_ROOT


def test_subprocess_without_tracing_extra_still_collects_repo() -> None:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            "tests/tracing/exporters",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_subprocess_with_tracing_extra_collects_exporter_tests() -> None:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--extra",
            "tracing",
            "python",
            "-m",
            "pytest",
            "tests/tracing/exporters",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    combined = proc.stdout + proc.stderr
    assert "no tests collected" not in combined.lower(), combined
    assert " collected" in combined or " test" in combined, combined
