"""An explicitly named config file that is missing is a configuration error (#1337)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.layered import load_layered_config_dict
from mergecraft.config.settings import load_repo_settings
from mergecraft.config.yaml_unique import ConfigParseError

if TYPE_CHECKING:
    from pathlib import Path


def _committed(tmp_path: Path) -> None:
    """Write a committed config that a fall-back would silently pick up."""
    (tmp_path / ".mergecraft").mkdir()
    (tmp_path / ".mergecraft" / "config.yaml").write_text("shell: disabled\n", encoding="utf-8")


def test_missing_env_config_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``MERGECRAFT_CONFIG`` naming a missing file never loads the committed config."""
    _committed(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(tmp_path / "typo.yaml"))
    with pytest.raises(ConfigParseError, match=r"MERGECRAFT_CONFIG file not found: .*typo\.yaml"):
        load_layered_config_dict(root=tmp_path)
    with pytest.raises(ConfigParseError, match=r"typo\.yaml"):
        load_repo_settings(root=tmp_path, load_learnings_files=False)


def test_missing_explicit_path_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit path that is missing never yields the defaults or the committed file."""
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    _committed(tmp_path)
    missing = tmp_path / "typo.yaml"
    with pytest.raises(ConfigParseError, match="config file not found"):
        load_repo_settings(missing, load_learnings_files=False)
    with pytest.raises(ConfigParseError, match="config file not found"):
        load_layered_config_dict(root=tmp_path, explicit_path=missing)


def test_existing_env_config_still_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A present ``MERGECRAFT_CONFIG`` file is still the sole contributor."""
    _committed(tmp_path)
    chosen = tmp_path / "chosen.yaml"
    chosen.write_text("shell: restricted\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(chosen))
    assert load_layered_config_dict(root=tmp_path)["shell"] == "restricted"
