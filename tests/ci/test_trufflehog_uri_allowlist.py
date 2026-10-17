"""Documentation URIs and the redaction patterns stop flagging themselves (#885).

TruffleHog's ``URI`` detector matches ``scheme://user:password@host``. The
redaction module is *about* that shape — its patterns and doctests spell it out
on purpose — and the tracing doc shows the same example, so every self-review
reported them as "URI secret detected". The allowlist is finding-level, not
path-level: one file, one detector. A different detector in the same file, or
the same detector in any other file, still reaches the review.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from tests.analyzers.support import import_module
from tests.ci.workflow_support import REPO_ROOT, read_text

if TYPE_CHECKING:
    from pathlib import Path

_REDACTION = "src/mergecraft/tracing/redaction.py"


def _module() -> Any:
    return import_module("scripts.ci_extended_sarif")


def _finding(path: str, detector: str, line: int = 1) -> str:
    return json.dumps(
        {
            "SourceMetadata": {"Data": {"Filesystem": {"file": path, "line": line}}},
            "DetectorName": detector,
            "Verified": False,
            "Raw": "PLANTED_NOT_A_REAL_SECRET",
        }
    )


def _emit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, findings: list[tuple[str, str, int]]
) -> list[tuple[str, str]]:
    module = _module()
    stdout = "\n".join(_finding(path, detector, line) for path, detector, line in findings) + "\n"
    monkeypatch.setattr(module, "_trufflehog_scan_argv", lambda **_kwargs: ["trufflehog"])
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["trufflehog"], returncode=0, stdout=stdout, stderr=""
        ),
    )
    out = tmp_path / "trufflehog.sarif"
    module.emit_trufflehog_sarif(out=out, repo_root=tmp_path)
    document = json.loads(out.read_text(encoding="utf-8"))
    return [
        (
            item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
            item["ruleId"],
        )
        for item in document["runs"][0]["results"]
    ]


def test_the_redaction_modules_own_uri_patterns_no_longer_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emitted = _emit(tmp_path, monkeypatch, [(_REDACTION, "URI", line) for line in range(1, 8)])
    assert emitted == []


def test_a_real_secret_in_the_same_file_still_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emitted = _emit(
        tmp_path,
        monkeypatch,
        [(_REDACTION, "URI", 62), (_REDACTION, "AWS", 70), (_REDACTION, "Github", 71)],
    )
    assert emitted == [(_REDACTION, "AWS"), (_REDACTION, "Github")]


def test_a_uri_secret_in_any_other_file_still_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = "src/mergecraft/utils/new_secret_source.py"
    emitted = _emit(tmp_path, monkeypatch, [(other, "URI", 3), (_REDACTION, "URI", 4)])
    assert emitted == [(other, "URI")]


def test_the_allowlist_is_finding_level_and_every_entry_is_reasoned() -> None:
    module = _module()
    allowed = dict(module.TRUFFLEHOG_ALLOWED_FINDINGS)
    assert (_REDACTION, "URI") in allowed
    for (path, detector), reason in allowed.items():
        assert detector, f"{path}: an allowlist entry must name the detector, not just a path"
        assert (REPO_ROOT / path).is_file(), f"stale allowlist entry: {path}"
        assert reason.strip(), f"{path}/{detector} must record why it is exempt"
    paths = [path for path, _ in allowed]
    assert not any(path.endswith(("/", "**")) for path in paths), "no directory or glob entries"


_CREDENTIAL_SHAPED_URI = re.compile(r"https?://[^\s/:@`]+:[^\s/@`]+@[\w.-]+")


@pytest.mark.parametrize("relative", ["docs/TRACING.md", "llms-full.txt"])
def test_documented_credential_shaped_examples_carry_the_inline_marker(relative: str) -> None:
    """TruffleHog skips a line that carries ``trufflehog:ignore``; the rest still scan."""
    for number, line in enumerate(read_text(relative).splitlines(), start=1):
        if _CREDENTIAL_SHAPED_URI.search(line):
            assert "trufflehog:ignore" in line, (
                f"{relative}:{number} spells a credential-shaped URI without the inline marker"
            )
