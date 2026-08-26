"""Lane A AP1.6 — prep lockfile selection order (MCB-22)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.prep.python import _config_applies

pytestmark = pytest.mark.xfail(
    reason="green after AP7: uv.lock wins over requirements.txt",
    strict=False,
)


def test_uv_lock_wins_over_a_stray_requirements_txt(tmp_path: Path) -> None:
    from mergecraft.prep import python as prep_python

    (tmp_path / "requirements.txt").write_text("httpx==0.1\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    chosen = next(c for c in prep_python._PYTHON_CONFIGS if _config_applies(c, tmp_path))
    assert chosen.file == "uv.lock"


def test_cwd_is_threaded_not_read_twice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mergecraft.prep.python import InstallPythonDependencies

    calls = 0

    def _cwd() -> Path:
        nonlocal calls
        calls += 1
        return tmp_path

    monkeypatch.setattr("mergecraft.prep.python.Path.cwd", _cwd)
    inst = InstallPythonDependencies()
    _ = inst.should_run()
    assert calls == 1, "should_run must read cwd once; run receives explicit cwd after AP7"
