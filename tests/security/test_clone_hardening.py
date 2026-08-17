"""TS3 — third-party clone hardening (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins D5 (token never in clone URL / on disk), D6 (shallow bounded clone, no
submodule recursion), D7 (symlink and path containment), and D10 (clear auth
errors). Authoring wave: **TS3.1** (RED). Implementation: **TS3.2**.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.analyzers.support import import_module


def _source_resolve_mod() -> Any:
    return import_module("mergecraft.utils.source_resolve")


def _review_source(*, url: str, ref: str = "main", token: str | None = None) -> Any:
    mod = _source_resolve_mod()
    cls = getattr(mod, "ReviewSource", None)
    if cls is None:
        pytest.fail("ReviewSource not defined in mergecraft.utils.source_resolve")
    return cls(url=url, ref=ref, token=token)


def _acquire() -> Any:
    fn = getattr(_source_resolve_mod(), "acquire", None)
    if fn is None:
        pytest.fail("acquire not defined in mergecraft.utils.source_resolve")
    return fn


def _validate_clone_url() -> Any:
    fn = getattr(_source_resolve_mod(), "validate_clone_url", None)
    if fn is None:
        pytest.fail("validate_clone_url not defined in mergecraft.utils.source_resolve")
    return fn


def _confine_path() -> Any:
    fn = getattr(_source_resolve_mod(), "confine_path", None)
    if fn is None:
        pytest.fail("confine_path not defined in mergecraft.utils.source_resolve")
    return fn


def _filter_confined_paths() -> Any:
    fn = getattr(_source_resolve_mod(), "filter_confined_paths", None)
    if fn is None:
        pytest.fail("filter_confined_paths not defined in mergecraft.utils.source_resolve")
    return fn


def _cli_analyzer_sandbox_applies() -> Any:
    fn = getattr(_source_resolve_mod(), "cli_analyzer_sandbox_applies", None)
    if fn is None:
        pytest.fail("cli_analyzer_sandbox_applies not defined in mergecraft.utils.source_resolve")
    return fn


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _init_bare_remote(tmp_path: Path, name: str = "remote.git") -> Path:
    bare = tmp_path / name
    bare.mkdir()
    _git(bare, "init", "--bare", "-b", "main")
    return bare


def _init_repo_with_commit(tmp_path: Path, name: str = "content") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def test_file_scheme_is_rejected() -> None:
    """Only ``https`` clone URLs are accepted — ``file://`` is attacker-controlled."""
    validate = _validate_clone_url()
    with pytest.raises(Exception, match=r"scheme|file"):
        validate("file:///etc/passwd")


def test_ssh_scheme_is_rejected() -> None:
    """SSH transport is not allowlisted for third-party acquisition."""
    validate = _validate_clone_url()
    for url in (
        "git@github.com:owner/repo.git",
        "ssh://git@github.com/owner/repo.git",
    ):
        with pytest.raises(Exception, match=r"ssh|scheme|transport"):
            validate(url)


def test_non_allowlisted_host_is_rejected() -> None:
    """Clone host must be on the GitHub allowlist — arbitrary hosts are rejected."""
    validate = _validate_clone_url()
    with pytest.raises(Exception, match=r"host|allowlist"):
        validate("https://evil.example.com/owner/repo.git")


