"""#278 / D8 — live modules skip unless ``MERGECRAFT_LIVE=1``; CI stays fail-closed.

Unmarked ``pytest tests/integration/test_live_providers.py`` (and the GitHub
live module) must skip when the flag is unset, not ``pytest.fail`` on missing
creds. ``MERGECRAFT_LIVE=1`` with credentials stripped must still fail (D8 / D9).

These tests are **not** ``integration``/``live`` — they spawn a child pytest on
the live modules and must run under ``make test``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from mergecraft.integrations.live_providers import PROVIDER_SECRET_ENV
from tests.ci.workflow_support import REPO_ROOT

_LIVE_MODULES: Final[tuple[str, ...]] = (
    "tests/integration/test_live_providers.py",
    "tests/integration/test_github_integration.py",
)

_COUNT = re.compile(
    r"(?P<n>\d+) (?P<kind>failed|passed|skipped|xfailed|xpassed|error)s?",
)

_LIVE_FLAG = "MERGECRAFT_LIVE"
_EXTRA_LIVE_ENV: Final[tuple[str, ...]] = (
    "MERGECRAFT_LIVE_PROVIDER",
    "MERGECRAFT_LIVE_GITHUB_REPO",
    "MERGECRAFT_LIVE_GITHUB_SHA",
    "GITHUB_REPOSITORY",
    "GITHUB_SHA",
    "PYTEST_ADDOPTS",
)


def _child_env(*, live: str | None) -> dict[str, str]:
    """Copy the parent env with live credentials and the opt-in flag removed."""
    env = os.environ.copy()
    env.pop(_LIVE_FLAG, None)
    for name in PROVIDER_SECRET_ENV.values():
        env.pop(name, None)
    for name in _EXTRA_LIVE_ENV:
        env.pop(name, None)
    if live is not None:
        env[_LIVE_FLAG] = live
    env["PYTEST_ADDOPTS"] = ""
    return env


def _summary_counts(output: str) -> dict[str, int]:
    counts = {
        "failed": 0,
        "passed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "error": 0,
    }
    for match in _COUNT.finditer(output):
        kind = match.group("kind")
        if kind in counts:
            counts[kind] = int(match.group("n"))
    return counts


def _run_live_module_pytest(relpath: str, *, live: str | None, tmp_path: Path) -> tuple[int, str]:
    cache_dir = tmp_path / "pytest-cache"
    cache_dir.mkdir(exist_ok=True)
    target = REPO_ROOT / relpath
    assert target.is_file(), f"missing live module {relpath}"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-q",
            "--tb=no",
            "-p",
            "no:xdist",
            "-o",
            f"cache_dir={cache_dir}",
        ],
        cwd=REPO_ROOT,
        env=_child_env(live=live),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    return proc.returncode, output


@pytest.mark.parametrize("relpath", _LIVE_MODULES)
@pytest.mark.parametrize("live_value", [None, "", "0"])
def test_live_module_skips_when_mergecraft_live_unset(
    relpath: str,
    live_value: str | None,
    tmp_path: Path,
) -> None:
    """D8 — collected live tests skip unless ``MERGECRAFT_LIVE=1`` (not fail)."""
    code, output = _run_live_module_pytest(relpath, live=live_value, tmp_path=tmp_path)
    counts = _summary_counts(output)
    # Exit code 5 means "no tests collected" — emitted by pytest.skip(allow_module_level=True);
    # exit code 0 means tests ran and were individually skipped. Both are "did not fail".
    assert code in (0, 5), (
        f"{relpath} with MERGECRAFT_LIVE={live_value!r} must skip, not fail "
        f"(exit {code}):\n{output}"
    )
    assert counts["failed"] == 0, (
        f"{relpath} must not fail when MERGECRAFT_LIVE is not '1'; got {counts}:\n{output}"
    )
    assert counts["error"] == 0, f"{relpath} collection/errors: {counts}:\n{output}"
    assert counts["skipped"] > 0, (
        f"{relpath} must skip when MERGECRAFT_LIVE is not '1'; got {counts}:\n{output}"
    )
    assert counts["passed"] == 0, (
        f"{relpath} must not pass live bodies when MERGECRAFT_LIVE is not '1'; "
        f"got {counts}:\n{output}"
    )


@pytest.mark.parametrize("relpath", _LIVE_MODULES)
def test_live_module_fails_when_flag_set_without_credentials(
    relpath: str,
    tmp_path: Path,
) -> None:
    """D8 — ``MERGECRAFT_LIVE=1`` keeps D9 fail-closed when secrets are absent."""
    code, output = _run_live_module_pytest(relpath, live="1", tmp_path=tmp_path)
    counts = _summary_counts(output)
    assert code != 0, (
        f"{relpath} with MERGECRAFT_LIVE=1 and no creds must fail, not skip "
        f"(exit {code}):\n{output}"
    )
    assert counts["failed"] > 0, (
        f"{relpath} must pytest.fail on missing creds when the live flag is set; "
        f"got {counts}:\n{output}"
    )
