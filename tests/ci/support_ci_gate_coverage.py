"""Shared helpers for wave 16 — coverage delta gate contracts."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping

_BASE_MEASURE_MARKER = "BASE_WORKTREE_MEASURE_BLOCK"
_BASE_MEASURE_BLOCK_RE = re.compile(
    rf"#.*{re.escape(_BASE_MEASURE_MARKER)}.*\n\(\s*\n(.*?)^\)",
    re.MULTILINE | re.DOTALL,
)
_SCRIPT_PATH = REPO_ROOT / "scripts" / "ci_coverage_delta_gate.sh"
_WORKTREE_SUFFIX = ".ci-mergecraft-base-coverage"


def script_text() -> str:
    return _SCRIPT_PATH.read_text(encoding="utf-8")


def base_measure_block(text: str | None = None) -> str:
    source = text if text is not None else script_text()
    match = _BASE_MEASURE_BLOCK_RE.search(source)
    if match is None:
        msg = f"{_BASE_MEASURE_MARKER} block missing from ci_coverage_delta_gate.sh"
        raise AssertionError(msg)
    return match.group(1)


def worktree_path(repo_root: Path) -> Path:
    return repo_root / _WORKTREE_SUFFIX


def clone_local_repo(tmp_path: Path) -> Path:
    """Clone the checkout under test into an isolated scratch repo."""
    dest = tmp_path / "scratch"
    subprocess.run(
        ["git", "clone", "--local", str(REPO_ROOT), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def install_bare_origin(scratch: Path, tmp_path: Path) -> None:
    """Point *scratch*'s ``origin`` at a local bare repo with current branches."""
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "--bare", str(scratch), str(bare)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(scratch, "remote", "set-url", "origin", str(bare))
    branch = git(scratch, "rev-parse", "--abbrev-ref", "HEAD")
    git(scratch, "push", "-u", "origin", branch)


def break_coverage_measure(makefile: Path) -> None:
    text = makefile.read_text(encoding="utf-8")
    if "ci-gate-break-measure" in text:
        return
    match = re.search(r"^(coverage-measure:.*\n)((?:\t.*\n)+)", text, flags=re.MULTILINE)
    if match is None:
        msg = "Makefile is missing a coverage-measure target"
        raise AssertionError(msg)
    replacement = f"{match.group(1)}\t@echo ci-gate-break-measure >&2\n\t@exit 1\n"
    patched = text[: match.start()] + replacement + text[match.end() :]
    makefile.write_text(patched, encoding="utf-8")


def run_coverage_delta_gate(
    repo_root: Path,
    *,
    base_ref: str,
    extra_env: Mapping[str, str] | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_BASE_REF": base_ref,
            "GITHUB_WORKSPACE": str(repo_root),
            "CI": "true",
        }
    )
    if extra_env:
        env.update(dict(extra_env))
    return subprocess.run(
        ["bash", str(_SCRIPT_PATH)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


__all__ = [
    "base_measure_block",
    "break_coverage_measure",
    "clone_local_repo",
    "git",
    "install_bare_origin",
    "run_coverage_delta_gate",
    "script_text",
    "worktree_path",
]
