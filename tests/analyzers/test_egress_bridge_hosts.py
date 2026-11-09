"""F41 — the egress bridge's hosts-file bind mount is bounded and its staging dir is removed."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers import egress_bridge

if TYPE_CHECKING:
    import pytest

_HOSTS = {"api.example.com": ["203.0.113.7"]}


def _install_fake_mount(monkeypatch: pytest.MonkeyPatch, *, timeout: bool) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen["timeout"] = kwargs.get("timeout")
        source = Path(argv[argv.index("--bind") + 1])
        seen["source"] = source
        seen["contents"] = source.read_text(encoding="utf-8")
        if timeout:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout") or 0)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(egress_bridge.subprocess, "run", _run)
    return seen


def test_hosts_mount_is_bounded_and_staging_removed_after_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install_fake_mount(monkeypatch, timeout=False)

    egress_bridge._write_hosts(_HOSTS)

    assert seen["argv"][-1] == "/etc/hosts"
    assert seen["timeout"] == egress_bridge._HOSTS_MOUNT_TIMEOUT_S
    assert "203.0.113.7 api.example.com" in seen["contents"]
    assert not seen["source"].exists(), "the bind-mount source tree must not be left behind"
    assert not seen["source"].parent.exists()


def test_hosts_mount_timeout_is_not_fatal_and_still_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install_fake_mount(monkeypatch, timeout=True)

    egress_bridge._write_hosts(_HOSTS)

    assert seen["timeout"] == egress_bridge._HOSTS_MOUNT_TIMEOUT_S
    assert not seen["source"].parent.exists()
