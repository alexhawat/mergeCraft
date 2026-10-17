"""Export paths must tolerate model-supplied slug fingerprints."""

from __future__ import annotations

from pathlib import Path

from mergecraft.analyzers.finding import normalize_export_fingerprint, write_findings_json


def test_normalize_export_fingerprint_hashes_slug() -> None:
    slug = "review-integrity-dotgit-doc-accuracy"
    normalized = normalize_export_fingerprint(slug)
    assert normalized != slug
    assert all(ch in "0123456789abcdef" for ch in normalized)
    assert len(normalized) >= 24


def test_write_findings_json_accepts_slug_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "findings.json"
    write_findings_json(
        path,
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
                "fingerprint": "review-integrity-dotgit-doc-accuracy",
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
    assert path.is_file()
    assert "review-integrity-dotgit-doc-accuracy" not in path.read_text(encoding="utf-8")
