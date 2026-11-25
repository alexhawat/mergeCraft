"""Container image references and version strings survive the log redactor (#1560)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_log_message
from mergecraft.redaction_sentinel import REDACTION_SENTINEL


def _image_digest() -> str:
    return "sha256:" + ("0123456789abcdef" * 4)


def _mixed_case_tag() -> str:
    """A 40-character mixed-case run: the shape of a pasted credential."""
    return ("Ab3xK9qLmZ7pR2tY8wQ1vN4c8FgH2jK5mP7sT9" * 2)[:40]


def _build_blob() -> str:
    return ("Ab3xK9qLmZ7pR2tY8wQ1vN4c8FgH2jK5" * 2)[:32]


def _github_token_body() -> str:
    return ("a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6" + "q7R8")[:36]


@pytest.mark.parametrize(
    "reference",
    [
        "ghcr.io/alexhawat/mergecraft-action:v0.1.0a6",
        "docker.io/library/python:3.12-slim",
        f"registry.example.test/team/app@{_image_digest()}",
        "v1.2.3-rc.1+build.55",
    ],
)
def test_image_references_and_versions_survive_log_redaction(reference: str) -> None:
    assert redact_log_message(reference) == reference


@pytest.mark.parametrize(
    "line",
    [
        "semgrep 1.170.0",
        "0.1.0a6",
    ],
)
def test_short_versions_already_survive_log_redaction(line: str) -> None:
    assert redact_log_message(line) == line


def test_image_tag_shaped_as_a_mixed_case_blob_is_still_redacted() -> None:
    tag = _mixed_case_tag()
    out = redact_log_message(f"ghcr.io/org/app:{tag}")
    assert tag not in out
    assert REDACTION_SENTINEL in out


def test_version_with_a_long_build_blob_is_still_redacted() -> None:
    blob = _build_blob()
    out = redact_log_message(f"v1.2.3+{blob}")
    assert blob not in out
    assert REDACTION_SENTINEL in out


def test_version_with_an_embedded_token_is_still_redacted() -> None:
    body = _github_token_body()
    out = redact_log_message(f"1.2.3-ghp_{body}")
    assert body not in out
    assert "ghp_" not in out
