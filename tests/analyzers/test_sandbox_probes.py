"""Lane A AP1.2 — sandbox capability probes (MCB-07/09/10/35)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.mcp import shell as shell_mod


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    shell_mod.reset_detection_cache()
    if hasattr(sandbox_mod, "reset_detection_cache"):
        sandbox_mod.reset_detection_cache()
    if hasattr(sandbox_mod.probe_capabilities, "cache_clear"):
        sandbox_mod.probe_capabilities.cache_clear()


def test_probe_does_not_consult_ci_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(list(cmd))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(sandbox_mod.subprocess, "run", _fake_run)
    caps = sandbox_mod.probe_capabilities()
    assert any("unshare" in " ".join(c) or "mount" in " ".join(c) for c in calls), (
        "probes must attempt real capabilities even when CI is unset"
    )
    assert caps.pid_namespace or caps.unavailable_reasons


def test_all_probes_share_one_privilege_ladder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every probe must share the same sudo/unshare fallback policy (D5)."""
    monkeypatch.setenv("MERGECRAFT_PROBE_ALLOW_SUDO", "1")

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        script = cmd[-1]
        assert "_run_probe 0" in script
        assert 'if [ "$pid" = 0 ] && _sudo_allowed' in script
        assert "probe ||" not in script
        assert 'mount_cmd="sudo mount"' in script
        assert 'umount_cmd="sudo umount"' in script
        return type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": b"pid=1 pid_method=sudo-unshare net=1 bind=1 tmpfs=1\n",
            },
        )()

    monkeypatch.setattr(sandbox_mod.subprocess, "run", _fake_run)
    caps = sandbox_mod.probe_capabilities()
    assert caps.pid_namespace is True
    assert caps.pid_namespace_method == "sudo-unshare"
    assert caps.network_namespace is True
    assert caps.read_only_bind is True
    assert caps.tmpfs is True


def test_probe_capabilities_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def _fake_run(*_a: object, **_k: object) -> object:
        nonlocal calls
        calls += 1
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(sandbox_mod.subprocess, "run", _fake_run)
    sandbox_mod.probe_capabilities()
    sandbox_mod.probe_capabilities()
    assert calls == 1, "probe_capabilities must be lru_cached (MCB-35)"


def test_reset_detection_cache_clears_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def _fake_run(*_a: object, **_k: object) -> object:
        nonlocal calls
        calls += 1
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(sandbox_mod.subprocess, "run", _fake_run)
    sandbox_mod.probe_capabilities()
    shell_mod.reset_detection_cache()
    sandbox_mod.probe_capabilities()
    assert calls == 2, "reset_detection_cache must clear probe_capabilities cache"
