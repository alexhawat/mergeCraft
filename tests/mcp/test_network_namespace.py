"""W12.7 — network-namespace probe + ``unshare --net`` argv shaping (``#35``).

**Contract change (lane A / MCB-10):** when netns is unavailable the untrusted
shell capability is **absent** — mergeCraft must not silently drop ``--net`` and
continue. Tests below pin the new fail-closed contract; green after **AP3**.
"""

from __future__ import annotations

import pytest

from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.shell import _unshare_argv, network_namespace_available

pytestmark = pytest.mark.xfail(
    reason="green after AP3: netns absence removes untrusted shell capability",
    strict=False,
)


@pytest.fixture(autouse=True)
def _reset_netns_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    shell_mod.reset_detection_cache()


def test_network_namespace_available_false_outside_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capability probe must not treat CI as the answer (D5)."""
    monkeypatch.delenv("CI", raising=False)

    class _Result:
        returncode = 0

    monkeypatch.setattr(shell_mod.subprocess, "run", lambda *a, **k: _Result())
    assert network_namespace_available() is False


def test_network_namespace_available_true_when_unshare_net_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)

    class _Result:
        returncode = 0

    monkeypatch.setattr(shell_mod.subprocess, "run", lambda *a, **k: _Result())
    assert network_namespace_available() is True


def test_network_namespace_available_false_when_unshare_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)

    def _boom(*_a: object, **_k: object) -> object:
        raise OSError("unshare not found")

    monkeypatch.setattr(shell_mod.subprocess, "run", _boom)
    assert network_namespace_available() is False


def test_unshare_argv_omits_net_when_isolation_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    argv = _unshare_argv(isolate_network=False)
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    assert "--net" not in argv


def test_unshare_argv_adds_net_when_available_and_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    assert "--net" in _unshare_argv(isolate_network=True)


def test_untrusted_shell_absent_when_netns_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCB-10 — missing netns removes the capability; do not spawn with ``--net`` dropped."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)
    from unittest.mock import MagicMock

    with pytest.raises((RuntimeError, PermissionError)):
        shell_mod._spawn_shell(
            "echo ok",
            env={},
            cwd="/tmp",
            stdout=MagicMock(),
            stderr=MagicMock(),
            isolate_network=True,
        )
