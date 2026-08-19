"""W10 — Batch J (#279 / D11). GitLab SCM errors name this release.

``GitLabScmAdapter._unsupported()`` raises ``UnsupportedScmCapability`` with
a message that tells the caller GitLab support is not available in this release
— not only the raw capability token. The message is passed explicitly via
``message=`` so the generic format string in ``errors.py`` stays clean.
"""

from __future__ import annotations

import pytest

from mergecraft.scm.errors import UnsupportedScmCapability

_RELEASE_UNAVAILABLE = "not available in this release"


def test_gitlab_unsupported_capability_names_this_release() -> None:
    """#279 / D11 — GitLab adapter raises an error naming this release."""
    import asyncio

    from mergecraft.scm.gitlab import GitLabScmAdapter

    adapter = GitLabScmAdapter(token="x", base_url="https://gitlab.example.com")
    with pytest.raises(UnsupportedScmCapability) as exc_info:
        asyncio.run(adapter.create_pull_request(title="t", body="b", head="h", base="b"))  # type: ignore[arg-type]
    assert _RELEASE_UNAVAILABLE in str(exc_info.value)


def test_generic_unsupported_capability_uses_format_string() -> None:
    """Generic (non-GitLab) providers use the format-string message."""
    exc = UnsupportedScmCapability("get_pr", provider="SomeSCM")
    assert "SomeSCM" in str(exc)
    assert "get_pr" in str(exc)
    assert _RELEASE_UNAVAILABLE not in str(exc)


def test_explicit_message_overrides_generic() -> None:
    """``message=`` parameter overrides the format-string fallback."""
    exc = UnsupportedScmCapability(
        "get_pr",
        provider="TestSCM",
        message="custom message for this release",
    )
    assert str(exc) == "custom message for this release"
