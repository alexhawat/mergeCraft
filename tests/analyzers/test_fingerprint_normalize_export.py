"""Agent-supplied slug fingerprints normalize at ingress, not on wire export."""

from __future__ import annotations

import pytest

from mergecraft.agents.verifier import AgentFinding
from mergecraft.analyzers.finding import (
    normalize_agent_supplied_fingerprint,
    write_findings_json,
)


def test_normalize_agent_supplied_fingerprint_hashes_slug() -> None:
    slug = "review-integrity-dotgit-doc-accuracy"
    normalized = normalize_agent_supplied_fingerprint(slug)
    assert normalized != slug
    assert all(ch in "0123456789abcdef" for ch in normalized)
    assert len(normalized) >= 24


@pytest.mark.parametrize(
    "slug",
    [
        "tests/agents/test_opencode_config_isolation.py:30:opencode-cli-not-pinned-or-run-in-ci",
        "../escape",
        "..",
        "src\\win\\path.py:4:slug",
    ],
)
def test_normalize_agent_supplied_fingerprint_hashes_path_shaped_slugs(slug: str) -> None:
    """A slug carrying a path is hashed, not rejected: the digest cannot traverse.

    Rejecting the first one crashed a local review with exit 30 after its verdict
    was already recorded.
    """
    normalized = normalize_agent_supplied_fingerprint(slug)
    assert all(ch in "0123456789abcdef" for ch in normalized)
    assert normalized == normalize_agent_supplied_fingerprint(slug)


@pytest.mark.parametrize("slug", ["", "   "])
def test_normalize_agent_supplied_fingerprint_rejects_empty(slug: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        normalize_agent_supplied_fingerprint(slug)


def test_agent_finding_identity_normalizes_slug() -> None:
    slug = "review-integrity-dotgit-doc-accuracy"
    finding = AgentFinding(
        path="src/a.py",
        body="example",
        severity="Minor",
        fingerprint=slug,
    )
    identity = finding.identity()
    assert identity != slug
    assert all(ch in "0123456789abcdef" for ch in identity)


def test_write_findings_json_stays_strict_on_raw_slug(tmp_path) -> None:
    slug = "review-integrity-dotgit-doc-accuracy"
    with pytest.raises(ValueError, match=r"lowercase hex"):
        write_findings_json(
            tmp_path / "findings.json",
            [
                {
                    "tool": "agent",
                    "rule_id": "agent:test",
                    "category": "Functional Correctness",
                    "severity": "Minor",
                    "confidence": "likely",
                    "message": "example",
                    "path": "src/a.py",
                    "start_line": 1,
                    "end_line": 1,
                    "fingerprint": slug,
                    "evidence": [],
                    "remediation": None,
                    "autofix": None,
                    "introduced_by_pr": "unknown",
                    "source": "agent",
                    "scope": "change",
                    "cluster_id": None,
                }
            ],
        )
