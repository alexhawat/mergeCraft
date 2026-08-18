"""DG6 citations — reproducible repo + SHA + location (convention 4).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG6).
Implementation: **DG6.2** — ``mergecraft.xrepo.citations``.
"""

from __future__ import annotations

import pytest
from tests.xrepo.support import import_xrepo_module


@pytest.mark.xfail(reason="green after DG6.2: citation validation", strict=False)
def test_every_citation_carries_repo_sha_and_location() -> None:
    """Convention 4 — every cross-repo citation carries repo, commit SHA, path, and range."""
    citations_mod = import_xrepo_module("citations")
    citation = citations_mod.Citation(
        repo="acme/api-contracts",
        sha="abc111" * 5,
        path="openapi.yaml",
        start_line=12,
        end_line=18,
    )

    citations_mod.validate_citation(citation)
    formatted = citations_mod.format_citation(citation)

    assert citation.repo in formatted
    assert citation.sha in formatted
    assert citation.path in formatted
    assert "12" in formatted
    assert "18" in formatted
