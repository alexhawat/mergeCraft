"""F40 — the temp findings sink is created without leaking a file descriptor."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from mergecraft.cli import diff_review_cmd


def test_findings_sink_is_a_closed_temp_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    fds: list[int] = []
    real_mkstemp = tempfile.mkstemp

    def _tracking_mkstemp(**kwargs: Any) -> tuple[int, str]:
        fd, name = real_mkstemp(**kwargs)
        fds.append(fd)
        return fd, name

    monkeypatch.setattr(diff_review_cmd.tempfile, "mkstemp", _tracking_mkstemp)

    sink = diff_review_cmd._allocate_findings_sink()

    assert sink.is_file()
    assert sink.name.startswith("mergecraft-review-findings-")
    assert sink.suffix == ".json"
    assert len(fds) == 1
    with pytest.raises(OSError, match=r"\[Errno 9\]"):
        os.fstat(fds[0])
    sink.unlink()
