"""Cross-tool clustering (D12)."""

from __future__ import annotations

import pytest

from mergecraft.review_taxonomy import finding_fingerprint
from tests.analyzers.support import import_module

pytestmark = pytest.mark.xfail(reason="green after W5: cross-tool clustering", strict=False)


def _finding(tool: str, path: str, line: int, message: str) -> object:
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool=tool,
        rule_id=f"{tool}-rule",
        category="Security & Privacy",
        severity="Major",
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


def test_three_tools_one_defect_publish_one_finding_with_evidence() -> None:
    cluster = import_module("mergecraft.analyzers.cluster")
    message = "unpinned third-party action"
    findings = [
        _finding("zizmor", ".github/workflows/unpinned-action.yml", 11, message),
        _finding("actionlint", ".github/workflows/unpinned-action.yml", 11, message),
        _finding("custom", ".github/workflows/unpinned-action.yml", 11, message),
    ]
    grouped = cluster.cluster_findings(findings)
    assert len(grouped) == 1
    canonical = grouped[0]
    assert len(canonical.evidence) >= 3
    assert canonical.confidence in {"certain", "likely"}


def test_distinct_defects_on_same_line_stay_distinct() -> None:
    cluster = import_module("mergecraft.analyzers.cluster")
    findings = [
        _finding("zizmor", "Dockerfile", 2, "Using latest tag"),
        _finding("hadolint", "Dockerfile", 2, "Missing HEALTHCHECK"),
    ]
    grouped = cluster.cluster_findings(findings)
    assert len(grouped) == 2


def test_cluster_key_derives_from_finding_fingerprint() -> None:
    cluster = import_module("mergecraft.analyzers.cluster")
    message = "Double quote to prevent globbing."
    path = "scripts/deploy.sh"
    f1 = _finding("shellcheck", path, 5, message)
    expected = finding_fingerprint(path=path, body=message)
    key = cluster.cluster_key(f1)
    assert key.startswith(expected[:12]) or expected in key
