"""F3 (#760) — the ambient GitHub event must not leak into tests.

``tests/conftest.py`` carries no ``GITHUB_EVENT_*`` guard today, so every test
that reaches ``derive_trust_tier`` inherits whatever event the runner exported:
a shape that passes on every ``pull_request`` run and fails on the first
``push`` to ``main``. The guard's contract is proven twice — directly, and in a
child process with the variables deliberately exported so the proof does not
depend on the ambient environment of whoever runs the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers.trust import derive_trust_tier

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROBE = _REPO_ROOT / "tests" / "probe" / "test_ambient_event_probe.py"
_SAME_REPO_EVENT = {"pull_request": {"head": {"repo": {"fork": False}}}}


def test_autouse_guard_clears_ambient_github_event_in_a_child_process(tmp_path: Path) -> None:
    """Both variables exported to the child must be cleared by the guard."""
    event_path = tmp_path / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    env = {
        **os.environ,
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_EVENT_PATH": str(event_path),
    }

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(_PROBE), "-q", "-p", "no:cacheprovider"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, (
        "the child inherited the exported GITHUB_EVENT_* values — tests/conftest.py has no "
        f"autouse guard\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "3 passed" in proc.stdout, f"probe did not run as expected:\n{proc.stdout}"


def test_ambient_event_variables_are_cleared_in_this_process() -> None:
    """The guard runs autouse, so a test body starts with neither variable set."""
    assert os.environ.get("GITHUB_EVENT_NAME") is None, (
        "GITHUB_EVENT_NAME leaked from the runner into the test process"
    )
    assert os.environ.get("GITHUB_EVENT_PATH") is None, (
        "GITHUB_EVENT_PATH leaked from the runner into the test process"
    )


def test_cleared_default_derives_fail_closed_untrusted() -> None:
    """With no ambient event, the same-repo PR shape must not read as trusted."""
    assert derive_trust_tier(event=_SAME_REPO_EVENT, shell="restricted") == "untrusted"


def test_explicit_event_opt_in_overrides_the_cleared_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``monkeypatch.setenv`` after the guard must still drive the tier."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert derive_trust_tier(event=_SAME_REPO_EVENT, shell="restricted") == "trusted"
