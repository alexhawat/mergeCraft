"""Shared helpers for the ``tests/docs`` contract suite (#405)."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path
from types import ModuleType

from tests.ci.workflow_support import REPO_ROOT

_SHA_REF = re.compile(r"^[0-9a-f]{40}$")

action_uses_pattern = re.compile(
    r"uses:\s*alexhawat/mergeCraft@(\S+)",
    re.IGNORECASE,
)


def git_ref_exists(ref: str) -> bool:
    """Return whether *ref* resolves as a tag, branch, or commit in this checkout."""
    ref = ref.rstrip("#").strip()
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
        if subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, check=False).returncode == 0:
            return True
    if not _SHA_REF.fullmatch(ref):
        return False
    # CI checkouts use fetch-depth: 1 — pinned SHAs may not be in the object db.
    fetch = subprocess.run(
        ["git", "fetch", "origin", ref, "--depth=1"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if fetch.returncode != 0:
        return False
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return verify.returncode == 0


def ci_steps() -> list[str]:
    """Return Makefile ``CI_STEPS`` tokens."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^CI_STEPS\s*:?=\s*(.+)$", makefile, re.MULTILINE)
    assert match, "Makefile missing CI_STEPS"
    return match.group(1).split()


def load_script_module(path: str | Path) -> ModuleType:
    """Load a repo script by absolute or repo-relative path."""
    script = Path(path)
    if not script.is_absolute():
        script = REPO_ROOT / script
    assert script.is_file(), f"missing {script.relative_to(REPO_ROOT)}"
    module_name = f"mergecraft_docs_support_{script.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        msg = f"could not load {script}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
