"""Batch GA — checkout vs packaged ``defaults.yaml`` sync (#402, #414).

Pins byte identity between ``scripts/example_workflows/defaults.yaml`` (source
of truth) and ``src/mergecraft/data/example_workflows/defaults.yaml``, plus
``make pins-check`` membership in ``CI_STEPS`` and ``ci-static``. Implementation
lands in W2 (D7).
"""

from __future__ import annotations

import re

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text

_CHECKOUT_DEFAULTS = REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"
_PACKAGED_DEFAULTS = (
    REPO_ROOT / "src" / "mergecraft" / "data" / "example_workflows" / "defaults.yaml"
)
_PINS_CHECK_TARGET = "pins-check"


def _makefile_prerequisite_tokens(makefile: str, target: str) -> set[str]:
    match = re.search(rf"^{re.escape(target)}:(.*)$", makefile, re.MULTILINE)
    assert match, f"Makefile missing {target}: recipe"
    return set(match.group(1).split())


def _ci_steps(makefile: str) -> list[str]:
    match = re.search(r"^CI_STEPS\s*:?=\s*(.+)$", makefile, re.MULTILINE)
    assert match, "Makefile missing CI_STEPS"
    return match.group(1).split()


@pytest.mark.xfail(reason="green after W2: sync packaged defaults.yaml copy (#402)", strict=False)
def test_checkout_and_packaged_defaults_yaml_are_byte_identical() -> None:
    """D7: checkout YAML is source of truth; packaged copy must match byte-for-byte."""
    assert _CHECKOUT_DEFAULTS.is_file(), (
        f"missing checkout defaults: {_CHECKOUT_DEFAULTS.relative_to(REPO_ROOT)}"
    )
    assert _PACKAGED_DEFAULTS.is_file(), (
        f"missing packaged defaults: {_PACKAGED_DEFAULTS.relative_to(REPO_ROOT)}"
    )
    checkout_bytes = _CHECKOUT_DEFAULTS.read_bytes()
    packaged_bytes = _PACKAGED_DEFAULTS.read_bytes()
    assert checkout_bytes == packaged_bytes, (
        "scripts/example_workflows/defaults.yaml and "
        "src/mergecraft/data/example_workflows/defaults.yaml must be byte-identical "
        "(edit checkout copy, sync packaged copy, then run make pins-check)"
    )


@pytest.mark.xfail(reason="green after W2: add pins-check Makefile target (#414)", strict=False)
def test_make_pins_check_target_exists() -> None:
    makefile = read_text("Makefile")
    assert re.search(
        rf"^{re.escape(_PINS_CHECK_TARGET)}:",
        makefile,
        re.MULTILINE,
    ), f"Makefile must define {_PINS_CHECK_TARGET}:"


@pytest.mark.xfail(reason="green after W2: wire pins-check into CI_STEPS (#414)", strict=False)
def test_make_pins_check_in_ci_steps() -> None:
    makefile = read_text("Makefile")
    steps = _ci_steps(makefile)
    assert _PINS_CHECK_TARGET in steps, (
        f"Makefile CI_STEPS must include {_PINS_CHECK_TARGET} (#414 drift gate)"
    )


@pytest.mark.xfail(reason="green after W2: wire pins-check into ci-static (#414)", strict=False)
def test_make_pins_check_in_ci_static() -> None:
    makefile = read_text("Makefile")
    ci_static = _makefile_prerequisite_tokens(makefile, "ci-static")
    assert _PINS_CHECK_TARGET in ci_static, (
        f"Makefile ci-static must include {_PINS_CHECK_TARGET} (#414 drift gate)"
    )
