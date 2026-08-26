"""Lane A AP1.6 — prep installs into a dedicated virtualenv (MCB-22 / D12)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_install_targets_a_dedicated_virtualenv(tmp_path: Path) -> None:
    from mergecraft.prep.python import InstallPythonDependencies
    from mergecraft.prep.types import PrepOptions

    (tmp_path / "requirements.txt").write_text("httpx==0.28.1\n", encoding="utf-8")
    captured: list[list[str]] = []

    async def _fake_run(cmd: str, args: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
        captured.append([cmd, *args])
        return 0, ""

    import mergecraft.prep.python as prep_python

    prep_python._run_cmd = _fake_run  # type: ignore[method-assign]
    inst = InstallPythonDependencies()
    result = await inst.run(PrepOptions(ignore_scripts=False))
    assert result.dependencies_installed is True
    joined = " ".join(" ".join(c) for c in captured)
    assert "prep-venv" in joined or ".venv" in joined
