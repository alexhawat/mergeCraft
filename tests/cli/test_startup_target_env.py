"""Startup credentials follow an explicitly selected local command target."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer

from mergecraft.cli import app as cli_app
from mergecraft.cli.startup_env import implicit_env_is_tracked, startup_local_target

if TYPE_CHECKING:
    from collections.abc import Iterator

_KEY = "MERGECRAFT_MODEL"


@pytest.fixture
def workspaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    for root, value in [(caller, "caller-model"), (target, "target-model")]:
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".env").write_text(f"{_KEY}={value}\n")
    before = os.environ.get(_KEY)
    monkeypatch.delenv(_KEY, raising=False)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.chdir(caller)
    try:
        yield caller, target
    finally:
        if before is None:
            os.environ.pop(_KEY, None)
        else:
            os.environ[_KEY] = before


@pytest.mark.parametrize(
    "args",
    [
        ["review", "--cwd", "{target}"],
        ["review", "--cwd={target}"],
        ["review", "--repo", "{target}", "--cwd", "{caller}"],
        ["diff-review", "--repo={target}"],
        ["--quiet", "config", "show", "model", "--cwd", "{target}"],
        ["review", "--repo", "example/remote", "--cwd", "{target}"],
    ],
)
def test_selected_local_workspace_wins_over_callers_env(
    workspaces: tuple[Path, Path], args: list[str]
) -> None:
    caller, target = workspaces
    cli_app._load_local_env([arg.format(caller=caller, target=target) for arg in args])
    assert os.environ[_KEY] == "target-model"


@pytest.mark.parametrize("kind", ["ambient", "explicit", "actions", "missing"])
def test_precedence_and_missing_file_never_fall_back_to_wrong_repo(
    workspaces: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    caller, target = workspaces
    expected: str | None = None
    if kind == "ambient":
        monkeypatch.setenv(_KEY, "operator-model")
        expected = "operator-model"
    elif kind == "explicit":
        explicit = caller / "operator.env"
        explicit.write_text(f"{_KEY}=explicit-model\n")
        monkeypatch.setenv("MERGECRAFT_ENV", "operator.env")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        expected = "explicit-model"
    elif kind == "actions":
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    else:
        (target / ".env").unlink()
    cli_app._load_local_env(["review", "--cwd", str(target)])
    assert os.environ.get(_KEY) == expected


@pytest.mark.parametrize("kind", ["prompt", "delimiter", "remote"])
def test_option_text_and_remote_sources_do_not_redirect_local_credentials(
    workspaces: tuple[Path, Path], kind: str
) -> None:
    _, target = workspaces
    if kind == "prompt":
        args = ["review", "--prompt", f"--cwd {target}"]
    elif kind == "delimiter":
        args = ["review", "--", "--cwd", str(target)]
    else:
        args = ["review", "--repo", "https://github.com/example/remote.git"]
    cli_app._load_local_env(args)
    assert os.environ[_KEY] == "caller-model"


def test_real_entrypoint_loads_selected_environment_before_command(
    workspaces: tuple[Path, Path],
) -> None:
    caller, target = workspaces
    source_root = Path(cli_app.__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from mergecraft.cli.app import main; main()",
            "--quiet",
            "config",
            "show",
            "model",
            "--cwd",
            str(target),
        ],
        cwd=caller,
        env={**os.environ, "PYTHONPATH": str(source_root), "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "target-model" in output
    assert "caller-model" not in output


def test_target_discovery_never_invokes_option_or_command_callbacks(tmp_path: Path) -> None:
    app = typer.Typer()

    def callback(value: Path) -> Path:
        raise AssertionError("option callback must not run during discovery")

    @app.command()
    def review(cwd: Path = typer.Option(..., "--cwd", callback=callback)) -> None:
        raise AssertionError("command must not run during discovery")

    assert startup_local_target(app, ["--cwd", str(tmp_path)]) == tmp_path.resolve()


@pytest.mark.parametrize("symlink", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_tracked_target_env_requires_explicit_operator_selection(
    workspaces: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    symlink: bool,
    explicit: bool,
) -> None:
    from io import StringIO

    from rich.console import Console

    _, target = workspaces
    env_path = target / ".env"
    tracked = target / "tracked-credentials" if symlink else env_path
    if symlink:
        env_path.rename(tracked)
        env_path.symlink_to(tracked.name)
    subprocess.run(["git", "add", tracked.name], cwd=target, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "tracked credential fixture",
        ],
        cwd=target,
        check=True,
        capture_output=True,
    )
    if explicit:
        monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    captured = StringIO()
    monkeypatch.setattr(cli_app, "err_console", Console(file=captured, width=120))

    cli_app._load_local_env(["review", "--repo", str(target)])

    assert os.environ.get(_KEY) == ("target-model" if explicit else None)
    assert ("Skipping implicit .env" in captured.getvalue()) is not explicit
    assert "target-model" not in captured.getvalue()


def test_implicit_env_symlink_loop_is_not_trusted(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.symlink_to(path.name)
    assert implicit_env_is_tracked(path)


@pytest.mark.parametrize(
    "args", [["--help"], ["--version"], ["review"], ["config", "show", "model"]]
)
def test_no_target_options_skips_command_tree(
    args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal invocations need no preliminary Click tree construction."""

    def unexpected(*args: object) -> None:
        raise AssertionError("startup must not build the command tree")

    monkeypatch.setattr("mergecraft.cli.startup_env.get_command", unexpected)
    assert startup_local_target(typer.Typer(), args) is None
