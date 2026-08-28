"""Lane A AP1.6 — prep installs into a dedicated virtualenv (MCB-22 / D12)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_install_targets_a_dedicated_virtualenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.prep.python import (
        InstallPythonDependencies,
        _prep_venv_bin,
        _prep_venv_dir,
        _prep_venv_python,
    )
    from mergecraft.prep.types import PrepOptions

    (tmp_path / "requirements.txt").write_text("httpx==0.28.1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    captured: list[list[str]] = []

    async def _fake_run(cmd: str, args: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
        captured.append([cmd, *args])
        if len(args) >= 3 and args[0] == "-m" and args[1] == "venv":
            venv = Path(args[2])
            for name in ("python", "pip"):
                bin_path = (
                    _prep_venv_python(venv) if name == "python" else _prep_venv_bin(venv, name)
                )
                bin_path.parent.mkdir(parents=True, exist_ok=True)
                bin_path.touch()
        elif "install" in args:
            venv = _prep_venv_dir(tmp_path)
            for tool in ("uv", "poetry", "pipenv"):
                if tool in args:
                    tool_bin = _prep_venv_bin(venv, tool)
                    tool_bin.parent.mkdir(parents=True, exist_ok=True)
                    tool_bin.touch()
                    break
        return 0, ""

    import mergecraft.prep.python as prep_python

    prep_python._run_cmd = _fake_run  # type: ignore[method-assign]
    inst = InstallPythonDependencies()
    result = await inst.run(PrepOptions(ignore_scripts=False))
    assert result.dependencies_installed is True
    assert result.package_manager == "pip"
    assert result.config_file == "requirements.txt"
    joined = " ".join(" ".join(c) for c in captured)
    assert "prep-venv" in joined
    venv = _prep_venv_dir(tmp_path)
    prep_pip = str(_prep_venv_bin(venv, "pip"))
    assert any(prep_pip in " ".join(c) for c in captured), (
        "dependency install must use pip from the prep virtualenv"
    )
