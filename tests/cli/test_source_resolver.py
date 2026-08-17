"""TS4 — CLI source resolver (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins D8 (``review`` verb; ``diff-review`` hidden alias), D9 (worktrees via
``--git-common-dir``), D10 (auth precedence), and integration with trust tier
(TS1) plus unchanged ``DiffMaterialization`` downstream.

Authoring wave: **TS4.1** (RED). Implementation: **TS4.2**.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.analyzers.support import import_module
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.utils.offline_diff import DiffMaterialization, materialize_diff

_TS4_2_XFAIL = pytest.mark.xfail(reason="green after TS4.2: source resolver", strict=False)

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _resolver_mod() -> Any:
    return import_module("mergecraft.utils.source_resolve")


def _spec_cls() -> Any:
    cls = getattr(_resolver_mod(), "SourceResolverSpec", None)
    if cls is None:
        pytest.fail("SourceResolverSpec not defined in mergecraft.utils.source_resolve")
    return cls


def _resolved_cls() -> Any:
    cls = getattr(_resolver_mod(), "ResolvedWorkspace", None)
    if cls is None:
        pytest.fail("ResolvedWorkspace not defined in mergecraft.utils.source_resolve")
    return cls


def _resolve_workspace() -> Any:
    fn = getattr(_resolver_mod(), "resolve_workspace", None)
    if fn is None:
        pytest.fail("resolve_workspace not defined in mergecraft.utils.source_resolve")
    return fn


def _materialize_resolved_diff() -> Any:
    fn = getattr(_resolver_mod(), "materialize_resolved_diff", None)
    if fn is None:
        pytest.fail("materialize_resolved_diff not defined in mergecraft.utils.source_resolve")
    return fn


def _resolve_auth_token() -> Any:
    fn = getattr(_resolver_mod(), "resolve_auth_token", None)
    if fn is None:
        pytest.fail("resolve_auth_token not defined in mergecraft.utils.source_resolve")
    return fn


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _init_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _init_bare_remote(tmp_path: Path, name: str = "remote.git") -> Path:
    bare = tmp_path / name
    bare.mkdir()
    _git(bare, "init", "--bare", "-b", "main")
    return bare


def _push_to_bare(content: Path, bare: Path, *, branch: str = "main") -> None:
    _git(content, "remote", "add", "origin", str(bare))
    _git(content, "push", "-u", "origin", branch)


@_TS4_2_XFAIL
def test_local_path_source(tmp_path: Path) -> None:
    """``--repo <path>`` reviews a local checkout at that path."""
    repo = _init_repo(tmp_path)
    (repo / "feature.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "add feature")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    spec = spec_cls(repo=str(repo), invocation_root=tmp_path)
    workspace = resolve(spec)
    assert workspace.cwd.resolve() == repo.resolve()
    assert workspace.cloned is False

    result = materialize(workspace, spec=spec, out_dir=tmp_path / "out")
    assert isinstance(result, DiffMaterialization)
    assert result.empty is False
    assert "feature.txt" in result.path.read_text(encoding="utf-8")


@_TS4_2_XFAIL
def test_linked_worktree_resolves_common_dir(tmp_path: Path) -> None:
    """D9/T6 — base detection reads refs from the main checkout's git dir."""
    main = _init_repo(tmp_path, "main-checkout")
    _git(main, "branch", "develop")
    _git(main, "checkout", "develop")
    (main / "on-develop.txt").write_text("dev\n", encoding="utf-8")
    _git(main, "add", "on-develop.txt")
    _git(main, "commit", "-m", "on develop")

    worktree = tmp_path / "linked-wt"
    _git(main, "worktree", "add", str(worktree), "develop")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    spec = spec_cls(repo=str(worktree), base="main", invocation_root=tmp_path)
    workspace = resolve(spec)
    common_dir = getattr(workspace, "git_common_dir", None)
    assert common_dir is not None
    assert common_dir.is_dir()

    result = materialize(workspace, spec=spec, out_dir=tmp_path / "wt-out")
    assert result.empty is False
    assert result.base_ref == "main"


@_TS4_2_XFAIL
def test_public_repo_url_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A public ``https://github.com/…`` URL is acquired and reviewed."""
    content = _init_repo(tmp_path, "content")
    bare = _init_bare_remote(tmp_path)
    _push_to_bare(content, bare)

    mod = _resolver_mod()
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

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    file_url = bare.as_uri()
    spec = spec_cls(repo=file_url, invocation_root=tmp_path)
    workspace = resolve(spec)
    assert workspace.cloned is True
    assert workspace.cwd.is_dir()

    result = materialize(workspace, spec=spec, out_dir=tmp_path / "url-out")
    assert isinstance(result, DiffMaterialization)
    assert result.path.is_file()


