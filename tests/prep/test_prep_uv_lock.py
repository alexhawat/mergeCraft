"""Lane A AP1.6 — uv.lock prep must not touch checkout ``.venv`` (MCB-22)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_uv_lock_sync_targets_prep_venv_not_checkout_dot_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.prep.python import (
        InstallPythonDependencies,
        _prep_venv_bin,
        _prep_venv_dir,
        _prep_venv_python,
    )
    from mergecraft.prep.types import PrepOptions

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("# uv lock\n", encoding="utf-8")
    checkout_venv = tmp_path / ".venv"
    checkout_venv.mkdir()
    (checkout_venv / "marker").write_text("untouched", encoding="utf-8")
    before_mtime = (checkout_venv / "marker").stat().st_mtime_ns

    monkeypatch.chdir(tmp_path)
    captured_envs: list[dict[str, str]] = []

    async def _fake_run(cmd: str, args: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
        from mergecraft.prep.python import _prep_env

        captured_envs.append(_prep_env(cwd))
        if len(args) >= 3 and args[0] == "-m" and args[1] == "venv":
            venv = Path(args[2])
            for name in ("python", "pip", "uv"):
                bin_path = (
                    _prep_venv_python(venv) if name == "python" else _prep_venv_bin(venv, name)
                )
                bin_path.parent.mkdir(parents=True, exist_ok=True)
                bin_path.touch()
        return 0, ""

    import mergecraft.prep.python as prep_python

    prep_python._run_cmd = _fake_run  # type: ignore[method-assign]
    inst = InstallPythonDependencies()
    result = await inst.run(PrepOptions(ignore_scripts=False))

    assert result.dependencies_installed is True
    assert result.package_manager == "uv"
    assert result.config_file == "uv.lock"
    assert captured_envs, "prep subprocesses must receive an isolated env"
    assert captured_envs[-1]["UV_PROJECT_ENVIRONMENT"] == ".mergecraft/prep-scratch/prep-venv"
    assert (checkout_venv / "marker").stat().st_mtime_ns == before_mtime
    assert _prep_venv_dir(tmp_path) == tmp_path / ".mergecraft" / "prep-scratch" / "prep-venv"
