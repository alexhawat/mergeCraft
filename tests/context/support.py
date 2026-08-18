"""Shared helpers for context engine tests (DG3.1 RED)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tests.analyzers.support import import_module

REPO_INSTRUCTIONS_HEADER = "************* REPO INSTRUCTIONS *************"
STANDING_INSTRUCTIONS_HEADER = "************* STANDING INSTRUCTIONS *************"
FENCE_OPEN = "<<<UNTRUSTED-MERGECRAFT-CONTENT"


def import_context_module(name: str) -> Any:
    """Lazy import for ``mergecraft.context.*`` symbols."""
    return import_module(f"mergecraft.context.{name}")


def git_run(*args: str, cwd: Path) -> str:
    """Run a git command and return stripped stdout."""
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def git_init_repo(root: Path) -> None:
    """Initialize a git repo with an initial commit."""
    root.mkdir(parents=True, exist_ok=True)
    git_run("init", cwd=root)
    git_run("-c", "user.email=test@example.com", "-c", "user.name=Test User", "add", "-A", cwd=root)


def git_commit_all(root: Path, message: str = "init") -> str:
    """Commit all tracked files and return the commit SHA."""
    git_run(
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test User",
        "add",
        "-A",
        cwd=root,
    )
    git_run(
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test User",
        "commit",
        "-m",
        message,
        cwd=root,
    )
    return git_run("rev-parse", "HEAD", cwd=root)


def git_tree_sha(root: Path, ref: str = "HEAD") -> str:
    """Return the tree object SHA for ``ref``."""
    return git_run("rev-parse", f"{ref}^{{tree}}", cwd=root)


def git_blob_sha(root: Path, rel_path: str, ref: str = "HEAD") -> str:
    """Return the blob object SHA for ``rel_path`` at ``ref``."""
    return git_run("rev-parse", f"{ref}:{rel_path}", cwd=root)


def write_context_fixture_repo(root: Path) -> None:
    """Lay down a miniature repo for map + symbol indexing tests."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[project.scripts]\n'
        'demo-cli = "myservice.cli:main"\n',
        encoding="utf-8",
    )
    (root / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    (root / "src" / "myservice").mkdir(parents=True)
    (root / "src" / "myservice" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "myservice" / "cli.py").write_text(
        "def main() -> None:\n    run_service()\n\ndef run_service() -> None:\n    return None\n",
        encoding="utf-8",
    )
    (root / "services" / "api").mkdir(parents=True)
    (root / "services" / "api" / "main.py").write_text(
        "def handle_request() -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )


class RecordingCache:
    """In-memory cache that records get/set calls for cache-key assertions."""

    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.set_calls: list[str] = []
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        self.get_calls.append(key)
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self.set_calls.append(key)
        self._store[key] = value


def section_text(prompt: str, header: str) -> str:
    """Return the body of a prompt section up to the next banner header."""
    if header not in prompt:
        return ""
    start = prompt.index(header) + len(header)
    rest = prompt[start:].lstrip("\n")
    next_banner = rest.find("************* ")
    if next_banner == -1:
        return rest
    return rest[:next_banner]


def fenced_blocks(prompt: str) -> list[str]:
    """Return every UNTRUSTED-MERGECRAFT-CONTENT fence block in ``prompt``."""
    blocks: list[str] = []
    cursor = 0
    while True:
        open_idx = prompt.find(FENCE_OPEN, cursor)
        if open_idx == -1:
            break
        close_marker = "<<<END-UNTRUSTED-MERGECRAFT-CONTENT"
        close_idx = prompt.find(close_marker, open_idx)
        if close_idx == -1:
            break
        end = prompt.find("\n", close_idx)
        blocks.append(prompt[open_idx : end if end != -1 else len(prompt)])
        cursor = close_idx + len(close_marker)
    return blocks
