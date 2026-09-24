"""Batch GA — checkout vs packaged ``defaults.yaml`` sync (#402, #414).

Pins byte identity between ``scripts/example_workflows/defaults.yaml`` (source
of truth) and ``src/mergecraft/data/example_workflows/defaults.yaml``, plus
``make pins-check`` membership in ``CI_STEPS`` and ``ci-static``. Implementation
lands in W2 (D7).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import ci_steps, makefile_prerequisite_tokens

_CHECKOUT_DEFAULTS = REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"
_PACKAGED_DEFAULTS = (
    REPO_ROOT / "src" / "mergecraft" / "data" / "example_workflows" / "defaults.yaml"
)
_PINS_CHECK_TARGET = "pins-check"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_LOCKED_CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
_LOCKED_ACTION_SHA = "521c0aedbf525a80a5bf6eddf0119ada85a8d381"


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


@pytest.mark.xfail(reason="green after SW3.1: shared SHA keys land in defaults", strict=False)
@pytest.mark.parametrize(
    "path",
    [_CHECKOUT_DEFAULTS, _PACKAGED_DEFAULTS],
    ids=["checkout", "packaged"],
)
def test_defaults_carry_the_shared_action_and_checkout_shas(path: Path) -> None:
    """One immutable commit each for the Action ref and every checkout."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw.get("action_sha_minimal") == _LOCKED_ACTION_SHA
    assert raw.get("checkout_sha") == _LOCKED_CHECKOUT_SHA
    assert _SHA.fullmatch(str(raw.get("action_sha_minimal")))
    assert _SHA.fullmatch(str(raw.get("checkout_sha")))
