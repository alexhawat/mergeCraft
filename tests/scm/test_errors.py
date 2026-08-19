"""W10 — Batch J RED (#279 / D11). GitLab SCM errors name this release.

``UnsupportedScmCapability("get_pr", provider="GitLabScmAdapter")`` must tell
the caller GitLab support is not available in this release — not only a
capability token. Today's wording is the capability form (W12 rewrites it).
"""

from __future__ import annotations

from mergecraft.scm.errors import UnsupportedScmCapability

_RELEASE_UNAVAILABLE = "not available in this release"


def test_gitlab_unsupported_capability_names_this_release() -> None:
    """#279 / D11 — GitLab get_pr error names the release, not only a capability."""
    exc = UnsupportedScmCapability("get_pr", provider="GitLabScmAdapter")
    assert _RELEASE_UNAVAILABLE in str(exc)
