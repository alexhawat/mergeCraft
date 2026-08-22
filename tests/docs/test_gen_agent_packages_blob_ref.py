"""Batch GC — ``_blob_ref()`` resolution (#404).

Pins D8 order: ``MERGECRAFT_AGENT_PACKAGES_REF`` → ``action_pin_minimal()`` only
when the pin resolves in git → else ``DEFAULT_BLOB_REF`` (``pre-0.0.1``). Never
generate blob URLs at a missing tag. Implementation lands in W6.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mergecraft.pins import action_pin_minimal
from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import git_ref_exists, load_script_module

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_agent_packages.py"
_ENV_KEY = "MERGECRAFT_AGENT_PACKAGES_REF"
_EXPECTED_DEFAULT = "pre-0.0.1"


def test_default_blob_ref_constant_is_pre_0_0_1() -> None:
    """``DEFAULT_BLOB_REF`` must be ``pre-0.0.1`` on this branch (D8)."""
    module = load_script_module(GEN_SCRIPT)
    assert module.DEFAULT_BLOB_REF == _EXPECTED_DEFAULT


def test_blob_ref_uses_env_override(monkeypatch: MonkeyPatch) -> None:
    """``MERGECRAFT_AGENT_PACKAGES_REF`` wins when the ref resolves (D8 step 1)."""
    module = load_script_module(GEN_SCRIPT)
    override = "feature/test-override"
    monkeypatch.setenv(_ENV_KEY, override)
    monkeypatch.setattr(
        module,
        "git_ref_exists",
        lambda ref, *, cwd=None: ref == override,
    )
    assert module._blob_ref() == override


def test_blob_ref_returns_default_when_pin_tag_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """When ``v0.1.0a1`` is absent locally, return ``pre-0.0.1`` — not the pin (D8)."""
    pin = action_pin_minimal()
    assert pin == "v0.1.0a1", "fixture assumes action_pin_minimal is v0.1.0a1"
    if git_ref_exists(pin):
        pytest.skip(f"G1: tag {pin!r} exists locally — skip missing-tag half of D8 test")
    monkeypatch.delenv(_ENV_KEY, raising=False)
    module = load_script_module(GEN_SCRIPT)
    ref = module._blob_ref()
    assert ref != pin, f"_blob_ref() must not return missing tag {pin!r} (D8)"
    assert ref == _EXPECTED_DEFAULT


def test_blob_ref_uses_action_pin_minimal_when_tag_exists(
    monkeypatch: MonkeyPatch,
) -> None:
    """When the pin tag resolves locally, ``_blob_ref()`` uses ``action_pin_minimal()``."""
    pin = action_pin_minimal()
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.delenv(_ENV_KEY, raising=False)

    original_run = subprocess.run

    def _fake_run(
        cmd: list[str] | tuple[str, ...],
        *args: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        cmd_list = list(cmd)
        if cmd_list[:3] == ["git", "rev-parse", "--verify"] and pin in cmd_list[3]:
            return subprocess.CompletedProcess(cmd_list, 0)
        return original_run(cmd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("mergecraft.utils.git_ref.subprocess.run", _fake_run)
    assert module._blob_ref() == pin
