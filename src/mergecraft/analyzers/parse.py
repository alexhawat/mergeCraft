"""Parse analyzer output from persisted files (W4.6 output-size discipline)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from mergecraft.analyzers.parsers import parse_output
from mergecraft.analyzers.redact import redact_analyzer_output

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest


def persist_analyzer_output(raw: str, *, tmpdir: Path, tool_id: str) -> Path:
    """Write full analyzer output to the run tmpdir for file-based parsing."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    path = tmpdir / f"{tool_id}-{uuid.uuid4().hex[:8]}.out"
    path.write_text(raw, encoding="utf-8")
    return path


def read_output_file(path: Path) -> str:
    """Read analyzer output from disk without an 8 KB cap."""
    return path.read_text(encoding="utf-8")


def parse_output_file(
    path: Path,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> list[Finding]:
    """Parse normalized findings from a persisted analyzer output file."""
    raw = read_output_file(path)
    redacted = redact_analyzer_output(raw, tool_id=manifest.id)
    return parse_output(redacted, manifest=manifest, repo_root=repo_root)


__all__ = ["parse_output_file", "persist_analyzer_output", "read_output_file"]
