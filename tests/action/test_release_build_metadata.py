"""Image build source stamping must not invent its future digest or manifest SHA."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from tests.ci.workflow_support import REPO_ROOT


@pytest.mark.parametrize("revision", ["a" * 40, ""])
def test_docker_source_stamp_records_only_valid_source(tmp_path: Path, revision: str) -> None:
    line = next(
        line
        for line in (REPO_ROOT / "Dockerfile").read_text().splitlines()
        if line.startswith("RUN SOURCE_REVISION=")
    )
    argv = shlex.split(line)
    source = argv[argv.index("-c") + 1]
    metadata = tmp_path / "src/mergecraft/_build_metadata.py"
    metadata.parent.mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env={**os.environ, "SOURCE_REVISION": revision},
        check=True,
        timeout=10,
    )
    assert metadata.read_text() == f"__commit__: str | None = {revision or None!r}\n"


def test_docker_source_stamp_rejects_untrusted_non_sha_value(tmp_path: Path) -> None:
    line = next(
        line
        for line in (REPO_ROOT / "Dockerfile").read_text().splitlines()
        if line.startswith("RUN SOURCE_REVISION=")
    )
    argv = shlex.split(line)
    result = subprocess.run(
        [sys.executable, "-c", argv[argv.index("-c") + 1]],
        cwd=tmp_path,
        env={**os.environ, "SOURCE_REVISION": "not-a-commit"},
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert not (tmp_path / "src/mergecraft/_build_metadata.py").exists()
