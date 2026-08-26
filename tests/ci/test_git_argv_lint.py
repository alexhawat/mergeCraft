"""Lane A AP1.1 — ``check_git_argv`` lint gate (D2)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(
    reason="green after AP2: scripts/check_git_argv.py wired into make lint",
    strict=False,
)

_REPO = Path(__file__).resolve().parents[2]
_CHECKER = _REPO / "scripts" / "check_git_argv.py"


def test_bare_git_list_literal_fails_the_checker(tmp_path: Path) -> None:
    assert _CHECKER.is_file(), "scripts/check_git_argv.py must exist"
    probe = tmp_path / "probe.py"
    probe.write_text(
        'evil = ["git", "status"]\n',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(_CHECKER), str(probe)],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0, "bare ['git', …] literal must fail the checker"
