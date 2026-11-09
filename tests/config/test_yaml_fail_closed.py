"""#1249 / #1250 - unparseable and duplicate-key config files fail closed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from mergecraft.config.io import load_config_dict
from mergecraft.config.layered import load_layered_config_dict
from mergecraft.config.settings import load_repo_settings
from mergecraft.config.yaml_unique import ConfigParseError, safe_load_unique

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def _committed(root: Path, body: str) -> Path:
    path = root / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_syntax_error_after_strict_setting_does_not_widen(tmp_path: Path) -> None:
    _committed(tmp_path, "shell: disabled\nanalyzers: [oops\n")
    with pytest.raises(ConfigParseError, match="config parse error") as ei:
        load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert "disabled" not in str(ei.value)
    assert "oops" not in str(ei.value)


def test_explicit_path_syntax_error_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("shell: disabled\nx: [oops\n", encoding="utf-8")
    with pytest.raises(ConfigParseError, match=r"bad\.yaml"):
        load_repo_settings(path=bad, load_learnings_files=False)


def test_env_selected_syntax_error_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "env.yaml"
    bad.write_text("x: [oops\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(bad))
    with pytest.raises(ConfigParseError):
        load_layered_config_dict(root=tmp_path)


def test_local_overlay_syntax_error_fails_closed(tmp_path: Path) -> None:
    _committed(tmp_path, "shell: disabled\n")
    (tmp_path / ".mergecraft" / "config.local.yaml").write_text("x: [oops\n", encoding="utf-8")
    with pytest.raises(ConfigParseError):
        load_layered_config_dict(root=tmp_path)


def test_valid_config_still_loads(tmp_path: Path) -> None:
    _committed(tmp_path, "shell: disabled\n")
    assert load_repo_settings(root=tmp_path, load_learnings_files=False).shell == "disabled"


def test_duplicate_top_level_key_is_rejected(tmp_path: Path) -> None:
    _committed(tmp_path, "shell: disabled\npush: disabled\nshell: unrestricted\n")
    with pytest.raises(ConfigParseError, match=r"duplicate key 'shell' at line 3") as ei:
        load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert "unrestricted" not in str(ei.value)


def test_duplicate_nested_key_is_rejected(tmp_path: Path) -> None:
    _committed(tmp_path, "gates:\n  gate_action: enforce\n  gate_action: shadow\n")
    with pytest.raises(ConfigParseError, match=r"duplicate key 'gate_action' at line 3"):
        load_layered_config_dict(root=tmp_path)


def test_duplicate_key_in_explicit_path_and_io_loader(tmp_path: Path) -> None:
    bad = tmp_path / "dup.yaml"
    bad.write_text("a: 1\na: 2\n", encoding="utf-8")
    with pytest.raises(ConfigParseError):
        load_repo_settings(path=bad, load_learnings_files=False)
    with pytest.raises(yaml.YAMLError, match="duplicate key 'a' at line 2"):
        load_config_dict(bad)


def test_distinct_and_repeated_values_are_fine() -> None:
    assert safe_load_unique("a: 1\nb:\n  a: 1\nc: [{a: 1}, {a: 2}]\n") == {
        "a": 1,
        "b": {"a": 1},
        "c": [{"a": 1}, {"a": 2}],
    }
