"""Resolve a local unified diff for offline ``mergecraft diff-review``."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from mergecraft.utils.git_hardening import git_argv

_DEFAULT_BASES = ("main", "master", "develop", "trunk")
_MAX_UNTRACKED_FILE_BYTES = 256 * 1024


@dataclass(slots=True)
class DiffMaterialization:
    """Result of writing a reviewable unified diff to disk."""

    path: Path
    base_ref: str | None
    line_count: int
    empty: bool
    #: Working-tree paths the default materialization deliberately left out
    #: (gitignored, oversized, binary, symlink, non-UTF-8). Carried on the
    #: result so an empty diff can never silently read as "nothing to review"
    #: (D11/D12) — the exclusion is visible, not just a log line.
    coverage_limitations: tuple[str, ...] = ()


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout_s: float | None = None,
) -> subprocess.CompletedProcess[str]:
    if timeout_s is None:
        from mergecraft.utils.run_bounds import timeout_for_external_operation

        timeout_s = timeout_for_external_operation("git_diff")
    return subprocess.run(
        git_argv(args),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def detect_default_base(cwd: Path, *, git_dir: Path | None = None) -> str:
    """Pick a sensible merge-base ref for offline review."""
    _ = git_dir  # reserved for worktree callers; git discovers metadata from ``cwd``.
    # Prefer upstream of current branch when set.
    upstream = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=cwd,
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


def git_merge_base_diff(
    *,
    cwd: Path,
    base: str,
    git_dir: Path | None = None,
) -> str:
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
        msg = f"failed to compute diff against {base!r}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def git_ref_diff(
    *,
    cwd: Path,
    base: str,
    head: str,
    git_dir: Path | None = None,
) -> str:
    """Return unified diff between ``base`` and ``head``."""
    _ = git_dir
    resolved_base = base
    probe = _run_git(["rev-parse", "--verify", base], cwd=cwd)
    if probe.returncode != 0 and not base.startswith("origin/"):
        candidate = f"origin/{base}"
        origin_probe = _run_git(["rev-parse", "--verify", candidate], cwd=cwd)
        if origin_probe.returncode == 0:
            resolved_base = candidate
    result = _run_git(["diff", f"{resolved_base}...{head}"], cwd=cwd)
    if result.returncode != 0:
        msg = (
            f"failed to compute diff {base!r}...{head!r}: {result.stderr.strip()}. "
            "Fetch sufficient shared history before retrying; endpoint comparison is not equivalent."
        )
        raise RuntimeError(msg)
    return result.stdout


def git_staged_diff(*, cwd: Path) -> str:
    """Return staged diff via ``git diff --cached``."""
    result = _run_git(["diff", "--cached"], cwd=cwd)
    if result.returncode != 0:
        msg = f"failed to compute staged diff: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def _nul_paths(data: str) -> list[str]:
    """Split a NUL-delimited ``git ls-files -z`` listing into paths."""
    return [item for item in data.split("\0") if item]


def _ignored_limitations(cwd: Path, *, already_seen: set[str]) -> list[str]:
    """Return limitations for gitignored working-tree paths.

    ``--exclude-standard`` hides ignored files from the eligible listing, so
    they would otherwise disappear without a trace. ``--directory`` collapses
    a fully-ignored directory (e.g. ``.venv/``) to one entry so the report
    stays readable in a large checkout.
    """
    ignored = _run_git(
        ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
        cwd=cwd,
    )
    if ignored.returncode != 0:
        return []
    return [
        f"gitignored path not reviewed: {rel}"
        for rel in _nul_paths(ignored.stdout)
        if rel not in already_seen
    ]


def _discover_untracked_additions(
    cwd: Path,
    *,
    report_ignored: bool = False,
) -> tuple[str, tuple[str, ...]]:
    """Return unified patches for eligible untracked files and their exclusions.

    This is the discovery half of :func:`git_unstaged_diff`, reused by the
    default ``--merge-base`` materialization (D11). A file that is skipped —
    symlink, oversized, binary, non-UTF-8 — is returned as a coverage
    limitation as well as logged; gitignored paths are reported when
    ``report_ignored`` is set (they never reach the eligible listing).
    """
    listing = _run_git(["ls-files", "--others", "--exclude-standard", "-z"], cwd=cwd)
    patches: list[str] = []
    limitations: list[str] = []
    eligible: set[str] = set()
    if listing.returncode == 0:
        for rel in _nul_paths(listing.stdout):
            eligible.add(rel)
            path = cwd / rel
            if path.is_symlink():
                limitations.append(f"symlink not reviewed: {rel}")
                continue
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                limitations.append(f"unreadable file not reviewed: {rel}")
                continue
            if len(raw) > _MAX_UNTRACKED_FILE_BYTES:
                logger.info("skipped oversized untracked file in unstaged diff: {}", rel)
                limitations.append(f"oversized file not reviewed: {rel}")
                continue
            if b"\0" in raw:
                logger.info("skipped binary untracked file in unstaged diff: {}", rel)
                limitations.append(f"binary file not reviewed: {rel}")
                continue
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                logger.info("skipped non-UTF-8 untracked file in unstaged diff: {}", rel)
                limitations.append(f"non-UTF-8 file not reviewed: {rel}")
                continue
            patch = _run_git(["diff", "--no-index", "--", "/dev/null", rel], cwd=cwd)
            if patch.returncode not in (0, 1):
                msg = f"failed to compute untracked diff for {rel!r}: {patch.stderr.strip()}"
                raise RuntimeError(msg)
            patches.append(patch.stdout)
    if report_ignored:
        limitations.extend(_ignored_limitations(cwd, already_seen=eligible))
    return "".join(patches), tuple(limitations)


def git_unstaged_diff(*, cwd: Path) -> str:
    """Return unstaged working-tree diff (tracked edits plus untracked adds)."""
    result = _run_git(["diff"], cwd=cwd)
    if result.returncode != 0:
        msg = f"failed to compute unstaged diff: {result.stderr.strip()}"
        raise RuntimeError(msg)
    untracked_text, _ = _discover_untracked_additions(cwd)
    return result.stdout + untracked_text


def git_range_diff(*, cwd: Path, range_spec: str) -> str:
    """Return unified diff for an explicit ``left..right`` range."""
    result = _run_git(["diff", range_spec], cwd=cwd)
    if result.returncode != 0:
        msg = f"failed to compute diff for range {range_spec!r}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def materialize_diff(
    *,
    cwd: Path,
    out_dir: Path,
    base: str | None = None,
    diff_file: Path | None = None,
    git_dir: Path | None = None,
) -> DiffMaterialization:
    """Write the reviewable unified diff to ``out_dir/review.diff``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "review.diff"
    base_ref: str | None = None
    coverage_limitations: tuple[str, ...] = ()

    if diff_file is not None:
        text = diff_file.read_text(encoding="utf-8")
        base_ref = None
    else:
        base_ref = base or detect_default_base(cwd, git_dir=git_dir)
        text = git_merge_base_diff(cwd=cwd, base=base_ref, git_dir=git_dir)
        # ``--merge-base`` never lists untracked files by construction, so a new
        # source file would otherwise be invisible to the default review (N7/D11).
        if text and not text.endswith("\n"):
            text = f"{text}\n"
        untracked_text, coverage_limitations = _discover_untracked_additions(
            cwd,
            report_ignored=True,
        )
        text += untracked_text

    # Normalize trailing newline for stable line counts.
    if text and not text.endswith("\n"):
        text = f"{text}\n"
    path.write_text(text, encoding="utf-8")
    line_count = 0 if not text.strip() else text.count("\n")
    empty = not text.strip()
    logger.info(
        "» offline diff ready ({} lines{}{}) → {}",
        line_count,
        f", base={base_ref}" if base_ref else "",
        f", {len(coverage_limitations)} coverage limitation(s)" if coverage_limitations else "",
        path,
    )
    return DiffMaterialization(
        path=path,
        base_ref=base_ref,
        line_count=line_count,
        empty=empty,
        coverage_limitations=coverage_limitations,
    )


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
