"""Launcher resolution for the public stdio MCP subprocess (venv-agnostic).

CI runs shards in ``.venv-dev`` while the helper used to hardcode ``.venv``.
These pin the resolution order and the entry-point fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.mcp import public_mcp_support

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _make_script(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/nonexistent/python\n", encoding="utf-8")
    return path


def test_launcher_uses_active_virtual_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    venv = tmp_path / "env"
    script = _make_script(venv / "bin" / "mergecraft")
    monkeypatch.setattr(public_mcp_support, "REPO_ROOT", tmp_path / "repo-without-venv")
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setattr(public_mcp_support.sys, "executable", str(venv / "bin" / "python"))

    argv = public_mcp_support._mergecraft_argv()

    assert argv == [str(venv / "bin" / "python"), str(script)]


def test_launcher_runs_console_script_through_interpreter(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bin_dir = tmp_path / "custom-venv" / "bin"
    script = _make_script(bin_dir / "mergecraft")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(public_mcp_support, "REPO_ROOT", tmp_path / "repo-without-venv")
    monkeypatch.setattr(public_mcp_support.sys, "executable", str(bin_dir / "python"))

    argv = public_mcp_support._mergecraft_argv()

    assert argv == [str(bin_dir / "python"), str(script)]


def test_launcher_falls_back_to_entrypoint(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(public_mcp_support, "REPO_ROOT", tmp_path / "none")
    monkeypatch.setattr(public_mcp_support.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(public_mcp_support.shutil, "which", lambda _name: None)

    argv = public_mcp_support._mergecraft_argv()

    assert argv[0] == str(tmp_path / "python")
    assert argv[1] == "-c"
    assert "mergecraft.cli.app" in argv[2]
