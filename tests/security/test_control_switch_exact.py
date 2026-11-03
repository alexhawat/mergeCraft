"""Control-weakening switches are enabled only by exactly ``"1"``.

Three switches weaken a control: the unsandboxed-shell override, the root
override, and the opt-in to a kernel egress sandbox. Each is read today by
comparing the raw value to the exact string ``"1"``; Pydantic's ``bool`` would
also accept ``true``, ``yes``, ``on``, ``t`` and ``y``, which would widen a
control an operator never asked to widen. The value therefore stays a raw
string and the comparison stays verbatim.

The reader table below is frozen from the pre-migration functions and covers
the spellings whose meaning does not move: ``"1"`` enables, and the ordinary
boolean spellings do not. The whitespace variants (``" 1"``, ``"1 "``) are
owned by the model's exact-``"1"`` contract and are pinned in
``tests/config/test_env_reads_inventory.py``; the readers are pinned here on the
unambiguous spellings so the table states today's behaviour honestly.

The switches also must not become a documented knob: ``ControlSwitches`` is a
hidden model, is not a field of ``RepoSettings``, and the removed
security-instructions switch must keep no reader at all. No ``xfail`` marker is
used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_UNSANDBOXED = "MERGECRAFT_ALLOW_UNSANDBOXED_SHELL"
_ALLOW_ROOT = "MERGECRAFT_ALLOW_ROOT"
_FILTERED_EGRESS = "MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME"
_REMOVED = "MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS"

_SWITCHES = (_UNSANDBOXED, _ALLOW_ROOT, _FILTERED_EGRESS)

#: Frozen reader table: raw value -> whether the switch is enabled.
#:
#: ``"1"`` is the only enabling spelling. ``"true"`` / ``"yes"`` / ``"on"`` /
#: ``"t"`` are the spellings Pydantic's ``bool`` would add; ``"01"`` proves the
#: comparison is not numeric; ``""`` and an absent variable are "off".
_FROZEN: list[tuple[str | None, bool]] = [
    ("1", True),
    ("true", False),
    ("TRUE", False),
    ("yes", False),
    ("on", False),
    ("t", False),
    ("01", False),
    ("", False),
    (None, False),
]


def _set(monkeypatch: MonkeyPatch, name: str, raw: str | None) -> None:
    for switch in _SWITCHES:
        monkeypatch.delenv(switch, raising=False)
    if raw is not None:
        monkeypatch.setenv(name, raw)


def _unsandboxed_shell_enabled(monkeypatch: MonkeyPatch, raw: str | None) -> bool:
    from mergecraft.mcp.shell import _allow_unsandboxed_shell

    _set(monkeypatch, _UNSANDBOXED, raw)
    return _allow_unsandboxed_shell()


def _allow_root_enabled(monkeypatch: MonkeyPatch, raw: str | None) -> bool:
    from mergecraft.utils.privilege import _allow_root_override

    _set(monkeypatch, _ALLOW_ROOT, raw)
    return _allow_root_override()


def _kernel_egress_attempted(monkeypatch: MonkeyPatch, raw: str | None) -> bool:
    """Whether the opt-in let the kernel egress probe run."""
    from mergecraft.analyzers import egress, egress_userspace

    _set(monkeypatch, _FILTERED_EGRESS, raw)
    attempted: list[bool] = []

    def _unshare() -> bool:
        attempted.append(True)
        return False

    unavailable = egress.FilteredEgressProbe(
        network_namespace=False,
        veth=False,
        ip_netns=False,
        iptables=False,
        available=False,
        reason="test double",
    )
    monkeypatch.setattr(egress_userspace, "probe_userspace_egress", lambda: unavailable)
    monkeypatch.setattr(egress, "_can_unshare_net", _unshare)
    egress.reset_filtered_egress_cache()
    try:
        egress.probe_filtered_egress()
    finally:
        egress.reset_filtered_egress_cache()
    return bool(attempted)


_READERS = [
    pytest.param(_unsandboxed_shell_enabled, id="unsandboxed-shell"),
    pytest.param(_allow_root_enabled, id="allow-root"),
    pytest.param(_kernel_egress_attempted, id="filtered-egress-opt-in"),
]


@pytest.mark.parametrize(("raw", "expected"), _FROZEN, ids=[repr(raw) for raw, _ in _FROZEN])
@pytest.mark.parametrize("reader", _READERS)
def test_control_switch_is_enabled_only_by_exactly_one(
    reader,
    raw: str | None,
    expected: bool,
    monkeypatch: MonkeyPatch,
) -> None:
    """Only the literal ``"1"`` enables a control-weakening switch."""
    assert reader(monkeypatch, raw) is expected


@pytest.mark.parametrize("switch_name", _SWITCHES)
def test_no_switch_is_a_repo_setting(switch_name: str) -> None:
    """A switch can never be rendered by ``config show``, which prints repo settings."""
    from mergecraft.config.settings import RepoSettings, default_settings

    declared = set(RepoSettings.model_fields)
    for field in RepoSettings.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, str):
            declared.add(alias)
    assert switch_name not in declared
    assert switch_name not in default_settings().model_dump_json()


def test_the_removed_security_instructions_switch_has_no_reader() -> None:
    """The deleted ``MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS`` must not come back."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "mergecraft"
    readers = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if _REMOVED in path.read_text(encoding="utf-8")
    ]
    assert not readers, f"{_REMOVED} must have no reader, found in {readers}"
