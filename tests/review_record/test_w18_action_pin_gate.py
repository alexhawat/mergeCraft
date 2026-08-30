"""W1.8 — action pin gate wired into ci-static (#532, implementation W8)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.pins.test_action_pin_freshness import _load, _workflow_text

_SHA_A = "0592d72828797005fdc5af1da9e413b0a98bd8a0"
_SHA_B = "cfa36704cf6c58a6abe895e539a377c4599fa4bd"
_WORKFLOW = ".github/workflows/mergecraft.yml"


def _makefile_text() -> str:
    return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def test_make_ci_static_invokes_action_pin_check() -> None:
    makefile = _makefile_text()
    ci_static_line = next(line for line in makefile.splitlines() if line.startswith("ci-static:"))
    assert "action-pin-check" in ci_static_line
    ci_steps = next(line for line in makefile.splitlines() if line.startswith("CI_STEPS :="))
    assert "action-pin-check" in ci_steps


def test_ci_yml_fails_on_stale_pin_instead_of_warning_only() -> None:
    ci_yml = read_text(".github/workflows/ci.yml")
    assert 'echo "::warning title=mergecraft action pin drift::' not in ci_yml
    assert "make action-pin-check" in ci_yml
    assert "exit 1" in ci_yml or "exit $?" in ci_yml


def test_mergecraft_workflow_three_rungs_share_one_pin_value() -> None:
    text = read_text(_WORKFLOW)
    pins = re.findall(r"uses:\s+alexhawat/mergeCraft@([0-9a-f]{40})", text)
    assert len(pins) >= 3
    assert len(set(pins)) == 1


def test_partial_pin_bump_fails_action_pin_check(tmp_path: Path) -> None:
    module = _load()
    drifted = tmp_path / "mergecraft.yml"
    drifted.write_text(_workflow_text(_SHA_A, _SHA_B), encoding="utf-8")
    pins = module._pins_in(drifted.read_text(encoding="utf-8"))
    failures = module._check_self_consistency(_WORKFLOW, pins)
    assert failures
    assert "different Action pins" in failures[0]
