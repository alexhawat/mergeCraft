"""Lane A AP1.6 — prep environment allowlist (MCB-22)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_prep_env_is_a_real_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.prep.python import _prep_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sekret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_sekret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp")
    env = _prep_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert env.get("PATH") == "/usr/bin"
