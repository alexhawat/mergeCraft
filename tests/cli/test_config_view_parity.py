"""CF3.2 — the read views agree about which config files contribute (D9).

Before the fix, four code paths resolved "the config file" four ways:

- the layered loader (what the review runs with) merged ``config.local.yaml``
  off CI;
- ``doctor``'s config probe ignored it and also reported a missing
  ``MERGECRAFT_CONFIG`` as "no config file (defaults apply)";
- ``config show/explain`` ignored it.

These tests pin the shared view: with a ``config.local.yaml`` present off CI,
``doctor``'s config row, ``config explain``'s YAML layer and
``load_repo_settings`` all reflect the same contributing files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.cli.config_precedence import explain_setting
from mergecraft.cli.doctor_cmd import _config_probe
from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    import pytest


def _write_views_config(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\ntracing:\n  enabled: false\n",
        encoding="utf-8",
    )
    (cfg_dir / "config.local.yaml").write_text(
        "models:\n  - openai/gpt-5.3-codex\ntracing:\n  enabled: true\n",
        encoding="utf-8",
    )


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING", raising=False)
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)


def test_doctor_config_row_lists_local_overlay(tmp_path: Path, monkeypatch) -> None:
    """The config probe names ``config.local.yaml`` when it contributes."""
    _clear_env(monkeypatch)
    _write_views_config(tmp_path)
    row = _config_probe(tmp_path)
    assert row.status == "ok", row.detail
    assert "config.yaml" in row.detail
    assert "config.local.yaml" in row.detail, (
        f"doctor ignored the local overlay it will run with: {row.detail!r}"
    )


def test_doctor_config_row_agrees_with_resolve_config_sources(tmp_path: Path, monkeypatch) -> None:
    """The probe's contributing files match the shared resolver's."""
    from mergecraft.config.layered import resolve_config_sources

    _clear_env(monkeypatch)
    _write_views_config(tmp_path)
    row = _config_probe(tmp_path)
    sources = resolve_config_sources(tmp_path)
    assert sources.files, "resolver reported no contributing files"
    for path in sources.files:
        assert Path(path).name in row.detail, (
            f"{Path(path).name} contributes but is missing from doctor's row: {row.detail!r}"
        )


def test_config_explain_yaml_layer_includes_local_overlay(tmp_path: Path, monkeypatch) -> None:
    """``config explain`` reads the merged YAML view, not just the committed file."""
    _clear_env(monkeypatch)
    _write_views_config(tmp_path)
    explained = explain_setting("tracing.enabled", cwd=tmp_path)
    assert explained["layers"]["yaml"] is True, (
        f"config explain ignored config.local.yaml: {explained!r}"
    )


def test_load_repo_settings_includes_local_overlay(tmp_path: Path, monkeypatch) -> None:
    """Guard — the loader already merges the local overlay off CI."""
    _clear_env(monkeypatch)
    _write_views_config(tmp_path)
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings.models == ["openai/gpt-5.3-codex"]


def test_doctor_names_missing_mergecraft_config(tmp_path: Path, monkeypatch) -> None:
    """A missing ``MERGECRAFT_CONFIG`` is named, never reported as defaults."""
    _clear_env(monkeypatch)
    (tmp_path / ".mergecraft").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n", encoding="utf-8"
    )
    missing = tmp_path / "nope.yaml"
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(missing))

    row = _config_probe(tmp_path)
    detail = row.detail.lower()
    assert "mergecraft_config" in detail, row.detail
    assert "nope.yaml" in detail, row.detail
    assert "defaults apply" not in detail, (
        f"doctor reported the missing env config as the committed defaults: {row.detail!r}"
    )
