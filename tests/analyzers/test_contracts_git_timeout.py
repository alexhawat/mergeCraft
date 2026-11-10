"""Contract base-ref git probes are bounded: a hung git reads as "base unavailable"."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers import contracts

if TYPE_CHECKING:
    import pytest


def _hang(seen: list[object]) -> object:
    def _run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=float(contracts._GIT_TIMEOUT_S))

    return _run


def test_ref_probe_timeout_reads_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(contracts.subprocess, "run", _hang(seen))

    assert contracts._git_ref_available(tmp_path, "origin/main") is False
    assert seen == [contracts._GIT_TIMEOUT_S]


def test_base_file_show_timeout_resolves_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(contracts, "_git_ref_available", lambda *_a: True)
    monkeypatch.setattr(contracts.subprocess, "run", _hang(seen))

    assert contracts._resolve_base_file(tmp_path, "api/openapi.yaml", "origin/main") is None
    assert seen == [contracts._GIT_TIMEOUT_S]
    assert not (tmp_path / ".mergecraft").exists(), "no scratch file on a timed-out show"
