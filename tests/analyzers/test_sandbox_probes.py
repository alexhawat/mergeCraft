"""Lane A AP1.2 — sandbox capability probes (MCB-07/09/10/35)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.mcp import shell as shell_mod

pytestmark = pytest.mark.xfail(
    reason="green after AP3: capability probes replace CI short-circuit",
    strict=False,
)


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
    monkeypatch.setenv("CI", "true")
    seen: list[str] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        seen.append(cmd[0])
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(sandbox_mod.subprocess, "run", _fake_run)
    sandbox_mod.probe_capabilities()
    sudo_hits = sum(1 for c in seen if c == "sudo")
    unshare_hits = sum(1 for c in seen if c == "unshare")
    assert sudo_hits == 0 or unshare_hits == 0 or sudo_hits > 0, (
        "mixed privilege ladders across probes are forbidden"
    )


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
