"""Anti-slop analyzer — catalog stub (#393)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mergecraft.analyzers.antislop.policy import AntislopRule, load_native_rules

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding


@dataclass(frozen=True, slots=True)
class AntislopScanResult:
    """Outcome of scanning changed source files for anti-slop patterns."""

    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None


def scan_changed_files(
    *,
    repo_root: Path,
    changed_files: list[str],
) -> AntislopScanResult:
    """Scan changed files — matcher ships in the next wave."""
    _ = repo_root.resolve(), changed_files, load_native_rules()
    return AntislopScanResult(
        findings=[],
        skipped=True,
        skip_reason="skipped antislop: matcher not wired yet",
    )


__all__ = [
    "AntislopRule",
    "AntislopScanResult",
    "load_native_rules",
    "scan_changed_files",
]
