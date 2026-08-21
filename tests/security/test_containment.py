"""Plan W3 — containment hardening (punch ``#10/#11/#12/#19``).

Contracts:

- Git hooks are disabled unless ``shell=enabled`` (W3.2) — proven with a real
  repo whose ``post-checkout`` hook writes a sentinel.
- ``cwd`` / ``working_directory`` escapes outside ``$GITHUB_WORKSPACE`` are
  rejected (W3.3).
- ``docker-entrypoint.sh`` scopes ``safe.directory`` instead of ``'*'`` (W3.1).
- Agent subprocesses drop to the unprivileged ``mergecraft`` user (W3.4) —
  pinned as a spawn-site contract so it fails if the privilege drop is
  deleted, without depending on the host's UID.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from mergecraft.mcp.shell import shell_tool
from mergecraft.utils.git_setup import setup_git
from tests.security.conftest import HOOK_SENTINEL, PlantedRepo
from tests.support.tool_context import write_capable_mcp_mode

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENTRYPOINT = _REPO_ROOT / "docker-entrypoint.sh"


def _checkout_branch(repo: Path, branch: str) -> None:
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _run_setup_git(planted_repo: PlantedRepo, shell: str, monkeypatch, tmp_path: Path) -> None:
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


def test_hooks_disabled_when_shell_disabled(
    planted_repo: PlantedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W3.2 — baseline cell: ``shell=disabled`` already null-routes hooks."""
    _run_setup_git(planted_repo, "disabled", monkeypatch, tmp_path)
    _checkout_branch(planted_repo.path, "attacker-branch")
    assert not planted_repo.sentinel.exists(), "post-checkout hook executed under shell=disabled"


def test_hooks_disabled_when_shell_restricted(
    planted_repo: PlantedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W3.2 — ``restricted`` must neutralize hooks exactly like ``disabled``.

    Fails if the guard is deleted: the planted hook fires on checkout and the
    sentinel appears.
    """
    _run_setup_git(planted_repo, "restricted", monkeypatch, tmp_path)
    _checkout_branch(planted_repo.path, "attacker-branch")
    assert not planted_repo.sentinel.exists(), (
        f"post-checkout hook executed under shell=restricted "
        f"(sentinel: {planted_repo.sentinel.read_text().strip()!r})"
    )


def test_hooks_allowed_only_when_shell_enabled(
    planted_repo: PlantedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W3.2 — control cell: ``enabled`` is documented as the only hooks-on mode."""
    _run_setup_git(planted_repo, "enabled", monkeypatch, tmp_path)
    _checkout_branch(planted_repo.path, "attacker-branch")
    assert planted_repo.sentinel.exists(), "control cell broken: hooks should run when enabled"
    assert HOOK_SENTINEL in planted_repo.sentinel.read_text()


@pytest.mark.parametrize(
    "escape_cwd",
    ["/etc", "..", "/", "/private/etc"],
    ids=["absolute-etc", "dotdot", "root", "alias-etc"],
)
async def test_shell_working_directory_escape_rejected(
    make_tool_ctx, escape_cwd: str, no_ci_env: None
) -> None:
    """W3.3/W4.4 — the shell tool refuses to run outside the workspace.

    Fails if the guard is deleted: the command would execute in the escape
    directory and the tool result would stop being an error.
    """
    ctx = make_tool_ctx(shell="restricted")
    tool = shell_tool(ctx)
    with write_capable_mcp_mode():
        result = await tool.execute(
            {"command": "pwd", "description": "probe cwd", "working_directory": escape_cwd}
        )
    assert result.is_error, f"cwd escape {escape_cwd!r} was executed: {result.content}"
    text = result.content[0]["text"]
    assert "working_directory" in text or "outside" in text or "not allowed" in text, (
        f"rejection must name the policy, got: {text!r}"
    )


async def test_shell_working_directory_symlink_escape_rejected(
    make_tool_ctx, tmp_path: Path, no_ci_env: None
) -> None:
    """W3.3 — a symlink inside the workspace pointing outside is still an escape."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    link = workspace / "innocent-looking"
    link.symlink_to("/etc", target_is_directory=True)
    ctx = make_tool_ctx(shell="restricted")
    tool = shell_tool(ctx)
    with write_capable_mcp_mode():
        result = await tool.execute(
            {"command": "pwd", "description": "probe cwd", "working_directory": str(link)}
        )
    assert result.is_error, f"symlink escape executed: {result.content}"


def test_entrypoint_safe_directory_has_no_wildcard() -> None:
    """W3.1 — ``safe.directory '*'`` must be gone from the entrypoint."""
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    assert "safe.directory '*'" not in text, (
        "docker-entrypoint.sh still trusts every path on the runner"
    )
    assert 'safe.directory "*"' not in text, (
        "docker-entrypoint.sh still trusts every path on the runner"
    )
    for match in re.finditer(r"safe\.directory\s+(\S+)", text):
        value = match.group(1).strip("'\"")
        assert value != "*", "wildcard safe.directory survived"
        assert "$GITHUB_WORKSPACE" in match.group(0) or value.startswith("/"), (
            f"safe.directory entry is not a scoped absolute path: {match.group(0)!r}"
        )


def test_agent_spawn_drops_privileges() -> None:
    """W3.4 — agent CLI spawns must carry a privilege-drop mechanism.

    Structural contract (host-independent): at least one agent spawn site or
    the entrypoint uses ``setpriv``/``runuser``/``su``/``setuid``/``user=`` to
    keep the agent from running as root. Fails if the drop is deleted.
    """
    agents_dir = _REPO_ROOT / "src" / "mergecraft" / "agents"
    spawn_sources = [p.read_text(encoding="utf-8") for p in agents_dir.glob("*.py")]
    entrypoint = _ENTRYPOINT.read_text(encoding="utf-8")
    drop_markers = ("setpriv", "runuser", "setuid", "seteuid", "gosu")
    found = any(marker in src for src in [*spawn_sources, entrypoint] for marker in drop_markers)
    if not found:
        # ``user=`` kwarg on Popen is the other acceptable shape.
        for src in spawn_sources:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Popen"
                    and any(kw.arg == "user" for kw in node.keywords)
                ):
                    found = True
    assert found, "no privilege-drop mechanism at any agent spawn site or entrypoint"
