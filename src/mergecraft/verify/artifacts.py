"""Artifact layout and screenshot redaction for behaviour verification.

Exports:
    resolve_artifacts_dir: Map issue / PR / timestamp onto the #61 layout.
    redact_screenshot: Pass post-auth screenshots through redaction (identity
        when pixels carry no secret).
"""

from __future__ import annotations

from pathlib import Path


def resolve_artifacts_dir(
    *,
    root: Path,
    issue: int | None = None,
    pr: int | None = None,
    timestamp: str | None = None,
    mode: str | None = None,
) -> Path:
    """Return the artifact directory for an issue, PR, or manual run.

    Args:
        root (Path): Repository (or fixture) root that owns ``.mergecraft/``.
        issue (int | None, optional): Issue number → ``issues/<n>/repro``.
        pr (int | None, optional): Pull-request number → ``prs/<n>/verify``.
        timestamp (str | None, optional): Manual-run stamp under ``manual/``.
        mode (str | None, optional): Unused for path selection; accepted so
            callers can pass the run mode alongside the locator.

    Returns:
        Path: Absolute or root-relative artifact directory.

    Raises:
        ValueError: When none of ``issue``, ``pr``, or ``timestamp`` is set.

    Examples:
        >>> resolve_artifacts_dir(root=Path("/tmp"), issue=61, mode="reproduce").as_posix().endswith(
        ...     "issues/61/repro"
        ... )
        True
    """
    _ = mode
    base = Path(root) / ".mergecraft" / "artifacts"
    if issue is not None:
        return base / "issues" / str(issue) / "repro"
    if pr is not None:
        return base / "prs" / str(pr) / "verify"
    if timestamp is not None:
        return base / "manual" / timestamp
    msg = "resolve_artifacts_dir requires issue, pr, or timestamp"
    raise ValueError(msg)


def redact_screenshot(path: Path) -> Path:
    """Redact a screenshot before it is referenced in a report.

    Pixel OCR is not implemented. ``run_verify_behavior`` suppresses all
    screenshots until this hook can rewrite ``path`` in place — YAML
    ``auth.strategy`` is not a reliable signal that the viewport is secret-free.

    Args:
        path (Path): Path written by ``BrowserDriver.screenshot``.

    Returns:
        Path: The same path, or a rewritten file when redaction is available.

    Examples:
        >>> redact_screenshot(Path("shot.png")).name
        'shot.png'
    """
    return Path(path)
