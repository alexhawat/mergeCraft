"""A tiny in-memory Git history answering the GitHub reads a re-approval makes.

Commits are whole snapshots (path -> text and mode). The compare API is computed from
them with real unified-diff patches, Git trees are synthesised per directory, and the
merge base of each comparison is declared by the scenario, so a test describes a
history the way a reader would: a base, a reviewed head, an upstream change, a merge.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
from dataclasses import dataclass, field
from typing import Any

from mergecraft.scm.types import ListedItems

OWNER = "acme"
REPO = "demo"
PULL = 7
REVIEWER_APP = "mergecraft-reviewer"
PRIOR_RUN_URL = "https://github.com/acme/demo/actions/runs/42697047477"

File = tuple[str, str]  # (text, mode)


def sha_of(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()  # synthetic ids, not security


def _blob(text: str) -> str:
    return hashlib.sha1(f"blob:{text}".encode()).hexdigest()  # synthetic ids


def _patch(before: str, after: str) -> str:
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=3)
    return "\n".join(list(lines)[2:])


@dataclass
class Repo:
    """Snapshots by commit SHA, declared merge bases and the PR's GitHub state."""

    commits: dict[str, dict[str, File]] = field(default_factory=dict)
    merge_bases: dict[tuple[str, str], str] = field(default_factory=dict)
    base_sha: str = ""
    base_ref: str = "main"
    head_sha: str = ""
    check_runs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    trees: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    def commit(self, label: str, files: dict[str, File]) -> str:
        sha = sha_of(label)
        self.commits[sha] = dict(files)
        self._index_trees(sha, files)
        return sha

    def _index_trees(self, commit: str, files: dict[str, File]) -> None:
        directories: dict[str, dict[str, dict[str, Any]]] = {"": {}}
        for path in files:
            parts = path.split("/")
            for depth in range(1, len(parts)):
                directories.setdefault("/".join(parts[:depth]), {})
        for path, (text, mode) in files.items():
            parent, _, name = path.rpartition("/")
            directories[parent][name] = {
                "path": name,
                "mode": mode,
                "type": "blob",
                "sha": _blob(text),
            }

        def tree_sha(directory: str) -> str:
            listing = sorted((row["path"], row["sha"]) for row in directories[directory].values())
            return hashlib.sha1(repr(listing).encode()).hexdigest()  # synthetic ids

        # Children before parents, so a parent's entry carries its child's tree id.
        for directory in sorted(directories, key=lambda d: -d.count("/") if d else 1):
            if not directory:
                continue
            parent, _, name = directory.rpartition("/")
            directories[parent][name] = {
                "path": name,
                "mode": "040000",
                "type": "tree",
                "sha": tree_sha(directory),
            }
        for directory, rows in directories.items():
            key = commit if not directory else tree_sha(directory)
            self.trees[key] = list(rows.values())

    def compare(self, base: str, head: str) -> dict[str, Any]:
        merge_base = base if base == head else self.merge_bases[(base, head)]
        before, after = self.commits[merge_base], self.commits[head]
        files: list[dict[str, Any]] = []
        for path in sorted(set(before) | set(after)):
            old, new = before.get(path), after.get(path)
            if old == new:
                continue
            old_text = old[0] if old else ""
            new_text = new[0] if new else ""
            status = "added" if old is None else "removed" if new is None else "modified"
            patch = _patch(old_text, new_text)
            files.append(
                {
                    "filename": path,
                    "status": status,
                    "sha": _blob(new_text if new else old_text),
                    "additions": sum(1 for ln in patch.splitlines() if ln.startswith("+")),
                    "deletions": sum(1 for ln in patch.splitlines() if ln.startswith("-")),
                    **({"patch": patch} if patch else {}),
                }
            )
        return {"merge_base_commit": {"sha": merge_base}, "status": "ahead", "files": files}

    # ── ScmProvider surface ──────────────────────────────────────────────────

    async def get(self, path: str, params: dict[str, Any] | None = None, **_kw: Any) -> Any:
        self.requests.append(path)
        root = f"/repos/{OWNER}/{REPO}"
        assert path.startswith(root), path
        rest = path[len(root) :]
        if rest == f"/pulls/{PULL}":
            return {
                "state": "open",
                "head": {"sha": self.head_sha},
                "base": {"sha": self.base_sha, "ref": self.base_ref},
            }
        if rest.startswith("/compare/"):
            base, _, head = rest.removeprefix("/compare/").partition("...")
            return self.compare(base, head)
        if rest.startswith("/git/trees/"):
            sha = rest.removeprefix("/git/trees/")
            return {"sha": sha, "tree": self.trees[sha], "truncated": False}
        if rest.startswith("/contents/"):
            name = rest.removeprefix("/contents/")
            ref = (params or {}).get("ref")
            text = self.commits[str(ref)][name][0]
            return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
        msg = f"unexpected read {path}"
        raise AssertionError(msg)

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **_kwargs: Any
    ) -> ListedItems:
        self.requests.append(f"checks:{ref}")
        return ListedItems(items=self.check_runs.get(ref, []), incomplete=False)


def approval_check(
    head: str,
    summary: str,
    *,
    conclusion: str = "success",
    app: str = REVIEWER_APP,
    check_id: int = 101,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": "mergecraft-approval",
        "head_sha": head,
        "status": "completed",
        "conclusion": conclusion,
        "app": {"slug": app},
        "details_url": PRIOR_RUN_URL,
        "output": {"title": "mergeCraft would approve", "summary": summary},
    }


def review(commit: str) -> dict[str, Any]:
    return {"commit_id": commit, "body": "*via mergecraft*", "user": {"login": "rev[bot]"}}
