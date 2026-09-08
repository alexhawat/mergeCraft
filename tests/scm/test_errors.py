"""W10 — Batch J (#279 / D11). ``UnsupportedScmCapability`` messaging.

Generic providers use the format-string message. An explicit ``message=``
overrides that fallback.
"""

from __future__ import annotations

from mergecraft.scm.errors import UnsupportedScmCapability

_RELEASE_UNAVAILABLE = "not available in this release"


def test_generic_unsupported_capability_uses_format_string() -> None:
    """Generic providers use the format-string message."""
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
