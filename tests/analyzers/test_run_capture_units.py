"""The analyzer capture limit counts UTF-8 bytes, and says so (#1591).

The bounded reader keeps at most ``MAX_CAPTURED_OUTPUT_BYTES`` bytes of each
stream. Everything downstream of it (the redaction-safe cut, the cap after
redaction, the exceeded notice) has to use the same unit: a multi-byte stream
must not keep more bytes than the limit, an exact fit must not be reported as
exceeding it, and the notice states the limit in bytes.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from mergecraft.analyzers import run as run_mod
from mergecraft.analyzers.resolve import AnalyzerPlan

_LINES_AT_LIMIT = 16
_CHARS = [
    pytest.param("a", id="ascii"),
    pytest.param("é", id="two-byte"),
    pytest.param("€", id="three-byte"),
    pytest.param("🎉", id="four-byte"),
]


def _line(char: str) -> str:
    return char * 31 + "\n"


def _limit(char: str) -> int:
    """A byte limit that ``_LINES_AT_LIMIT`` lines of *char* fill exactly."""
    return len(_line(char).encode("utf-8")) * _LINES_AT_LIMIT


def _plan(tmp_path: Path) -> AnalyzerPlan:
    return AnalyzerPlan(
        manifest_id="probe",
        argv=(sys.executable, "-c", "pass"),
        cwd=tmp_path,
        mode="repo-native",
        timeout_s=30,
    )


def _outcome(tmp_path: Path, stdout: str, *, truncated: bool) -> run_mod.AnalyzerOutcome:
    completed = subprocess.CompletedProcess(args=["probe"], returncode=0, stdout=stdout, stderr="")
    return run_mod._outcome_from_completed(
        completed,
        plan=_plan(tmp_path),
        command="probe",
        output_dir=tmp_path,
        truncated=frozenset({"stdout"}) if truncated else frozenset(),
    )


def _persisted(outcome: run_mod.AnalyzerOutcome) -> bytes:
    assert outcome.output_path is not None
    return Path(outcome.output_path).read_bytes()


@pytest.mark.parametrize("char", _CHARS)
@pytest.mark.parametrize("lines", [_LINES_AT_LIMIT - 1, _LINES_AT_LIMIT], ids=["below", "at"])
def test_a_stream_within_the_byte_limit_is_kept_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, char: str, lines: int
) -> None:
    limit = _limit(char)
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_BYTES", limit)
    payload = _line(char) * lines

    text, truncated = run_mod._read_bounded_stream(io.StringIO(payload), limit)
    outcome = _outcome(tmp_path, text, truncated=truncated)

    assert (text, truncated) == (payload, False)
    assert "exceeded" not in outcome.output
    assert _persisted(outcome).decode("utf-8") == payload.strip()


@pytest.mark.parametrize("char", _CHARS)
@pytest.mark.parametrize("slack", [0, 1], ids=["on-a-character", "mid-character"])
def test_a_stream_over_the_byte_limit_keeps_valid_utf8_within_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, char: str, slack: int
) -> None:
    limit = _limit(char) + slack
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_BYTES", limit)
    payload = _line(char) * (_LINES_AT_LIMIT + 1)

    text, truncated = run_mod._read_bounded_stream(io.StringIO(payload), limit)
    outcome = _outcome(tmp_path, text, truncated=truncated)

    assert truncated is True
    assert len(text.encode("utf-8")) <= limit
    assert payload.startswith(text)
    persisted = _persisted(outcome)
    assert len(persisted) <= limit
    assert payload.startswith(persisted.decode("utf-8"))
    assert f"capture limit of {limit} bytes (UTF-8) per stream" in outcome.output
    assert "chars per stream" not in outcome.output


@pytest.mark.parametrize("char", _CHARS)
def test_output_handed_over_unbounded_is_capped_in_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, char: str
) -> None:
    """Text that did not pass the reader is cut to the byte limit, not a character count."""
    limit = _limit(char)
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_BYTES", limit)
    payload = _line(char) * (_LINES_AT_LIMIT * 2)

    outcome = _outcome(tmp_path, payload, truncated=False)

    persisted = _persisted(outcome)
    assert len(persisted) <= limit
    assert payload.startswith(persisted.decode("utf-8"))
    assert f"capture limit of {limit} bytes (UTF-8) per stream" in outcome.output


def test_the_display_limit_is_separate_from_the_capture_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Output within the capture limit but past the display limit is shortened, not cut."""
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_BYTES", 64 * 1024)
    payload = "é" * (run_mod.MAX_OUTPUT_CHARS * 2)

    outcome = _outcome(tmp_path, payload, truncated=False)

    assert "exceeded" not in outcome.output
    assert f"truncated; full output saved to {outcome.output_path}" in outcome.output
    assert _persisted(outcome).decode("utf-8") == payload
