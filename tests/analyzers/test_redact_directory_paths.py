"""Directory-only paths survive the log redactor (#1560)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_log_message
from mergecraft.redaction_sentinel import REDACTION_SENTINEL

_SURVIVING_PATHS = [
    ".github/workflows",
    ".mergecraft/analyzers",
    "/root/.cache/mergecraft/analyzers",
    ".git/worktrees/mergecraft-base",
    "src/mergecraft/cli",
    "python=/usr/bin/python3.12",
]


def _high_entropy_segment() -> str:
    """A mixed-case alphanumeric run: the shape of a pasted credential."""
    return "aB3xK9qLmZ7pR2tY8wQ1" + "vN4c"


def _low_entropy_random_segment() -> str:
    """A lowercase hex-like run: random by shape, under a word-based entropy bar."""
    return "e405" + "ee00" + "d36e" + "8e0"


_LOW_ENTROPY_RANDOM_SEGMENT = _low_entropy_random_segment()


def _absolute_high_entropy_segment() -> str:
    return "Zx9Kq2Lm8Pw3Rt7Yv1Nc5" + "Bd0"


def _base64_like_secret() -> str:
    """A 40-character base64-shaped run carrying two slashes."""
    body = ("aB3xK9qLmZ7pR2tY8wQ1vN4cP0lK" * 2)[:38]
    return f"{body[:13]}/{body[13:31]}/{body[31:38]}"


def _github_token_body() -> str:
    return ("a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6" + "q7R8")[:36]


def _userinfo_password() -> str:
    return ("Ab3xK9qLmZ7pR2tY8wQ1" * 2)[:21]


@pytest.mark.parametrize("path", _SURVIVING_PATHS)
def test_directory_paths_survive_log_redaction(path: str) -> None:
    assert redact_log_message(path) == path


def test_directory_path_survives_inside_a_sentence() -> None:
    line = "provisioning semgrep into /root/.cache/mergecraft/analyzers (python3.12)"
    assert redact_log_message(line) == line


def test_high_entropy_directory_segment_is_still_redacted() -> None:
    secret = _high_entropy_segment()
    out = redact_log_message(f"src/{secret}/x")
    assert secret not in out
    assert REDACTION_SENTINEL in out


def test_absolute_path_with_high_entropy_segment_is_still_redacted() -> None:
    secret = _absolute_high_entropy_segment()
    out = redact_log_message(f"/home/u/.config/{secret}")
    assert secret not in out
    assert REDACTION_SENTINEL in out


@pytest.mark.parametrize(
    "text",
    [
        f"src/{_LOW_ENTROPY_RANDOM_SEGMENT}",
        f"/opt/{_LOW_ENTROPY_RANDOM_SEGMENT}",
        f"python=/usr/bin/{_LOW_ENTROPY_RANDOM_SEGMENT}",
    ],
)
def test_random_looking_low_entropy_segment_is_still_redacted(text: str) -> None:
    assert _LOW_ENTROPY_RANDOM_SEGMENT not in redact_log_message(text)


def test_base64_with_two_slashes_is_still_redacted() -> None:
    secret = _base64_like_secret()
    assert len(secret) == 40
    assert secret.count("/") == 2
    out = redact_log_message(f"header {secret}")
    assert secret not in out
    assert REDACTION_SENTINEL in out


def test_github_token_after_a_directory_is_still_redacted() -> None:
    body = _github_token_body()
    out = redact_log_message(f"tokens/ghp_{body}")
    assert body not in out
    assert "ghp_" not in out


def test_url_userinfo_password_is_still_redacted() -> None:
    password = _userinfo_password()
    out = redact_log_message(f"https://user:{password}@example.test/path")
    assert password not in out
    assert REDACTION_SENTINEL in out
