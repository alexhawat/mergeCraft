"""In-image proof that the namespace shell drops root identity after its masks.

Only meaningful on the privileged Linux backend the action image provides: the
MCP shell mounts its masks inside a namespace and then runs the requested
command. These tests assert the command's *identity* and *mount state* — UID,
effective capabilities, and the read-only ``.git`` bind — never an escape
payload. On a host without euid 0, Linux, ``unshare`` and ``setpriv`` the whole
module skips with the precondition reason; it runs as root inside the image.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT_PRECONDITION_REASON = "requires euid 0, Linux, unshare and setpriv — runs in the action image"


def _preconditions_met() -> bool:
    if sys.platform != "linux" or os.geteuid() != 0:
        return False
    return shutil.which("unshare") is not None and shutil.which("setpriv") is not None


pytestmark = pytest.mark.skipif(not _preconditions_met(), reason=_ROOT_PRECONDITION_REASON)


def _run_in_shell(command: str, *, cwd: Path) -> str:
    """Spawn the real namespace shell and return its combined output."""
    from mergecraft.mcp import shell as shell_mod

    shell_mod.reset_detection_cache()
    proc = shell_mod._spawn_shell(
        command,
        env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": "/tmp"},
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        isolate_network=False,
    )
    stdout, _ = proc.communicate(timeout=60)
    return (stdout or b"").decode("utf-8", errors="replace")


def test_shell_payload_runs_unprivileged_with_no_effective_capabilities(
    tmp_path: Path,
) -> None:
    """The command reports a non-root UID and an empty capability set."""
    output = _run_in_shell("id -u; grep CapEff /proc/self/status", cwd=tmp_path)
    uid_lines = [line.strip() for line in output.splitlines() if line.strip().isdigit()]
    assert uid_lines, output
    assert uid_lines[0] != "0", output
    assert "CapEff:" in output, output
    capability_line = next(
        line for line in output.splitlines() if line.strip().startswith("CapEff:")
    )
    assert capability_line.split(":", 1)[1].strip() == "0000000000000000", output


def test_shell_cannot_write_the_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read-only ``.git`` bind still holds against a dropped payload."""
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))

    output = _run_in_shell(
        "touch .git/uid-drop-probe 2>&1 && echo GIT_WRITE_OK || echo GIT_WRITE_DENIED",
        cwd=repo,
    )
    assert "GIT_WRITE_OK" not in output, output
    assert "GIT_WRITE_DENIED" in output or "Read-only file system" in output, output
    assert not (git_dir / "uid-drop-probe").exists()


def test_shell_cannot_read_a_root_only_file(tmp_path: Path) -> None:
    """A root-owned ``0600`` file stays unreadable to the dropped payload."""
    secret_dir = Path(tempfile.mkdtemp(dir="/tmp"))
    os.chmod(secret_dir, 0o755)
    try:
        secret = secret_dir / "root-only.txt"
        secret.write_text("root-only-secret", encoding="utf-8")
        os.chmod(secret, 0o600)

        output = _run_in_shell(
            f"cat {secret} 2>&1 && echo READ_OK || echo READ_DENIED",
            cwd=tmp_path,
        )
        assert "READ_OK" not in output, output
        assert "READ_DENIED" in output or "Permission denied" in output, output
    finally:
        shutil.rmtree(secret_dir, ignore_errors=True)
