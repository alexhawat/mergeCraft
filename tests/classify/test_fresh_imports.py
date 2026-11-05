"""Every entry module imports cleanly in a fresh interpreter (#1056 part 3).

``classify/blast_radius.py`` importing ``mergecraft.utils.path_globs`` ran
``utils/__init__`` → ``utils.github`` → ``config.settings`` →
``from mergecraft.classify import RuleSet`` while ``mergecraft.classify`` was
still initialising, so 39 modules failed when they were the first thing a
process imported. The suite never sees it: by the time a test runs, something
else has imported the cycle in a working order. Each import here runs in its
own isolated interpreter (``python -I -c``).

The sweep covers every module under ``mergecraft.classify``, ``mergecraft.config``
and ``mergecraft.utils`` (the packages the cycle runs through), eight
interpreters at a time. A sweep over all ~575 modules takes about two minutes
even with forked children, so it is not run here.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_DEADLINE_S = 120.0

ENTRY_MODULES = [
    "mergecraft.main",
    "mergecraft.config.settings",
    "mergecraft.classify.triage",
    "mergecraft.fast_path",
    "mergecraft.classify",
]


def _fresh_import(module: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=_DEADLINE_S,
        check=False,
    )


def _last_line(stderr: str) -> str:
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _missing_optional_dependency(stderr: str) -> bool:
    """A third-party extra that is not installed, not a broken mergecraft import."""
    last = _last_line(stderr)
    return last.startswith("ModuleNotFoundError: No module named ") and "mergecraft" not in last


@pytest.mark.parametrize("module", ENTRY_MODULES)
def test_an_entry_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    completed = _fresh_import(module)

    assert completed.returncode == 0, _last_line(completed.stderr)


def _modules_under(*packages: str) -> list[str]:
    names: list[str] = []
    for package in packages:
        root = _SRC / Path(*package.split("."))
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path.name == "__main__.py":
                continue
            dotted = ".".join(path.relative_to(_SRC).with_suffix("").parts)
            names.append(dotted.removesuffix(".__init__"))
    return names


def test_every_module_on_the_cycle_path_imports_first_in_a_fresh_interpreter() -> None:
    modules = _modules_under("mergecraft.classify", "mergecraft.config", "mergecraft.utils")
    assert "mergecraft.classify.blast_radius" in modules
    assert "mergecraft.utils.path_globs" in modules

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = dict(zip(modules, pool.map(_fresh_import, modules), strict=True))

    failures = {
        module: _last_line(completed.stderr)
        for module, completed in outcomes.items()
        if completed.returncode != 0 and not _missing_optional_dependency(completed.stderr)
    }
    assert failures == {}
