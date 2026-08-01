"""Resolve a local unified diff for offline ``mergecraft diff-review``."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

_DEFAULT_BASES = ("main", "master", "develop", "trunk")


@dataclass(slots=True)
class DiffMaterialization:
    """Result of writing a reviewable unified diff to disk."""

    path: Path
    base_ref: str | None
    line_count: int
    empty: bool


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def detect_default_base(cwd: Path) -> str:
    """Pick a sensible merge-base ref for offline review."""
    # Prefer upstream of current branch when set.
    upstream = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=cwd
    )
    if upstream.returncode == 0:
        ref = upstream.stdout.strip()
        if ref:
            return ref

    for name in _DEFAULT_BASES:
        for candidate in (f"origin/{name}", name):
            probe = _run_git(["rev-parse", "--verify", candidate], cwd=cwd)
            if probe.returncode == 0:
                return candidate

    # Last resort: empty tree vs HEAD (shows all commits as adds) — prefer HEAD^ if exists.
    parent = _run_git(["rev-parse", "--verify", "HEAD^"], cwd=cwd)
    if parent.returncode == 0:
        return "HEAD^"
    msg = (
        "could not detect a base branch (tried upstream, origin/main|master|develop, HEAD^). "
        "pass --base explicitly."
    )
    raise RuntimeError(msg)


def git_merge_base_diff(*, cwd: Path, base: str) -> str:
    """Return unified diff of working tree + commits since merge-base with ``base``.

    Uses ``git diff --merge-base <base>`` so uncommitted edits are included and
    base-branch noise is excluded (same form mergecraft-reviewer expects).
    """
    # Ensure base ref exists locally when it looks like origin/<name>.
    if base.startswith("origin/"):
        branch = base.removeprefix("origin/")
        fetch = _run_git(
            [
                "fetch",
                "--no-tags",
                "--depth",
                "200",
                "origin",
                f"{branch}:refs/remotes/origin/{branch}",
            ],
            cwd=cwd,
        )
        if fetch.returncode != 0:
            logger.warning("git fetch of {} failed (continuing): {}", base, fetch.stderr.strip())

    result = _run_git(["diff", "--merge-base", base], cwd=cwd)
    if result.returncode != 0:
        # Fallback: three-dot committed-only range.
        logger.warning(
            "git diff --merge-base {} failed ({}); trying three-dot range",
            base,
            result.stderr.strip() or result.returncode,
        )
        result = _run_git(["diff", f"{base}...HEAD"], cwd=cwd)
    if result.returncode != 0:
        msg = f"failed to compute diff against {base!r}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def materialize_diff(
    *,
    cwd: Path,
    out_dir: Path,
    base: str | None = None,
    diff_file: Path | None = None,
) -> DiffMaterialization:
    """Write the reviewable unified diff to ``out_dir/review.diff``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "review.diff"
    base_ref: str | None = None

    if diff_file is not None:
        text = diff_file.read_text(encoding="utf-8")
        base_ref = None
    else:
        base_ref = base or detect_default_base(cwd)
        text = git_merge_base_diff(cwd=cwd, base=base_ref)

    # Normalize trailing newline for stable line counts.
    if text and not text.endswith("\n"):
        text = f"{text}\n"
    path.write_text(text, encoding="utf-8")
    line_count = 0 if not text.strip() else text.count("\n")
    empty = not text.strip()
    logger.info(
        "» offline diff ready ({} lines{}) → {}",
        line_count,
        f", base={base_ref}" if base_ref else "",
        path,
    )
    return DiffMaterialization(path=path, base_ref=base_ref, line_count=line_count, empty=empty)


def summarize_diff(text: str) -> str:
    """Return a short TOC-like summary of changed paths in a unified diff."""
    paths: list[str] = []
    for line in text.splitlines():
        if line.startswith("diff --git "):
            # diff --git a/foo b/foo
            parts = line.split()
            if len(parts) >= 4:
                paths.append(parts[3].removeprefix("b/"))
    if not paths:
        return "(empty diff)"
    listed = "\n".join(f"- {p}" for p in paths)
    return f"{len(paths)} file(s) changed:\n{listed}"
