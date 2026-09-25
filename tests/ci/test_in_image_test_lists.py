"""Privileged tests must run in the lane built for them, not skip in every lane.

Three tests are gated by root, a direct ``unshare`` capability, or a live
flag, and no lane satisfies those gates. The in-image privilege script also
pins a different ``pytest-asyncio`` than the project it tests. This module
pins the end state: the chown test joins the in-image root pass, both in-image
scripts pin the project's test runner, the disposable host lane runs the
sandbox test with the privileged-lane flag set, and both guarded tests consult
that flag and fail rather than skip.
"""

from __future__ import annotations

import re
import tomllib
from typing import Final

import pytest

from tests.ci.workflow_support import (
    REPO_ROOT,
    load_workflow,
    makefile_target_body,
    read_text,
)

_PYPROJECT: Final = REPO_ROOT / "pyproject.toml"
_PRIVILEGE_SCRIPT: Final = "docker/e2e/run_in_image_privilege.sh"
_ADVERSARIAL_SCRIPT: Final = "docker/e2e/run_in_image_adversarial.sh"
_PINNED_QUOTED: Final = re.compile(r'"([A-Za-z0-9._-]+)==([^"]+)"')
_LANE_ENV: Final = "MERGECRAFT_PRIVILEGED_LANE"
_LANE_SET: Final = re.compile(rf"{_LANE_ENV}\s*[:=]\s*['\"]?1\b")
_GUARDED_TESTS: Final = (
    "tests/analyzers/test_sandbox_execution.py",
    "tests/utils/test_privilege_chown.py",
)


def _dev_pins() -> dict[str, str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    dev = data["project"]["optional-dependencies"]["dev"]
    pins: dict[str, str] = {}
    for requirement in dev:
        name, separator, version = str(requirement).partition("==")
        if separator and "[" not in name:
            pins[name.strip()] = version.strip()
    return pins


def _script_pins(relative: str) -> dict[str, str]:
    text = read_text(relative)
    return {match.group(1): match.group(2) for match in _PINNED_QUOTED.finditer(text)}


def test_privilege_script_runs_the_chown_test_in_the_privileged_lane() -> None:
    text = read_text(_PRIVILEGE_SCRIPT)
    assert "tests/utils/test_privilege_chown.py" in text, (
        "the in-image root pass must list the chown test; it is the only root lane it has"
    )
    assert _LANE_SET.search(text), (
        f"the root pass must set {_LANE_ENV}=1 so the guarded tests fail rather than skip"
    )


@pytest.mark.parametrize("relative", [_PRIVILEGE_SCRIPT, _ADVERSARIAL_SCRIPT])
def test_in_image_scripts_pin_the_project_test_runner(relative: str) -> None:
    project = _dev_pins()
    script = _script_pins(relative)
    for package in ("pytest", "pytest-asyncio"):
        assert package in script, f"{relative} must install {package} into the image venv"
        assert package in project, f"pyproject.toml no longer pins {package}"
        assert script[package] == project[package], (
            f"{relative} installs {package}=={script[package]} but the project pins "
            f"{package}=={project[package]}"
        )


def _privileged_lane_texts() -> list[str]:
    """Every workflow step, plus any Make target its ``run:`` calls."""
    doc = load_workflow("integration.yml")
    makefile = read_text("Makefile")
    texts: list[str] = []
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            text = str(step)
            for target in re.findall(r"make\s+([a-z0-9-]+)", text):
                try:
                    text += "\n" + makefile_target_body(target, makefile)
                except AssertionError:
                    continue
            texts.append(text)
    return texts


def test_disposable_host_lane_runs_the_sandbox_test_in_the_privileged_lane() -> None:
    hits = [
        text
        for text in _privileged_lane_texts()
        if "tests/analyzers/test_sandbox_execution.py" in text and _LANE_SET.search(text)
    ]
    assert hits, (
        "no integration.yml step (or Make target it calls) runs "
        f"tests/analyzers/test_sandbox_execution.py with {_LANE_ENV}=1"
    )


@pytest.mark.parametrize("relative", _GUARDED_TESTS)
def test_every_guarded_test_consults_the_privileged_lane(relative: str) -> None:
    text = read_text(relative)
    assert _LANE_ENV in text, (
        f"{relative} must check {_LANE_ENV} to fail instead of skip inside its lane"
    )
    assert "pytest.fail" in text, (
        f"{relative} must call pytest.fail when its privileged lane cannot satisfy the gate"
    )
