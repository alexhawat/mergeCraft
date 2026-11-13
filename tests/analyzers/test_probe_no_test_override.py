"""Environment values cannot manufacture sandbox isolation capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from mergecraft.analyzers import sandbox


def test_test_environment_cannot_bypass_platform_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "external-caller")
    monkeypatch.setenv("MERGECRAFT_PROBE_TEST_DOUBLE", "1")
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setenv("PATH", "")
    sandbox.probe_capabilities.cache_clear()
    try:
        capabilities = sandbox.probe_capabilities()
        assert not capabilities.pid_namespace
        assert not capabilities.network_namespace
        assert not capabilities.read_only_bind
        assert not capabilities.tmpfs
    finally:
        sandbox.probe_capabilities.cache_clear()
