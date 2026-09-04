"""Parse analyzer output from persisted files (W4.6 output-size discipline)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from mergecraft.analyzers.parsers import parse_output
from mergecraft.analyzers.redact import redact_for_fingerprint, redact_secrets

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest


def _redact_findings(findings: list[Finding], *, tool_id: str) -> list[Finding]:
    redacted: list[Finding] = []
    for finding in findings:
        message = redact_secrets(finding.message)
        evidence = [redact_secrets(item) for item in finding.evidence]
        body = redact_for_fingerprint(finding.message, tool_id=tool_id)
        fingerprint = finding.fingerprint
        if body != finding.message:
            from mergecraft.review_taxonomy import finding_fingerprint

            fingerprint = finding_fingerprint(path=finding.path, body=body)
        redacted.append(
            finding.model_copy(
                update={
                    "message": message,
                    "evidence": evidence,
                    "fingerprint": fingerprint,
                }
            )
        )
    return redacted


def persist_analyzer_output(raw: str, *, tmpdir: Path, tool_id: str) -> Path:
    """Write full analyzer output to the run tmpdir for file-based parsing."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    path = tmpdir / f"{tool_id}-{uuid.uuid4().hex[:8]}.out"
    path.write_text(raw, encoding="utf-8")
    return path


def _read_output_file(path: Path) -> str:
    """Read analyzer output from disk without an 8 KB cap."""
    return path.read_text(encoding="utf-8")


def parse_output_file(
    path: Path,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> list[Finding]:
    """Parse normalized findings from a persisted analyzer output file."""
    raw = _read_output_file(path)
    findings = parse_output(raw, manifest=manifest, repo_root=repo_root)
    return _redact_findings(findings, tool_id=manifest.id)


__all__ = ["parse_output_file", "persist_analyzer_output"]
