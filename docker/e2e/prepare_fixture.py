#!/usr/bin/env python3
"""Prepare an isolated, real Git PR and matching event for image/host tests."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def prepare(work: Path, event_name: str, *, container: bool = True) -> dict[str, Any]:
    """Build a base/head pair whose local origin serves refs/pull/N/head."""
    workspace = work / "workspace"
    shutil.copytree(FIXTURES / "repo", workspace)
    for directory in ("runner-temp", "github"):
        (work / directory).mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=workspace, text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "e2e@example.com")
    git("config", "user.name", "E2E")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-q", "-b", "feature/e2e-fixture")
    readme = workspace / "README.md"
    readme.write_text(
        readme.read_text().replace(
            "# E2E fixture repo\n",
            "# E2E fixture repo\n\nFixture update validated through MCP.\n",
            1,
        )
    )
    git("add", "README.md")
    git("commit", "-q", "-m", "fixture head")
    head = git("rev-parse", "HEAD")
    event: dict[str, Any] = json.loads((FIXTURES / "events" / f"{event_name}.json").read_text())
    pull = event["pull_request"]
    pull["head"]["sha"], pull["base"]["sha"] = head, base
    pull["body"] = "Fixture review.\n\nScope paths:\n- README.md\n"
    diff = git("diff", base, head, "--", "README.md")
    event["_e2e_files"] = [
        {
            "filename": "README.md",
            "status": "modified",
            "additions": 2,
            "deletions": 0,
            "patch": "@@" + diff.split("@@", 1)[1],
        }
    ]
    # A self-contained local origin keeps the image fixture inside the workspace
    # already registered by the production entrypoint as a safe Git directory.
    git("update-ref", f"refs/pull/{pull['number']}/head", head)
    git("checkout", "-q", "main")
    git("remote", "add", "origin", "/github/workspace" if container else str(workspace))
    (work / "github" / "event.json").write_text(json.dumps(event))
    for name in ("output", "state"):
        (work / "github" / name).write_text("")
    return event


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--event", choices=("pull_request", "pull_request_target"), required=True)
    args = parser.parse_args()
    prepare(args.work_dir, args.event)
