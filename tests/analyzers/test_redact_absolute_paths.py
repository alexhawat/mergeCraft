"""Absolute CI paths with ordinary segments survive entropy redaction (#1255)."""

from __future__ import annotations

import json

import pytest

from mergecraft.analyzers.redact import redact_analyzer_output, redact_secrets
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


# ``$TMPDIR`` on macOS: the per-user hash segment is random by construction.
_MACOS_TMP = (
    "/private/var/folders/2p/9stl57x50yv7zfs2zn_lzchh0000gn/T/pytest-of-alex/pytest-1/repo0"
)


@pytest.mark.parametrize(
    "text",
    [
        f"{_MACOS_TMP}/scripts/deploy.sh:5:3: warning: Double quote to prevent globbing",
        f"{_MACOS_TMP}/config/planted-secret.env",
        f"{_MACOS_TMP}/src/Main.java:12",
        _MACOS_TMP.removeprefix("/private"),
        f"file://{_MACOS_TMP}/src/index.js",
    ],
    ids=["gcc-line", "dotfile-ext", "java", "bare-var-folders", "file-uri"],
)
def test_macos_temp_dir_paths_are_preserved(text: str) -> None:
    assert redact_secrets(text) == text
    assert redact_analyzer_output(text, tool_id="shellcheck") == text


def test_macos_temp_dir_path_survives_inside_json_output() -> None:
    uri = f"file://{_MACOS_TMP}/src/index.js"
    raw = json.dumps({"runs": [{"results": [{"uri": uri}]}]})
    assert json.loads(redact_analyzer_output(raw, tool_id="eslint")) == json.loads(raw)


def test_a_secret_segment_under_a_macos_temp_root_is_still_redacted() -> None:
    secret = "aB3xK9mQ2z" + "L7vN4pR8tY5wC1"  # split: no literal for scanners
    out = redact_secrets(f"open {_MACOS_TMP}/{secret}/src/app.py:3")
    assert secret not in out
    assert REDACTION_SENTINEL in out
    assert out.startswith("open /private/var/folders/2p/9stl57x50yv7zfs2zn_lzchh0000gn/T")
