"""Plan W4.4 - containment-escape attempts across the ``shell x push`` matrix.

Hooks execution, ``safe.directory`` wildcard, and ``cwd`` escapes - each run
per matrix cell so a future regression cannot hide behind one configuration.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from mergecraft.mcp.shell import shell_tool
from mergecraft.utils.git_setup import setup_git
from tests.security.conftest import PUSH_MODES, SHELL_MODES, PlantedRepo

CELLS = [(s, p) for s in SHELL_MODES for p in PUSH_MODES]
CELL_IDS = [f"shell-{s}__push-{p}" for s in SHELL_MODES for p in PUSH_MODES]

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _hooks_executed(planted_repo: PlantedRepo, shell: str, monkeypatch, tmp_path: Path) -> bool:
    """Run real ``setup_git`` for the cell, then trigger the planted hook."""
    from mergecraft.mcp.tool_state import init_tool_state

    monkeypatch.chdir(planted_repo.path)
    state = init_tool_state(owner="acme", name="demo", dir=str(planted_repo.path))
    setup_git(
        git_token="ghs_secret_token",
        owner="acme",
        name="demo",
        tool_state=state,
        shell=shell,
        tmpdir=str(tmp_path),
    )
    subprocess.run(
        ["git", "checkout", "-b", "hook-probe"],
        cwd=planted_repo.path,
        capture_output=True,
        text=True,
        check=True,
    )
    return planted_repo.sentinel.exists()


_HOOKS_RESTRICTED_CELLS = [("restricted", p) for p in PUSH_MODES]
_HOOKS_DISABLED_CELLS = [("disabled", p) for p in PUSH_MODES]


@pytest.mark.parametrize(
    ("shell", "push"),
    _HOOKS_RESTRICTED_CELLS,
    ids=[f"shell-{s}__push-{p}" for s, p in _HOOKS_RESTRICTED_CELLS],
)
def test_hooks_never_execute_unless_shell_enabled(
    planted_repo: PlantedRepo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shell: str,
    push: str,
) -> None:
    """W4.4 — PR-authored git hooks must not fire in ``restricted``.

    Fails if the guard is deleted: the planted ``post-checkout`` hook writes
    its sentinel and the assertion turns red. The ``shell=enabled`` control
    cell lives in ``test_containment.py``.
    """
    executed = _hooks_executed(planted_repo, shell, monkeypatch, tmp_path)
    assert not executed, f"post-checkout hook executed under shell={shell}"


@pytest.mark.parametrize(
    ("shell", "push"),
    _HOOKS_DISABLED_CELLS,
    ids=[f"shell-{s}__push-{p}" for s, p in _HOOKS_DISABLED_CELLS],
)
def test_hooks_never_execute_when_shell_disabled(
    planted_repo: PlantedRepo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shell: str,
    push: str,
) -> None:
    """W4.4 — existing invariant pinned plain: hooks are off under ``disabled``.

    Guards the guard: a regression that re-enables hooks here turns red
    immediately, without waiting for the W3 flip.
    """
    executed = _hooks_executed(planted_repo, shell, monkeypatch, tmp_path)
    assert not executed, f"post-checkout hook executed under shell={shell}"


@pytest.mark.parametrize("push", PUSH_MODES, ids=[f"push-{p}" for p in PUSH_MODES])
async def test_working_directory_escapes_rejected(
    make_tool_ctx, push: str, no_ci_env: None, tmp_path: Path
) -> None:
    """W4.4 — ``..``, absolute system paths, and workspace-relative escapes."""
    ctx = make_tool_ctx(shell="restricted", push=push)
    tool = shell_tool(ctx)
    workspace = Path(os.environ.get("GITHUB_WORKSPACE") or tmp_path)
    escapes = [
        "..",
        str(workspace.parent.parent),
        "/etc",
        str(workspace / ".." / ".." / ".."),
    ]
    for escape in escapes:
        result = await tool.execute(
            {"command": "pwd", "description": "cwd escape attempt", "working_directory": escape}
        )
        assert result.is_error, f"cwd escape {escape!r} executed under push={push}"


@pytest.mark.parametrize("push", PUSH_MODES, ids=[f"push-{p}" for p in PUSH_MODES])
async def test_working_directory_inside_workspace_accepted(
    make_tool_ctx, push: str, no_ci_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W4.4 happy path — a real subdirectory of the workspace keeps working."""
    workspace = tmp_path / "workspace"
    subdir = workspace / "pkg" / "mod"
    subdir.mkdir(parents=True)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    ctx = make_tool_ctx(shell="restricted", push=push)
    tool = shell_tool(ctx)
    result = await tool.execute(
        {"command": "pwd", "description": "in-workspace cwd", "working_directory": str(subdir)}
    )
    assert not result.is_error, f"legitimate cwd rejected: {result.content}"


@pytest.mark.parametrize(("shell", "push"), CELLS, ids=CELL_IDS)
def test_safe_directory_wildcard_absent(shell: str, push: str) -> None:
    """W4.4 — the entrypoint must not pre-trust every path on the runner.

    Parametrized over the full ``shell x push`` matrix: a wildcard
    ``safe.directory`` undermines containment in every cell.
    """
    text = (_REPO_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    wildcards = [m.group(0) for m in re.finditer(r"safe\.directory\s+['\"]?\*['\"]?", text)]
    assert not wildcards, (
        f"wildcard safe.directory entries under shell={shell} push={push}: {wildcards}"
    )
