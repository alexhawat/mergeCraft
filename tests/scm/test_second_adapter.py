"""DG9.1 RED suite — second SCM adapter contract (D10 demand-gated).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (DG9.1 RED,
DG9.2 impl).
"""

from __future__ import annotations

import pytest
from tests.scm.conftest import require_scm


def test_one_additional_provider_satisfies_the_protocol() -> None:
    """At least one non-GitHub adapter fully implements ``ScmProvider``."""
    require_scm()
    from mergecraft.scm.gitlab import GitLabScmAdapter
    from mergecraft.scm.protocol import ScmProvider, validate_provider

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    assert isinstance(adapter, ScmProvider)
    report = validate_provider(adapter)
    assert report.complete is True, f"adapter missing protocol operations: {report.missing}"


def test_unsupported_capability_is_declared_not_faked() -> None:
    """Providers declare unsupported capabilities instead of emulating GitHub."""
    require_scm()
    from mergecraft.scm.errors import UnsupportedScmCapability
    from mergecraft.scm.gitlab import GitLabScmAdapter
    from mergecraft.scm.protocol import ScmCapability

    adapter = GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4")
    assert ScmCapability.GRAPHQL not in adapter.capabilities

    with pytest.raises(UnsupportedScmCapability) as exc_info:
        adapter.graphql("query { viewer { username } }")

    message = str(exc_info.value).lower()
    assert "graphql" in message or "unsupported" in message
    assert "capabilit" in message
