"""Batch GA — checkout vs packaged ``defaults.yaml`` sync (#402, #414).

Pins byte identity between ``scripts/example_workflows/defaults.yaml`` (source
of truth) and ``src/mergecraft/data/example_workflows/defaults.yaml``, plus
``make pins-check`` membership in ``CI_STEPS`` and ``ci-static``. Implementation
lands in W2 (D7).
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import ci_steps, makefile_prerequisite_tokens

_CHECKOUT_DEFAULTS = REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"
_PACKAGED_DEFAULTS = (
    REPO_ROOT / "src" / "mergecraft" / "data" / "example_workflows" / "defaults.yaml"
)
_PINS_CHECK_TARGET = "pins-check"


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


def test_make_pins_check_target_exists() -> None:
    makefile = read_text("Makefile")
    assert re.search(
        rf"^{re.escape(_PINS_CHECK_TARGET)}:",
        makefile,
        re.MULTILINE,
    ), f"Makefile must define {_PINS_CHECK_TARGET}:"


def test_make_pins_check_in_ci_steps() -> None:
    assert _PINS_CHECK_TARGET in ci_steps(), (
        f"Makefile CI_STEPS must include {_PINS_CHECK_TARGET} (#414 drift gate)"
    )


def test_make_pins_check_in_ci_static() -> None:
    makefile = read_text("Makefile")
    ci_static = makefile_prerequisite_tokens(makefile, "ci-static")
    assert _PINS_CHECK_TARGET in ci_static, (
        f"Makefile ci-static must include {_PINS_CHECK_TARGET} (#414 drift gate)"
    )
