"""W12.7 — network-namespace probe + ``unshare --net`` argv shaping (``#35``)."""

from __future__ import annotations

import pytest

from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.shell import _unshare_argv, network_namespace_available


@pytest.fixture(autouse=True)
def _reset_netns_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_mod, "_detected_netns", None)


def test_network_namespace_available_false_outside_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — non-CI hosts skip the probe and treat netns as unavailable."""
    monkeypatch.delenv("CI", raising=False)
    assert network_namespace_available() is False


def test_network_namespace_available_true_when_unshare_net_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — CI probe caches success when ``unshare --net true`` returns 0."""
    monkeypatch.setenv("CI", "true")

    class _Result:
        returncode = 0

    monkeypatch.setattr(shell_mod.subprocess, "run", lambda *a, **k: _Result())
    assert network_namespace_available() is True
    # Cached — second call must not re-probe.
    monkeypatch.setattr(
        shell_mod.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-probed")),
    )
    assert network_namespace_available() is True


def test_network_namespace_available_false_when_unshare_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — ``OSError`` from missing ``unshare`` caches unavailable."""
    monkeypatch.setenv("CI", "true")

    def _boom(*_a: object, **_k: object) -> object:
        raise OSError("unshare not found")

    monkeypatch.setattr(shell_mod.subprocess, "run", _boom)
    assert network_namespace_available() is False


def test_unshare_argv_omits_net_when_isolation_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — trusted / non-isolate path never appends ``--net``."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    argv = _unshare_argv(isolate_network=False)
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    assert "--net" not in argv


def test_unshare_argv_adds_net_when_available_and_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — untrusted shell adds ``--net`` only when the probe says ok."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: True)
    assert "--net" in _unshare_argv(isolate_network=True)


def test_unshare_argv_skips_net_when_probe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W12.7 — without netns, argv stays PID-only (credential isolation fallback)."""
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)
    assert "--net" not in _unshare_argv(isolate_network=True)
