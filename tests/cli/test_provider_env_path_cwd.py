"""``provider_cmd._env_path`` honors ``--cwd``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.cli.support_provider_registry import scaffold_mergecraft_home, stub_mergecraft_env

from mergecraft.cli.provider_cmd import _env_path

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def test_env_path_uses_cwd_not_process_cwd(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repo = tmp_path / "consumer-repo"
    other = tmp_path / "other-dir"
    repo.mkdir()
    other.mkdir()
    scaffold_mergecraft_home(repo)
    stub_mergecraft_env(monkeypatch, repo)
    monkeypatch.chdir(other)

    assert _env_path(repo) == (repo / ".env").resolve()
    assert _env_path(repo) != (other / ".env").resolve()
