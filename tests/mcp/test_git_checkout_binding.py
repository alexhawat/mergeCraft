"""The ``git`` tool binds -C / --git-dir / --work-tree to registered checkouts.

Every test drives the real tool against real repositories in ``tmp_path``:
being inside the workspace is not enough for these options, the directory has
to select a checkout this run registered. The spawn tests assert the fixed
hardened configuration on every git child the tool starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_git_tool import _ctx
from tests.support.policy_fixtures import commit_all, init_git_repo

from mergecraft.mcp.git import git_fetch_tool, git_tool
from mergecraft.mcp.tool_state import ensure_repo_state

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _primary(tmp_path: Path) -> Path:
    root = (tmp_path / "checkout").resolve()
    init_git_repo(root)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    commit_all(root, "initial")
    _git(root, "config", "--local", "mc.probe", "primary")
    return root


def _nested_repo(root: Path) -> Path:
    """A bare-layout repository sitting in the checkout's tree."""
    nested = root / "vendor" / "data"
    nested.mkdir(parents=True)
    _git(nested, "init", "-q", "--bare")
    _git(nested, "config", "mc.probe", "nested")
    return nested


async def _run(ctx: ToolContext, args: list[str], command: str = "config") -> Any:
    return await git_tool(ctx).execute({"command": command, "args": args})


def _ok(result: Any) -> str:
    assert result.is_error is False, result.content[0]["text"]
    return str(json.loads(result.content[0]["text"])["output"])


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ToolContext, Path, Path]:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    root = _primary(tmp_path)
    nested = _nested_repo(root)
    return _ctx(root), root, nested


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda n: ["-C", str(n)], id="dash-C"),
        pytest.param(lambda n: ["--git-dir", str(n)], id="git-dir-separate"),
        pytest.param(lambda n: [f"--git-dir={n}"], id="git-dir-equals"),
        pytest.param(lambda n: ["--work-tree", str(n)], id="work-tree-separate"),
        pytest.param(lambda n: [f"--work-tree={n}"], id="work-tree-equals"),
        pytest.param(lambda _n: ["-C", "vendor/data"], id="dash-C-relative"),
        pytest.param(lambda _n: ["-C", "vendor", "-C", "data"], id="dash-C-cumulative"),
    ],
)
async def test_nested_repository_in_the_tree_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, build: Any
) -> None:
    ctx, _root, nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    result = await _run(ctx, [*build(nested), "--get", "mc.probe"])
    assert result.is_error is True
    assert "registered checkout" in result.content[0]["text"]


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda r: ["-C", str(r)], id="dash-C-root"),
        pytest.param(lambda r: ["-C", str(r / "src")], id="dash-C-subdir"),
        pytest.param(lambda _r: ["-C", "src"], id="dash-C-relative-subdir"),
        pytest.param(lambda r: [f"--git-dir={r / '.git'}"], id="git-dir-own"),
        pytest.param(
            lambda r: ["--git-dir", str(r / ".git"), "--work-tree", str(r)], id="both-own"
        ),
    ],
)
async def test_registered_checkout_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, build: Any
) -> None:
    ctx, root, _nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    assert _ok(await _run(ctx, [*build(root), "--get", "mc.probe"])).strip() == "primary"


async def test_secondary_registered_checkout_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _root, _nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    other = (tmp_path / "other").resolve()
    await asyncio.to_thread(init_git_repo, other)
    await asyncio.to_thread(_git, other, "config", "--local", "mc.probe", "other")
    ensure_repo_state(ctx.tool_state, owner="acme", name="other", dir=str(other), access="read")
    assert _ok(await _run(ctx, ["-C", str(other), "--get", "mc.probe"])).strip() == "other"


async def test_unregistered_repository_in_the_workspace_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _root, _nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    stray = (tmp_path / "stray").resolve()
    await asyncio.to_thread(init_git_repo, stray)
    result = await _run(ctx, ["-C", str(stray), "--get", "mc.probe"])
    assert result.is_error is True
    assert "registered checkout" in result.content[0]["text"]


async def test_global_and_system_config_are_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _root, _nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[mc]\n\tambient = global\n", encoding="utf-8")
    system = tmp_path / "system.gitconfig"
    system.write_text("[mc]\n\tambient = system\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(system))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "mc.ambient")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "env")
    # Sanity: plain git does see every one of these sources.
    plain = await asyncio.to_thread(
        subprocess.run,
        ["git", "config", "--get-all", "mc.ambient"],
        cwd=ctx.tool_state.repos["acme/demo"].dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert {"global", "system", "env"} <= set(plain.stdout.split())

    result = await _run(ctx, ["--get-all", "mc.ambient"])
    assert result.is_error is True
    text = result.content[0]["text"]
    assert "failed (1)" in text
    for source in ("global", "system", "env"):
        assert source not in text.split("failed (1)", 1)[1]


class _SpawnSpy:
    """Wrap ``subprocess.Popen`` and keep each git child's argv and env."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, argv: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(argv, list) and argv and argv[0] == "git":
            env = kwargs.get("env")
            self.calls.append((list(argv), dict(env) if env is not None else dict(os.environ)))
        return self.real(argv, *args, **kwargs)


def _assert_hardened(calls: list[tuple[list[str], dict[str, str]]]) -> None:
    assert calls, "expected git spawns"
    for argv, env in calls:
        assert env.get("GIT_CONFIG_NOSYSTEM") == "1", argv
        assert env.get("GIT_CONFIG_GLOBAL") == os.devnull, argv
        assert env.get("GIT_ATTR_NOSYSTEM") == "1", argv
        assert "GIT_CONFIG_PARAMETERS" not in env, argv
        flat = " ".join(argv)
        for pin in (
            "core.fsmonitor=false",
            "core.hooksPath=/dev/null",
            "safe.bareRepository=explicit",
            "credential.helper=",
            "core.attributesFile=/dev/null",
        ):
            assert pin in flat, (pin, argv)


async def test_every_git_tool_spawn_uses_the_hardened_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, root, _nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'mc.ambient'='env'")
    spy = _SpawnSpy(subprocess.Popen)
    monkeypatch.setattr(subprocess, "Popen", spy)
    _ok(await _run(ctx, ["-C", "src", "--get", "mc.probe"]))
    _ok(await _run(ctx, ["HEAD:src/app.py"], command="show"))
    _ok(await _run(ctx, ["-1", "-Sx"], command="log"))
    _assert_hardened(spy.calls)
    log_argv = next(argv for argv, _env in spy.calls if "log" in argv)
    assert "--no-textconv" in log_argv
    assert any(f"safe.directory={root}" in " ".join(argv) for argv, _env in spy.calls)


async def test_git_fetch_spawns_use_the_hardened_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, root, _nested = await asyncio.to_thread(_setup, tmp_path, monkeypatch)
    remote = (tmp_path / "remote.git").resolve()
    await asyncio.to_thread(_git, tmp_path, "clone", "-q", "--bare", str(root), str(remote))
    await asyncio.to_thread(_git, root, "remote", "add", "origin", str(remote))
    spy = _SpawnSpy(subprocess.Popen)
    monkeypatch.setattr(subprocess, "Popen", spy)
    result = await git_fetch_tool(ctx).execute({})
    assert result.is_error is False, result.content[0]["text"]
    _assert_hardened(spy.calls)
