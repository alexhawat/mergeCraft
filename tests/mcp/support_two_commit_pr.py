"""Recording two-commit PR fixture for commit-info scope tests (RA1.6).

Commit 1 touches ``security.py``; commit 2 touches ``docs.md``. The full PR
diff covers both files; each ``get_commit`` returns only its own commit's patch.
The recording SCM lets a test prove which commit the inspection tool saw without
touching the network.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

_FIRST_SHA = "1" * 40
_HEAD_SHA = "2" * 40

_FIRST_HUNK = "@@ -1,3 +1,4 @@\n def check(user):\n+    assert user is not None\n     return user\n"
_HEAD_HUNK = "@@ -1 +1,2 @@\n # Docs\n+new line\n"


@dataclass
class RecordingScm:
    """Minimal SCM stub recording every ``get_commit`` / ``get_pull`` call."""

    pulls: dict[int, dict[str, Any]]
    commits: dict[str, dict[str, Any]]
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def get_commit(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        self.calls.append(("get_commit", sha))
        return copy.deepcopy(self.commits[sha])

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        self.calls.append(("get_pull", str(pull_number)))
        return copy.deepcopy(self.pulls[pull_number])


@dataclass
class TwoCommitPR:
    """Fixture bundle for one two-commit pull request."""

    root: Any
    pr_diff_path: Any
    first_sha: str
    head_sha: str
    scm: RecordingScm
    pr_number: int = 1

    def pr_diff_text(self) -> str:
        return self.pr_diff_path.read_text(encoding="utf-8")


def _commit_payload(sha: str, filename: str, hunk: str) -> dict[str, Any]:
    return {
        "sha": sha,
        "commit": {"message": f"change {filename}", "author": {"date": "2026-09-01T00:00:00Z"}},
        "author": {"login": "dev"},
        "committer": {"login": "dev"},
        "html_url": f"https://example.test/commit/{sha}",
        "parents": [],
        "stats": {"additions": 1, "deletions": 0, "total": 1},
        "files": [{"filename": filename, "patch": hunk}],
    }


def _diff_header(filename: str, hunk: str) -> str:
    return f"diff --git a/{filename} b/{filename}\n--- a/{filename}\n+++ b/{filename}\n{hunk}"


def build_two_commit_pr(tmp_path: Any) -> TwoCommitPR:
    """Build a disposable two-commit PR with a recording SCM."""
    pr_diff_path = tmp_path / "pr.diff"
    pr_diff_path.write_text(
        _diff_header("security.py", _FIRST_HUNK) + _diff_header("docs.md", _HEAD_HUNK),
        encoding="utf-8",
    )
    scm = RecordingScm(
        pulls={
            1: {
                "head": {"ref": "feature", "sha": _HEAD_SHA},
                "base": {"ref": "main", "sha": _FIRST_SHA},
                "title": "Two-commit change",
                "html_url": "https://example.test/pull/1",
            }
        },
        commits={
            _FIRST_SHA: _commit_payload(_FIRST_SHA, "security.py", _FIRST_HUNK),
            _HEAD_SHA: _commit_payload(_HEAD_SHA, "docs.md", _HEAD_HUNK),
        },
    )
    return TwoCommitPR(
        root=tmp_path,
        pr_diff_path=pr_diff_path,
        first_sha=_FIRST_SHA,
        head_sha=_HEAD_SHA,
        scm=scm,
    )


__all__ = ["RecordingScm", "TwoCommitPR", "build_two_commit_pr"]
