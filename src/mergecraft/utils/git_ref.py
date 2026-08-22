"""Git ref resolution helpers shared by scripts and tests."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_SHA_REF = re.compile(r"^[0-9a-f]{40}$")


def git_ref_exists(ref: str, *, cwd: Path | None = None) -> bool:
    """Return whether *ref* resolves as a tag, branch, or commit in the checkout."""
    ref = ref.rstrip("#").strip()
    workdir = cwd or Path(__file__).resolve().parents[2]
    candidates: list[list[str]]
    if _SHA_REF.fullmatch(ref):
        candidates = [["git", "rev-parse", "--verify", f"{ref}^{{commit}}"]]
    elif ref.startswith("v"):
        candidates = [["git", "rev-parse", "--verify", f"refs/tags/{ref}^{{commit}}"]]
    else:
        candidates = [
            ["git", "rev-parse", "--verify", f"refs/heads/{ref}^{{commit}}"],
            ["git", "rev-parse", "--verify", f"refs/remotes/origin/{ref}^{{commit}}"],
        ]
    for cmd in candidates:
        if subprocess.run(cmd, cwd=workdir, capture_output=True, check=False).returncode == 0:
            return True
    if not _SHA_REF.fullmatch(ref):
        return False
    # CI checkouts use fetch-depth: 1 — pinned SHAs may not be in the object db.
    fetch = subprocess.run(
        ["git", "fetch", "origin", ref, "--depth=1"],
        cwd=workdir,
        capture_output=True,
        check=False,
    )
    if fetch.returncode != 0:
        return False
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=workdir,
        capture_output=True,
        check=False,
    )
    return verify.returncode == 0
