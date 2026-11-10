"""Absolute CI paths with ordinary segments survive entropy redaction (#1255)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL


@pytest.mark.parametrize(
    "path",
    [
        "/home/runner/work/repo/src/app/module.py:12",
        "/home/runner/work/mergeCraft/mergeCraft/src/pkg/util.py",
        "/tmp/x/a.py",
        "/github/workspace/tests/unit/test_thing.py:7",
    ],
)
def test_absolute_paths_with_ordinary_segments_are_preserved(path: str) -> None:
    assert redact_secrets(f"error at {path}") == f"error at {path}"


def test_relative_path_behaviour_unchanged() -> None:
    assert redact_secrets("see src/app/module.py:12") == "see src/app/module.py:12"


def test_secret_looking_segment_in_absolute_path_is_still_redacted() -> None:
    secret = "aB3xK9mQ2zL7vN4pR8tY5wC1"
    out = redact_secrets(f"open /home/runner/work/{secret}/src/app.py:3")
    assert secret not in out
    assert REDACTION_SENTINEL in out


def test_secret_looking_filename_stem_in_absolute_path_is_still_redacted() -> None:
    secret = "Zk4Qm9Xw2Lp7Vn3Rt8Yc5Hb"
    out = redact_secrets(f"/home/runner/work/repo/{secret}.py")
    assert secret not in out
