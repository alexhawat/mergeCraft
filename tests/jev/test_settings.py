"""J1.1 — ``jev:`` block defaults and credential-absent skip (D4, D8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.jev.support import PACK_IDS, PINNED_MODEL

if TYPE_CHECKING:
    from pathlib import Path


def test_default_settings_jev_is_disabled() -> None:
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    assert settings.jev.enabled is False
    assert settings.jev.model == PINNED_MODEL
    assert settings.jev.budget_tokens > 0


def test_absent_config_file_does_not_enable_jev(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(tmp_path / "missing.yaml", load_learnings_files=False)
    assert settings.jev.enabled is False


def test_explicit_jev_enabled_flip_is_opt_in(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    path = tmp_path / "config.yaml"
    path.write_text(
        "push: restricted\nshell: restricted\njev:\n  enabled: true\n",
        encoding="utf-8",
    )
    settings = load_repo_settings(path, load_learnings_files=False)
    assert settings.jev.enabled is True
    assert settings.jev.model == PINNED_MODEL


def test_per_pack_toggles_default_on_for_every_versioned_pack() -> None:
    from mergecraft.config.settings import default_settings

    packs = default_settings().jev.packs
    for pack_id in PACK_IDS:
        assert packs[pack_id] is True


def test_jev_gate_defaults_to_shadow() -> None:
    from mergecraft.config.settings import GatesSettings

    assert GatesSettings().jev == "shadow"


def test_jev_settings_model_cannot_be_floating_alias() -> None:
    from pydantic import ValidationError

    from mergecraft.config.settings import JevSettings

    with pytest.raises(ValidationError, match="floating alias"):
        JevSettings(enabled=True, model="jev-latest")
    with pytest.raises(ValidationError, match="floating alias"):
        JevSettings(enabled=True, model="jev-preview")


def test_jev_settings_rejects_unpinned_version_id() -> None:
    """D8: a versioned id that is not the pin must fail closed."""
    from pydantic import ValidationError

    from mergecraft.config.settings import JevSettings

    with pytest.raises(ValidationError, match=r"pinned id jev-1\.13\.0"):
        JevSettings(model="jev-1.14.0")


def test_config_yaml_rejects_unpinned_jev_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D8: ``.mergecraft/config.yaml`` cannot load an unpinned ``jev.model``."""
    from pydantic import ValidationError

    from mergecraft.config.settings import load_repo_settings

    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "push: restricted\nshell: restricted\njev:\n  model: jev-1.14.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match=r"pinned id jev-1\.13\.0"):
        load_repo_settings(root=tmp_path, load_learnings_files=False)


def test_jev_settings_accepts_pinned_model() -> None:
    from mergecraft.config.settings import JevSettings

    settings = JevSettings(model="jev-1.13.0")
    assert settings.model == PINNED_MODEL
