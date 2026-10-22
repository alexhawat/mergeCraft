"""``tests/mcp/test_rpc.py`` leaves no ``package_version`` cache behind (#1006).

The module's autouse fixture used to clear the cache in setup only. One of its
tests caches a fake ``9.9.9+wheel``; when random ordering ran that test last, the
fake survived into every later test that resolved the installed version. The
later test looked broken while the leaking one was green, and the failure only
reproduced under the full suite with the deterministic default seed.

The reproduction is run in a child pytest so the poisoned order is exact: the
leaking test first, a probe that reads the cached version second, ordering plugins
off.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_LEAKING_TEST = "tests/mcp/test_rpc.py::test_package_version_prefers_installed_distribution"
_PROBE = """
from mergecraft.utils.version import package_version


def test_probe_sees_the_real_version() -> None:
    assert package_version() != "9.9.9+wheel"
"""


def test_a_version_reading_test_after_the_leaking_test_sees_the_real_version(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "test_probe_version.py"
    probe.write_text(_PROBE, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-n",
            "0",
            "--rootdir",
            str(REPO_ROOT),
            "-c",
            str(REPO_ROOT / "pyproject.toml"),
            _LEAKING_TEST,
            str(probe),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "2 passed" in completed.stdout, completed.stdout