def test_redirect_chain_is_not_followed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Git must not follow HTTP redirects during acquisition (SSRF / credential leak)."""
    mod = _source_resolve_mod()
    recorded: list[list[str]] = []

    def _recording_run_git(args: list[str], **_kwargs: Any) -> str:
        recorded.append(list(args))
        if "fetch" in args:
            raise RuntimeError("redirect probe")
        return ""

    run_git = getattr(mod, "_run_git", None)
    if run_git is None:
        pytest.fail("_run_git not defined in mergecraft.utils.source_resolve")

    monkeypatch.setattr(mod, "_run_git", _recording_run_git)
    acquire = _acquire()
    source = _review_source(url="https://github.com/owner/repo.git")
    with pytest.raises(RuntimeError, match="redirect probe"):
        acquire(source, dest=tmp_path / "dest")

    joined = " ".join(" ".join(call) for call in recorded)
    assert "followRedirects" in joined or "follow-redirects" in joined.lower()


def test_token_never_written_to_git_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D5/T4 — credential must not persist in the cloned tree's ``.git/config``."""
    token = "ghp_test_token_never_on_disk_abc123"
    content = _init_repo_with_commit(tmp_path)
    bare = _init_bare_remote(tmp_path)
    _git(content, "remote", "add", "origin", str(bare))
    _git(content, "push", "-u", "origin", "main")

    mod = _source_resolve_mod()
    real_run = subprocess.run

    def _local_git(args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        result = real_run(
            ["git", *args],
            cwd=cwd,
            env=env or os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            msg = f"git {' '.join(args)} failed ({result.returncode}): {err}"
            raise RuntimeError(msg)
        return result.stdout

    monkeypatch.setattr(mod, "_run_git", _local_git)

    acquire = _acquire()
    dest = tmp_path / "cloned"
    source = _review_source(url=str(bare), token=token)
    acquire(source, dest=dest)

    config_text = (dest / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    remote_url = subprocess.check_output(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=dest,
        text=True,
    ).strip()
    assert token not in remote_url


def test_token_never_appears_in_process_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spawned git argv must not embed the token — env/header/ASKPASS only (D5)."""
    token = "ghp_argv_leak_probe_xyz789"
    argv_snapshots: list[list[str]] = []

    real_run = subprocess.run

    def _recording_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd and Path(cmd[0]).name == "git":
            argv_snapshots.append(list(cmd))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", _recording_run)
    acquire = _acquire()
    source = _review_source(url="https://github.com/owner/repo.git", token=token)
    with contextlib.suppress(Exception):
        acquire(source, dest=tmp_path / "dest")

    for argv in argv_snapshots:
        joined = " ".join(argv)
        assert token not in joined


def test_submodules_are_not_recursed_by_default(tmp_path: Path) -> None:
    """D6 — submodule trees are not fetched unless explicitly requested."""
    parent = _init_repo_with_commit(tmp_path, "parent")
    child = _init_repo_with_commit(tmp_path, "child")
    bare_child = _init_bare_remote(tmp_path, "child.git")
    _git(child, "remote", "add", "origin", str(bare_child))
    _git(child, "push", "-u", "origin", "main")

    (parent / ".gitmodules").write_text(
        f'[submodule "sub"]\n\tpath = sub\n\turl = {bare_child}\n',
        encoding="utf-8",
    )
    (parent / "sub").mkdir()
    _git(parent, "add", ".gitmodules", "sub")
    _git(parent, "commit", "-m", "add submodule metadata")

    bare_parent = _init_bare_remote(tmp_path, "parent.git")
    _git(parent, "remote", "add", "origin", str(bare_parent))
    _git(parent, "push", "-u", "origin", "main")

    acquire = _acquire()
    dest = tmp_path / "cloned"
    source = _review_source(url=str(bare_parent))
    acquire(source, dest=dest)

    submodule_checkout = dest / "sub" / "README.md"
    assert not submodule_checkout.exists(), "submodule was recursed during clone"


def test_clone_size_ceiling_aborts_cleanly(tmp_path: Path) -> None:
    """Oversized clones abort with a bounded error — hostile repos fail fast (D6)."""
    repo = _init_repo_with_commit(tmp_path)
    (repo / "blob.bin").write_bytes(b"x" * 64_000)
    _git(repo, "add", "blob.bin")
    _git(repo, "commit", "-m", "large blob")

    bare = _init_bare_remote(tmp_path)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")

    acquire = _acquire()
    source = _review_source(url=str(bare))
    with pytest.raises(Exception, match=r"size|limit|ceiling|bytes"):
        acquire(source, dest=tmp_path / "dest", max_bytes=1024)


def test_file_count_ceiling_aborts_cleanly(tmp_path: Path) -> None:
    """File-count ceiling aborts before unbounded tree walks (D6)."""
    repo = _init_repo_with_commit(tmp_path)
    for i in range(20):
        (repo / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "many files")

    bare = _init_bare_remote(tmp_path)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")

    acquire = _acquire()
    source = _review_source(url=str(bare))
    with pytest.raises(Exception, match=r"file|count|limit|ceiling"):
        acquire(source, dest=tmp_path / "dest", max_files=5)


def test_symlink_escaping_workspace_is_dropped(tmp_path: Path) -> None:
    """D7/T5 — symlinks pointing outside the workspace are not readable."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("exfil\n", encoding="utf-8")
    link = workspace / "escape"
    link.symlink_to(secret)

    confine = _confine_path()
    result = confine(workspace, "escape")
    assert result is None


def test_diff_path_escaping_workspace_is_dropped(tmp_path: Path) -> None:
    """Diff paths that resolve outside the workspace root are dropped (D7)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope\n", encoding="utf-8")

    filter_paths = _filter_confined_paths()
    kept = filter_paths(
        workspace,
        ["README.md", "../outside.txt", "../../etc/passwd"],
    )
    assert kept == ["README.md"]


def test_anonymous_clone_of_private_repo_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D10 — missing credentials against a private repo yield a clear auth error."""
    mod = _source_resolve_mod()
    auth_err = getattr(mod, "CloneAuthError", None)
    if auth_err is None:
        pytest.fail("CloneAuthError not defined in mergecraft.utils.source_resolve")

    def _fail_auth(*_args: Any, **_kwargs: Any) -> str:
        msg = "Authentication failed for 'https://github.com/private-owner/private-repo.git'"
        raise RuntimeError(msg)

    run_git = getattr(mod, "_run_git", None)
    if run_git is None:
        pytest.fail("_run_git not defined in mergecraft.utils.source_resolve")
    monkeypatch.setattr(mod, "_run_git", _fail_auth)

    acquire = _acquire()
    source = _review_source(url="https://github.com/private-owner/private-repo.git", token=None)
    with pytest.raises(auth_err, match=r"auth|credential|token|private"):
        acquire(source, dest=tmp_path / "dest")


def test_analyzer_sandbox_applies_on_the_cli_path(tmp_path: Path) -> None:
    """Untrusted CLI reviews must plan analyzer sandbox isolation (existing D7 policy)."""
    applies = _cli_analyzer_sandbox_applies()
    assert applies(trust_tier="untrusted", repo_root=tmp_path) is True
    assert applies(trust_tier="trusted", repo_root=tmp_path) is False