@_TS4_2_XFAIL
def test_owner_name_shorthand_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``owner/repo`` shorthand resolves to a GitHub HTTPS clone."""
    content = _init_repo(tmp_path, "content")
    bare = _init_bare_remote(tmp_path)
    _push_to_bare(content, bare)

    mod = _resolver_mod()
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

    captured_urls: list[str] = []
    real_acquire = mod.acquire

    def _recording_acquire(source: Any, **kwargs: Any) -> Any:
        captured_urls.append(source.url)
        return real_acquire(source, **kwargs)

    monkeypatch.setattr(mod, "acquire", _recording_acquire)

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()

    spec = spec_cls(repo="acme/widget", invocation_root=tmp_path)
    workspace = resolve(spec)
    assert workspace.cloned is True
    assert captured_urls
    assert "github.com/acme/widget" in captured_urls[0]


@_TS4_2_XFAIL
def test_private_repo_with_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Private repos require a token — ``--token`` satisfies auth (D10)."""
    content = _init_repo(tmp_path, "private-content")
    bare = _init_bare_remote(tmp_path)
    _push_to_bare(content, bare)

    mod = _resolver_mod()
    real_run = subprocess.run
    token = "ghp_private_test_token_xyz"

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

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()

    spec = spec_cls(
        repo="https://github.com/private-org/secret.git",
        token=token,
        invocation_root=tmp_path,
    )
    workspace = resolve(spec)
    assert workspace.cloned is True
    assert workspace.cwd.is_dir()


@_TS4_2_XFAIL
def test_head_and_base_refs_select_the_diff(tmp_path: Path) -> None:
    """``--head`` and ``--base`` select the diff range explicitly."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    (repo / "head.txt").write_text("head change\n", encoding="utf-8")
    _git(repo, "add", "head.txt")
    _git(repo, "commit", "-m", "feature commit")
    _git(repo, "checkout", "main")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    spec = spec_cls(
        repo=str(repo),
        head="feature",
        base="main",
        invocation_root=tmp_path,
    )
    workspace = resolve(spec)
    result = materialize(workspace, spec=spec, out_dir=tmp_path / "hb-out")
    text = result.path.read_text(encoding="utf-8")
    assert "head.txt" in text
    assert result.base_ref == "main"


@_TS4_2_XFAIL
def test_remote_branch_that_is_not_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-default remote branch is checked out for review."""
    content = _init_repo(tmp_path, "content")
    _git(content, "checkout", "-b", "release")
    (content / "release.txt").write_text("release\n", encoding="utf-8")
    _git(content, "add", "release.txt")
    _git(content, "commit", "-m", "release branch")
    _git(content, "checkout", "main")

    bare = _init_bare_remote(tmp_path)
    _git(content, "remote", "add", "origin", str(bare))
    _git(content, "push", "-u", "origin", "main")
    _git(content, "push", "-u", "origin", "release")

    mod = _resolver_mod()
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

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    spec = spec_cls(
        repo="acme/widget",
        head="release",
        base="main",
        invocation_root=tmp_path,
    )
    workspace = resolve(spec)
    result = materialize(workspace, spec=spec, out_dir=tmp_path / "branch-out")
    assert "release.txt" in result.path.read_text(encoding="utf-8")


