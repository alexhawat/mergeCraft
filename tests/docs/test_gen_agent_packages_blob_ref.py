"""Batch GC — ``_blob_ref()`` resolution (#404).

Pins D8 order: ``MERGECRAFT_AGENT_PACKAGES_REF`` → ``action_pin_minimal()`` only
when the pin resolves in git → else ``DEFAULT_BLOB_REF`` (``pre-0.0.1``). Never
generate blob URLs at a missing tag. Implementation lands in W6.
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


def test_blob_ref_uses_the_pin_even_when_the_tag_is_absent_locally(
    monkeypatch: MonkeyPatch,
) -> None:
    """The pin is used regardless of local git state.

    Replaces the old D8 assertion that a locally-missing tag falls back to
    ``DEFAULT_BLOB_REF``. That behaviour made the generated packages depend on
    whether the checkout happened to have fetched tags: a tag build emitted the
    pin, a `fetch-depth: 1` branch build emitted the default, and whichever the
    committed files matched, the other failed `agent-packages-check`. The refs
    are github.com blob URLs, so the tag resolving locally is irrelevant.
    """
    pin = action_pin_minimal()
    assert pin == "v0.1.0a1", "fixture assumes action_pin_minimal is v0.1.0a1"
    monkeypatch.delenv(_ENV_KEY, raising=False)
    module = load_script_module(GEN_SCRIPT)
    # Simulate a shallow checkout with no tags: every ref lookup fails.
    monkeypatch.setattr(module, "git_ref_exists", lambda ref, *, cwd=None: False)
    assert module._blob_ref() == pin


def test_generated_packages_are_identical_without_local_tags(
    monkeypatch: MonkeyPatch,
) -> None:
    """Rendered output must not change with local git state (the drift bug)."""
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.delenv(_ENV_KEY, raising=False)
    with_tags = module.render_all()
    monkeypatch.setattr(module, "git_ref_exists", lambda ref, *, cwd=None: False)
    without_tags = module.render_all()
    assert with_tags == without_tags


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
