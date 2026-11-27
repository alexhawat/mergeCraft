"""User-facing change detection and end-to-end proof scanning (#1611)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_DEFAULT_UI_GLOBS: tuple[str, ...] = (
    "**/*.tsx",
    "**/*.jsx",
    "**/*.vue",
    "**/templates/**",
    "**/static/**",
    "**/public/**",
    "**/ui/**",
    "**/components/**",
)
_DEFAULT_CLI_GLOBS: tuple[str, ...] = (
    "**/cli/**",
    "**/__main__.py",
    "**/commands/**",
)
_DEFAULT_API_GLOBS: tuple[str, ...] = (
    "**/__init__.py",
    "**/api/**",
    "docs/**/*.md",
)
_DEFAULT_PERF_GLOBS: tuple[str, ...] = (
    "**/perf/**",
    "**/benchmark/**",
    "**/*bench*.*",
    "**/hot/**",
)

_IMAGE_PROOF_RE = re.compile(
    r"!\[[^\]]*\]\([^)]+\)|<img\b|user-images\.githubusercontent\.com|"
    r"github\.com/.*/assets/",
    re.IGNORECASE,
)
_VIDEO_PROOF_RE = re.compile(
    r"\.(?:mp4|webm|mov|gif)\b|\.(?:mp4|webm|mov)\)|video/|recording",
    re.IGNORECASE,
)
_BENCH_PROOF_RE = re.compile(
    r"\b(?:benchmark|profil(?:e|ing)|flamegraph|perf(?:\s+test)?|latency\s+test)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class UserFacingChange:
    """What kind of user-facing surface changed."""

    ui_paths: tuple[str, ...]
    cli_paths: tuple[str, ...]
    api_paths: tuple[str, ...]
    perf_paths: tuple[str, ...]

    @property
    def any_ui(self) -> bool:
        return bool(self.ui_paths or self.cli_paths or self.api_paths)

    @property
    def any_perf(self) -> bool:
        return bool(self.perf_paths)


@dataclass(frozen=True, slots=True)
class ProofScan:
    """Where proof was searched and what was found."""

    sources_searched: tuple[str, ...]
    has_visual_proof: bool
    has_perf_proof: bool


def default_user_facing_globs() -> tuple[str, ...]:
    """Default globs for detecting user-facing diffs."""
    return _DEFAULT_UI_GLOBS + _DEFAULT_CLI_GLOBS + _DEFAULT_API_GLOBS


def default_perf_globs() -> tuple[str, ...]:
    return _DEFAULT_PERF_GLOBS


def _match_paths(paths: Sequence[str], globs: Sequence[str]) -> tuple[str, ...]:
    matched: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").lstrip("./")
        if any(fnmatch(normalized, pattern) for pattern in globs):
            matched.append(normalized)
    return tuple(dict.fromkeys(matched))


def detect_user_facing_changes(
    changed_paths: Sequence[str],
    *,
    user_facing_globs: Sequence[str] | None = None,
    perf_globs: Sequence[str] | None = None,
) -> UserFacingChange:
    """Classify changed paths against configured globs."""
    perf = perf_globs or default_perf_globs()
    normalized = [p.replace("\\", "/").lstrip("./") for p in changed_paths]
    extra = list(user_facing_globs or ())
    ui_globs = _DEFAULT_UI_GLOBS + tuple(g for g in extra if g not in _DEFAULT_UI_GLOBS)
    return UserFacingChange(
        ui_paths=_match_paths(normalized, ui_globs),
        cli_paths=_match_paths(normalized, _DEFAULT_CLI_GLOBS + tuple(extra)),
        api_paths=_match_paths(normalized, _DEFAULT_API_GLOBS + tuple(extra)),
        perf_paths=_match_paths(normalized, perf),
    )


def scan_e2e_proof(
    *,
    pr_body: str | None = None,
    review_summary: str | None = None,
    artifact_names: Sequence[str] | None = None,
    run_artifact_paths: Sequence[str] | None = None,
) -> ProofScan:
    """Scan PR body, review summary, CI artifact names, and run artifacts for proof.

    Documented proof locations (``docs/merge-attention.md``):
    - Pull request description and review summary (markdown images, attachments, bench notes)
    - Workflow artifact basenames listed in ``ci_evidence`` ingest
    - Files under the run evidence directory whose names end in image/video extensions
    """
    chunks: list[str] = []
    sources: list[str] = []
    if pr_body and pr_body.strip():
        chunks.append(pr_body)
        sources.append("pr_description")
    if review_summary and review_summary.strip():
        chunks.append(review_summary)
        sources.append("review_summary")
    for name in artifact_names or ():
        if name.strip():
            chunks.append(name)
    if artifact_names:
        sources.append("ci_artifacts")
    artifact_paths = list(run_artifact_paths or ())
    for path in artifact_paths:
        if path.strip():
            chunks.append(path)
    if artifact_paths:
        sources.append("run_artifacts")
    combined = "\n".join(chunks)
    visual = bool(_IMAGE_PROOF_RE.search(combined) or _VIDEO_PROOF_RE.search(combined))
    for path in artifact_paths:
        lower = path.lower()
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov")):
            visual = True
            break
    perf = bool(_BENCH_PROOF_RE.search(combined))
    for path in artifact_paths:
        lower = path.lower()
        if "bench" in lower or "perf" in lower or lower.endswith((".prof", ".svg")):
            perf = True
            break
    return ProofScan(
        sources_searched=tuple(dict.fromkeys(sources)),
        has_visual_proof=visual,
        has_perf_proof=perf,
    )


def verification_gaps_for_user_facing(
    change: UserFacingChange,
    proof: ProofScan,
) -> list[str]:
    """Return human-readable verification gaps (not nits)."""
    gaps: list[str] = []
    searched = ", ".join(proof.sources_searched) if proof.sources_searched else "no sources"
    if change.any_ui and not proof.has_visual_proof:
        gaps.append(
            "User-facing paths changed but no before/after screenshot or recording was found "
            f"(searched: {searched})."
        )
    if change.any_perf and not proof.has_perf_proof:
        gaps.append(
            "Performance-sensitive paths changed but no benchmark or profiling evidence was "
            f"found (searched: {searched})."
        )
    return gaps


__all__ = [
    "ProofScan",
    "UserFacingChange",
    "default_perf_globs",
    "default_user_facing_globs",
    "detect_user_facing_changes",
    "scan_e2e_proof",
    "verification_gaps_for_user_facing",
]
