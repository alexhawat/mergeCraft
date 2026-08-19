"""Plan W6.4 — one pytest version across unit CI and the adversarial image (``#271``).

``docker/e2e/run_in_image_adversarial.sh`` installs its own test runner into
the baked image venv (product code stays the ``/opt/mergecraft`` install, which
is the containment boundary). That ``uv pip install`` line carries its own
pins, so it silently drifts from ``pyproject.toml``'s ``dev`` extra: the
adversarial suite then runs on a different pytest than the one every unit job
uses, and a collection/behaviour difference shows up only in the image job.

Both pins are parsed out of their files rather than hardcoded, so this guard
keeps working after the next dependency bump instead of becoming the thing
that has to be edited.
"""

from __future__ import annotations

import re
import tomllib
from typing import Final

import pytest

from tests.ci.workflow_support import REPO_ROOT

_PYPROJECT: Final = REPO_ROOT / "pyproject.toml"
_SCRIPT_RELATIVE: Final = "docker/e2e/run_in_image_adversarial.sh"
_SCRIPT: Final = REPO_ROOT / _SCRIPT_RELATIVE

# `"pkg==1.2.3"` as written on the script's `uv pip install` line.
_QUOTED_PIN = re.compile(r'"([A-Za-z0-9._-]+)==([^"]+)"')


def _pyproject_pins() -> dict[str, str]:
    """Exact ``==`` pins declared anywhere in ``pyproject.toml``'s extras."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    extras = data.get("project", {}).get("optional-dependencies", {})
    pins: dict[str, str] = {}
    for requirements in extras.values():
        for requirement in requirements:
            name, sep, version = str(requirement).partition("==")
            if sep and "[" not in name:
                pins[name.strip()] = version.strip()
    return pins


def _script_pins() -> dict[str, str]:
    """Exact ``==`` pins the adversarial runner installs into the image venv."""
    text = _SCRIPT.read_text(encoding="utf-8")
    return {match.group(1): match.group(2) for match in _QUOTED_PIN.finditer(text)}


class TestPinSourcesAreParseable:
    """The guard is only meaningful if both anchors are still where we think."""

    def test_pyproject_declares_a_pytest_pin(self) -> None:
        assert "pytest" in _pyproject_pins(), (
            "pyproject.toml no longer declares an exact `pytest==` pin — re-anchor #271"
        )

    def test_script_installs_a_pytest_pin(self) -> None:
        assert "pytest" in _script_pins(), (
            f"{_SCRIPT_RELATIVE} no longer pins pytest on its uv pip install line"
        )

    def test_script_pins_are_exact(self) -> None:
        """No ``>=``/``~=`` smuggled into the image install."""
        text = _SCRIPT.read_text(encoding="utf-8")
        loose = [tok for tok in (">=", "~=", "<=") if f'"pytest{tok}' in text]
        assert not loose, f"{_SCRIPT_RELATIVE} uses a loose pytest specifier: {loose}"


class TestPinsAgree:
    """Every runner package the script installs must match ``pyproject.toml``."""

    def test_pytest_pin_matches_pyproject(self) -> None:
        assert _script_pins()["pytest"] == _pyproject_pins()["pytest"], (
            f"{_SCRIPT_RELATIVE} installs pytest=={_script_pins()['pytest']} but "
            f"pyproject.toml pins pytest=={_pyproject_pins()['pytest']}"
        )

    def test_pytest_asyncio_pin_matches_pyproject(self) -> None:
        """Already in sync today — W9 must keep it that way."""
        assert _script_pins()["pytest-asyncio"] == _pyproject_pins()["pytest-asyncio"], (
            f"{_SCRIPT_RELATIVE} installs "
            f"pytest-asyncio=={_script_pins()['pytest-asyncio']} but pyproject.toml "
            f"pins pytest-asyncio=={_pyproject_pins()['pytest-asyncio']}"
        )

    @pytest.mark.parametrize("package", ["pytest", "pytest-asyncio"])
    def test_no_runner_package_drifts(self, package: str) -> None:
        """Table form so a newly-added runner pin is covered without editing logic."""
        script = _script_pins()
        pyproject = _pyproject_pins()
        if package not in script:
            pytest.skip(f"{package} not installed by {_SCRIPT_RELATIVE}")
        assert package in pyproject, f"{package} pinned in the script but not in pyproject.toml"
        assert script[package] == pyproject[package], (
            f"{package}: script {script[package]} != pyproject {pyproject[package]}"
        )

    def test_every_script_pin_is_declared_in_pyproject(self) -> None:
        """The image must not install a package that unit CI has never resolved."""
        pyproject = _pyproject_pins()
        undeclared = [name for name in _script_pins() if name not in pyproject]
        assert not undeclared, (
            f"{_SCRIPT_RELATIVE} installs package(s) absent from pyproject.toml: {undeclared}"
        )


__all__ = [
    "TestPinSourcesAreParseable",
    "TestPinsAgree",
]
