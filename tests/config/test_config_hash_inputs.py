"""#1244 - the config integrity hash covers the files the layered loader actually reads."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings_snapshot import (
    assert_config_unchanged,
    capture_repo_settings_snapshot,
    config_yaml_hash,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_env_selected_config_edit_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / ".mergecraft" / "config.yaml", "shell: restricted\n")
    env_cfg = _write(tmp_path / "elsewhere" / "cfg.yaml", "shell: disabled\n")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(env_cfg))

    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.settings.shell == "disabled"
    assert_config_unchanged(snapshot)

    env_cfg.write_text("shell: unrestricted\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after settings were snapshotted"):
        assert_config_unchanged(snapshot)


def test_unused_committed_file_edit_does_not_trip_when_env_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed = _write(tmp_path / ".mergecraft" / "config.yaml", "shell: restricted\n")
    env_cfg = _write(tmp_path / "elsewhere" / "cfg.yaml", "shell: disabled\n")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(env_cfg))
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)

    committed.write_text("shell: unrestricted\n", encoding="utf-8")
    assert_config_unchanged(snapshot)


def test_switching_env_selected_file_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _write(tmp_path / "a.yaml", "shell: disabled\n")
    second = _write(tmp_path / "b.yaml", "shell: disabled\n")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(first))
    before = config_yaml_hash(root=tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(second))
    assert config_yaml_hash(root=tmp_path) != before


def test_local_overlay_hashed_off_ci_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / ".mergecraft" / "config.yaml", "shell: restricted\n")
    local = _write(tmp_path / ".mergecraft" / "config.local.yaml", "shell: disabled\n")
    off_ci = config_yaml_hash(root=tmp_path)
    local.write_text("shell: unrestricted\n", encoding="utf-8")
    assert config_yaml_hash(root=tmp_path) != off_ci

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    on_ci = config_yaml_hash(root=tmp_path)
    local.write_text("shell: disabled\n", encoding="utf-8")
    assert config_yaml_hash(root=tmp_path) == on_ci


def test_missing_env_config_differs_from_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = config_yaml_hash(root=tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(tmp_path / "missing.yaml"))
    assert config_yaml_hash(root=tmp_path) != plain


def test_unreadable_config_fails_closed(tmp_path: Path) -> None:
    cfg = _write(tmp_path / ".mergecraft" / "config.yaml", "shell: disabled\n")
    cfg.chmod(0o000)
    try:
        if os.access(cfg, os.R_OK):
            pytest.skip("running as a user that ignores file modes")
        with pytest.raises(ValueError, match="cannot hash config file"):
            config_yaml_hash(root=tmp_path)
    finally:
        cfg.chmod(0o600)
