"""GitHub permalinks survive the entropy pass; tokens pasted into them do not (#1281)."""

from __future__ import annotations

import json

import pytest

from mergecraft.analyzers.redact import redact_analyzer_output, redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL

_SHA40 = "cc3a6b2d7455f996b15c5a7b934be01180c7abcd"
_SHA64 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
_GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
_PAT = (
    "github_pat_11ABCDEFG0123456789_"
    + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2w3X4y5Z6a7B8c9D0e1F2g"
)
_RANDOM_SEGMENT = "aZ9kQ2xP7vL4mN8rT1yW6sJ3hB5cD0fG"

_PERMALINKS = [
    f"https://github.com/alexhawat/mergeCraft/blob/{_SHA40}/src/mergecraft/analyzers/redact.py",
    f"https://github.com/alexhawat/mergeCraft/blob/{_SHA64}/docs/eval-bank.md",
    f"https://github.com/alexhawat/mergeCraft/tree/{_SHA40}/docs",
    f"https://github.com/alexhawat/mergeCraft/commit/{_SHA40}",
    "https://github.com/alexhawat/mergeCraft/actions/runs/42851842248",
    "https://github.com/alexhawat/mergeCraft/actions/runs/42851842248/job/123456789012",
    "https://github.com/alexhawat/mergeCraft/pull/1167",
    "https://github.com/alexhawat/mergeCraft/issues/1165",
    "https://github.com/some-org/repo.name_2/pull/7",
]


@pytest.mark.parametrize("link", _PERMALINKS)
def test_each_permalink_shape_survives(link: str) -> None:
    assert redact_secrets(link) == link
    assert redact_secrets(f"see {link} for context") == f"see {link} for context"
    assert redact_secrets(f"({link}).") == f"({link})."


@pytest.mark.parametrize("link", _PERMALINKS)
def test_permalinks_survive_in_json_analyzer_output(link: str) -> None:
    raw = json.dumps({"message": f"see {link}", "help": link})
    assert link in redact_analyzer_output(raw, tool_id="semgrep")


def test_fragment_is_not_part_of_the_exemption_but_a_line_anchor_is_harmless() -> None:
    link = f"https://github.com/o/r/blob/{_SHA40}/src/app.py#L10-L12"
    assert redact_secrets(link) == link


@pytest.mark.parametrize("secret", [_GHP, _PAT])
def test_token_in_the_path_is_still_redacted(secret: str) -> None:
    out = redact_secrets(f"https://github.com/o/r/blob/{_SHA40}/{secret}/x.py")
    assert secret not in out
    assert REDACTION_SENTINEL in out


@pytest.mark.parametrize("secret", [_GHP, _PAT])
def test_token_in_the_query_is_still_redacted(secret: str) -> None:
    for link in (
        f"https://github.com/o/r/blob/{_SHA40}/x.py?token={secret}",
        f"https://github.com/o/r/blob/{_SHA40}/x.py?{secret}",
        f"https://github.com/o/r/pull/12?ref={secret}",
        "https://github.com/o/r/actions/runs/42851842248?check_suite_focus=" + secret,
    ):
        out = redact_secrets(link)
        assert secret not in out, link
        assert REDACTION_SENTINEL in out, link


def test_high_entropy_path_segment_is_still_redacted() -> None:
    out = redact_secrets(f"https://github.com/o/r/blob/{_SHA40}/{_RANDOM_SEGMENT}/x.py")
    assert _RANDOM_SEGMENT not in out


def test_high_entropy_query_and_fragment_are_still_redacted() -> None:
    for suffix in (f"?x={_RANDOM_SEGMENT}", f"#{_RANDOM_SEGMENT}"):
        out = redact_secrets(f"https://github.com/o/r/pull/12{suffix}")
        assert _RANDOM_SEGMENT not in out, suffix
        assert out.startswith("https://github.com/o/r/pull/12"), suffix


def test_high_entropy_owner_or_repo_is_not_exempt() -> None:
    out = redact_secrets(f"https://github.com/o/{_RANDOM_SEGMENT}/pull/12")
    assert _RANDOM_SEGMENT not in out


def test_trailing_segment_after_an_exact_shape_is_still_checked() -> None:
    out = redact_secrets(f"https://github.com/o/r/pull/12/{_RANDOM_SEGMENT}")
    assert _RANDOM_SEGMENT not in out


@pytest.mark.parametrize(
    "link",
    [
        # Not an exact shape: a short SHA, a non-hex ref, a non-numeric run id.
        f"https://github.com/o/r/blob/main/{_RANDOM_SEGMENT}/x.py",
        f"https://github.com/o/r/actions/runs/{_RANDOM_SEGMENT}",
        f"https://github.com/o/r/pull/12{_RANDOM_SEGMENT}",
        f"https://evil.example/o/r/pull/12/{_RANDOM_SEGMENT}",
    ],
)
def test_non_permalink_shapes_get_no_exemption(link: str) -> None:
    assert _RANDOM_SEGMENT not in redact_secrets(link)
