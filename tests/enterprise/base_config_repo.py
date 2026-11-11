"""Build a git checkout whose base commit and working tree carry different configs.

Shared by the enterprise and tracing suites to drive
:func:`mergecraft.enterprise.trusted_base.read_trusted_base` through a real
``git show <base>:.mergecraft/config.yaml``.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def make_pr_checkout(root: Path, *, base_config: str | None, head_config: str) -> str:
    """Create ``root`` with a base commit and a head working tree; return the base sha.

    Args:
        root: Directory to initialise (created if missing).
        base_config: ``.mergecraft/config.yaml`` text at the base commit, or ``None``
            for a base without the file.
        head_config: The config text left in the working tree (the PR head).

    Returns:
        str: The base commit sha.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    config_dir = root / ".mergecraft"
    config_dir.mkdir(exist_ok=True)
    (root / "README.md").write_text("base\n", encoding="utf-8")
    if base_config is not None:
        (config_dir / "config.yaml").write_text(base_config, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "--allow-empty", "-m", "base")
    base_sha = _git(root, "rev-parse", "HEAD")
    (config_dir / "config.yaml").write_text(head_config, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "--allow-empty", "-m", "head")
    return base_sha


def pull_request_event(base_sha: str, *, base_ref: str = "main") -> dict[str, Any]:
    """A minimal ``pull_request`` event payload naming ``base_sha``."""
    return {
        "pull_request": {
            "number": 7,
            "base": {"sha": base_sha, "ref": base_ref},
            "head": {"sha": "f" * 40, "ref": "feature"},
        }
    }


def write_event(path: Path, event: dict[str, Any]) -> Path:
    """Write ``event`` as a ``GITHUB_EVENT_PATH`` file and return the path."""
    path.write_text(json.dumps(event), encoding="utf-8")
    return path
