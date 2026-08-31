"""W2 regression — refuse config writes that would destroy YAML comments."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.config.io import config_has_yaml_comments, write_config_dict

_COMMENTED_CONFIG = """\
# fork floor always refuses
trust:
  selfReview: 'off'
  agentSandbox: 'dispatch'
model: anthropic/claude-sonnet
push: restricted
shell: restricted
"""


def test_config_has_yaml_comments_false_when_file_missing(tmp_path: Path) -> None:
    assert config_has_yaml_comments(tmp_path / ".mergecraft" / "config.yaml") is False


def test_config_has_yaml_comments_false_without_hash_lines(tmp_path: Path) -> None:
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("trust:\n  selfReview: 'off'\n", encoding="utf-8")
    assert config_has_yaml_comments(path) is False


def test_config_has_yaml_comments_true_for_comment_line(tmp_path: Path) -> None:
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(_COMMENTED_CONFIG, encoding="utf-8")
    assert config_has_yaml_comments(path) is True


def test_write_config_dict_refuses_commented_target(tmp_path: Path) -> None:
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(_COMMENTED_CONFIG, encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match=r"refusing to rewrite|YAML comments|destroyed"):
        write_config_dict(path, {"trust": {"selfReview": "off", "agentSandbox": "never"}})
    assert path.read_text(encoding="utf-8") == before