@_TS4_2_XFAIL
def test_staged_only(tmp_path: Path) -> None:
    """``--staged`` uses ``git diff --cached``, bypassing base detection."""
    repo = _init_repo(tmp_path)
    (repo / "staged.txt").write_text("staged only\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    spec = spec_cls(repo=str(repo), staged=True, invocation_root=tmp_path)
    workspace = resolve(spec)
    result = materialize(workspace, spec=spec, out_dir=tmp_path / "staged-out")
    text = result.path.read_text(encoding="utf-8")
    assert "staged.txt" in text
    assert result.base_ref is None


@_TS4_2_XFAIL
def test_unstaged_only(tmp_path: Path) -> None:
    """``--unstaged`` reviews only the working-tree diff."""
    repo = _init_repo(tmp_path)
    (repo / "unstaged.txt").write_text("wip\n", encoding="utf-8")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()

    spec = spec_cls(repo=str(repo), unstaged=True, invocation_root=tmp_path)
    workspace = resolve(spec)
    result = materialize(workspace, spec=spec, out_dir=tmp_path / "unstaged-out")
    text = result.path.read_text(encoding="utf-8")
    assert "unstaged.txt" in text
    assert result.base_ref is None


@_TS4_2_XFAIL
def test_commit_range(tmp_path: Path) -> None:
    """``--range HEAD~3..HEAD`` is accepted; malformed ranges are rejected."""
    repo = _init_repo(tmp_path)
    for idx in range(3):
        (repo / f"f{idx}.txt").write_text(f"v{idx}\n", encoding="utf-8")
        _git(repo, "add", f"f{idx}.txt")
        _git(repo, "commit", "-m", f"commit {idx}")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()
    parse_range = getattr(_resolver_mod(), "parse_commit_range", None)
    if parse_range is None:
        pytest.fail("parse_commit_range not defined in mergecraft.utils.source_resolve")

    with pytest.raises(ValueError, match=r"range|malformed|invalid"):
        parse_range("HEAD~3; rm -rf /")

    spec = spec_cls(repo=str(repo), commit_range="HEAD~3..HEAD", invocation_root=tmp_path)
    workspace = resolve(spec)
    result = materialize(workspace, spec=spec, out_dir=tmp_path / "range-out")
    text = result.path.read_text(encoding="utf-8")
    assert "f0.txt" in text or "f1.txt" in text or "f2.txt" in text


@_TS4_2_XFAIL
def test_auth_precedence_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """D10 — ``--token`` > ``GH_TOKEN``/``GITHUB_TOKEN`` > ``gh auth token`` > anonymous."""
    resolve_auth = _resolve_auth_token()

    assert resolve_auth(explicit="cli-token").token == "cli-token"
    assert resolve_auth(explicit="cli-token").source == "--token"

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "env-gh-token")
    assert resolve_auth().token == "env-gh-token"

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "env-github-token")
    assert resolve_auth().token == "env-github-token"

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def _fake_gh(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="gh-cli-token\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_gh)
    assert resolve_auth().token == "gh-cli-token"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    )
    assert resolve_auth().token is None
    assert resolve_auth().source == "anonymous"


def test_review_alias_diff_review_still_works(tmp_path: Path) -> None:
    """D8 — ``diff-review`` remains a working entry point (Harbor pin)."""
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert "offline" in out.lower()
    assert "demo.py" in out


@_TS4_2_XFAIL
def test_downstream_pipeline_unchanged(tmp_path: Path) -> None:
    """Resolver produces the same ``DiffMaterialization`` shape as ``materialize_diff``."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    (repo / "pipe.txt").write_text("pipe\n", encoding="utf-8")
    _git(repo, "add", "pipe.txt")
    _git(repo, "commit", "-m", "pipe change")

    direct = materialize_diff(cwd=repo, out_dir=tmp_path / "direct", base="main")

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    materialize = _materialize_resolved_diff()
    spec = spec_cls(repo=str(repo), base="main", invocation_root=tmp_path)
    workspace = resolve(spec)
    resolved = materialize(workspace, spec=spec, out_dir=tmp_path / "resolved")

    assert type(resolved) is type(direct)
    assert resolved.base_ref == direct.base_ref
    assert resolved.empty == direct.empty
    assert resolved.line_count == direct.line_count
    assert "pipe.txt" in resolved.path.read_text(encoding="utf-8")


@_TS4_2_XFAIL
def test_cloned_source_reviews_at_untrusted_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TS1 integration — cloned sources review at untrusted tier."""
    import asyncio

    from mergecraft.offline_review import run_offline_diff_review

    content = _init_repo(tmp_path, "content")
    bare = _init_bare_remote(tmp_path)
    _push_to_bare(content, bare)

    mod = _resolver_mod()
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

    spec_cls = _spec_cls()
    resolve = _resolve_workspace()
    file_url = bare.as_uri()
    spec = spec_cls(repo=file_url, invocation_root=tmp_path)
    workspace = resolve(spec)

    tier_holder: dict[str, str] = {}

    async def _run() -> None:
        result = await run_offline_diff_review(
            cwd=workspace.cwd,
            dry_run=True,
            invocation_root=tmp_path,
            cloned=workspace.cloned,
        )
        assert result.success, result.error
        tier_holder["tier"] = os.environ.get("MERGECRAFT_TRUST_TIER", "")

    asyncio.run(_run())
    assert tier_holder.get("tier") == "untrusted"
