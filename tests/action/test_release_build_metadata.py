"""Image build source stamping must not invent its future digest or manifest SHA."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.ci.workflow_support import REPO_ROOT


def _stamp_source() -> str:
    text = (REPO_ROOT / "Dockerfile").read_text()
    return text.split("python - <<'PYTHON'\n", 1)[1].split("\nPYTHON", 1)[0]


@pytest.mark.parametrize("revision", ["a" * 40, ""])
@pytest.mark.parametrize("optimized", [False, True])
def test_docker_source_stamp_records_only_valid_source(
    tmp_path: Path, revision: str, optimized: bool
) -> None:
    metadata = tmp_path / "src/mergecraft/_build_metadata.py"
    metadata.parent.mkdir(parents=True)
    subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", _stamp_source()],
        cwd=tmp_path,
        env={**os.environ, "SOURCE_REVISION": revision},
        check=True,
        timeout=10,
    )
    assert metadata.read_text() == f"__commit__: str | None = {revision or None!r}\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_docker_source_stamp_rejects_untrusted_non_sha_value(
    tmp_path: Path, optimized: bool
) -> None:
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", _stamp_source()],
        cwd=tmp_path,
        env={**os.environ, "SOURCE_REVISION": "not-a-commit", "PYTHONOPTIMIZE": "1"},
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert b"invalid source revision" in result.stderr
    assert not (tmp_path / "src/mergecraft/_build_metadata.py").exists()
