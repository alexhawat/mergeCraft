"""Batch GC — ``_blob_ref()`` resolution (#404).

Pins D8 order: ``MERGECRAFT_AGENT_PACKAGES_REF`` → ``action_pin_minimal()`` only
when ``git rev-parse --verify --quiet <pin>`` succeeds → else
``DEFAULT_BLOB_REF`` (``pre-0.0.1``). Never generate blob URLs at a missing tag.
Implementation lands in W6.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from mergecraft.pins import action_pin_minimal
from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_agent_packages.py"
_ENV_KEY = "MERGECRAFT_AGENT_PACKAGES_REF"
_EXPECTED_DEFAULT = "pre-0.0.1"


def _git_tag_exists(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{ref}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def test_default_blob_ref_constant_is_pre_0_0_1() -> None:
    """``DEFAULT_BLOB_REF`` must be ``pre-0.0.1`` on this branch (D8)."""
    module = load_script_module(GEN_SCRIPT)
    assert module.DEFAULT_BLOB_REF == _EXPECTED_DEFAULT


def test_blob_ref_uses_env_override(monkeypatch: MonkeyPatch) -> None:
    """``MERGECRAFT_AGENT_PACKAGES_REF`` wins over pin and default (D8 step 1)."""
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.setenv(_ENV_KEY, "feature/test-override")
    assert module._blob_ref() == "feature/test-override"


def test_blob_ref_returns_default_when_pin_tag_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """When ``v0.1.0a1`` is absent locally, return ``pre-0.0.1`` — not the pin (D8)."""
    pin = action_pin_minimal()
    assert pin == "v0.1.0a1", "fixture assumes action_pin_minimal is v0.1.0a1"
    assert not _git_tag_exists(pin), (
        f"test requires missing tag {pin!r} (G1 not cut); fetch a leaner checkout or skip"
    )
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
        if list(cmd)[:4] == ["git", "rev-parse", "--verify", "--quiet"] and pin in cmd:
            return subprocess.CompletedProcess(list(cmd), 0)
        return original_run(cmd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("subprocess.run", _fake_run)
    assert module._blob_ref() == pin
