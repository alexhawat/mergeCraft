"""CI #487 — helpers for ``init`` gitignore scaffold of ``.mergecraft/audit.jsonl`` (D10).

Pins explicit ignore line in consumer ``.gitignore`` so enterprise audit JSONL
never appears as untracked local state after a review run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mergecraft.enterprise.audit import DEFAULT_AUDIT_REL

# D10: explicit line — not a broad ``/.mergecraft/*`` blanket for consumer repos.
AUDIT_JSONL_GITIGNORE_LINE = DEFAULT_AUDIT_REL.as_posix()


def audit_jsonl_rel_path() -> str:
    return DEFAULT_AUDIT_REL.as_posix()


def audit_jsonl_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_AUDIT_REL


def gitignore_path(repo_root: Path) -> Path:
    return repo_root / ".gitignore"


def gitignore_contains_audit_jsonl(repo_root: Path) -> bool:
    path = gitignore_path(repo_root)
    if not path.is_file():
        return False
    return AUDIT_JSONL_GITIGNORE_LINE in path.read_text(encoding="utf-8")


def git_check_ignores(repo_root: Path, rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        cwd=repo_root,
        capture_output=True,
    )
    return result.returncode == 0


def git_status_porcelain(repo_root: Path, rel_path: str) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", rel_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr or result.stdout or "git status failed"
        raise RuntimeError(msg)
    return result.stdout.strip()
