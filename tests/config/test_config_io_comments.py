"""W2 regression — refuse config writes that would destroy YAML comments."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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


# ── CF2.5 — ``patch_config_dict`` replaces a top-level block in place ────────
#
# ``patch_config_dict`` used to call ``append_config_mapping`` whenever the file
# had any ``#`` line. That concatenated a fresh block at the bottom, so a second
# ``agents:`` (or ``tracing:``) landed after the original and PyYAML kept the
# last one: the write silently discarded everything the consumer already had and
# the file grew on every call. The contract is now: replace the existing
# top-level block in place, append only when the key is absent, and leave every
# comment line outside the replaced block untouched.


def _top_level_key_count(raw: str, key: str) -> int:
    return raw.count(f"\n{key}:") + (1 if raw.startswith(f"{key}:") else 0)


_COMMENTED_AGENTS = """\
# top-of-file note
model: anthropic/claude-sonnet

agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet

# trailing note belongs to tracing
tracing:
  enabled: true
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_patch_config_dict_replaces_commented_block_in_place(tmp_path: Path) -> None:
    """One write of an existing ``agents:`` block leaves exactly one key."""
    from mergecraft.config.io import patch_config_dict

    path = _write(tmp_path, _COMMENTED_AGENTS)
    patch_config_dict(path, {"agents": {"reviewer": {"modelChain": ["openai/gpt-5.3-codex"]}}})
    raw = path.read_text(encoding="utf-8")
    assert _top_level_key_count(raw, "agents") == 1, f"duplicate agents key:\n{raw}"
    assert "# top-of-file note" in raw
    assert "# trailing note belongs to tracing" in raw
    loaded = yaml.safe_load(raw)
    assert loaded["agents"]["reviewer"]["modelChain"] == ["openai/gpt-5.3-codex"]
    assert loaded["model"] == "anthropic/claude-sonnet"
    assert loaded["tracing"] == {"enabled": True}


def test_patch_config_dict_twice_leaves_one_agents_key(tmp_path: Path) -> None:
    """Repeated writes never accumulate a second copy of the replaced key."""
    from mergecraft.config.io import patch_config_dict

    path = _write(tmp_path, _COMMENTED_AGENTS)
    patch_config_dict(path, {"agents": {"reviewer": {"modelChain": ["openai/gpt-5.3-codex"]}}})
    patch_config_dict(path, {"agents": {"reviewer": {"modelChain": ["anthropic/claude-opus"]}}})
    raw = path.read_text(encoding="utf-8")
    assert _top_level_key_count(raw, "agents") == 1, f"duplicate agents key:\n{raw}"
    loaded = yaml.safe_load(raw)
    assert loaded["agents"]["reviewer"]["modelChain"] == ["anthropic/claude-opus"]


def test_patch_config_dict_appends_only_when_key_absent(tmp_path: Path) -> None:
    """Absent keys are appended once; the consumer's comments survive."""
    from mergecraft.config.io import patch_config_dict

    body = "# keep me\nmodel: anthropic/claude-sonnet\n"
    path = _write(tmp_path, body)
    patch_config_dict(path, {"tracing": {"enabled": True}})
    patch_config_dict(path, {"tracing": {"enabled": False}})
    raw = path.read_text(encoding="utf-8")
    assert _top_level_key_count(raw, "tracing") == 1, f"duplicate tracing key:\n{raw}"
    assert "# keep me" in raw
    assert yaml.safe_load(raw)["tracing"] == {"enabled": False}


def test_patch_config_dict_preserves_comments_outside_replaced_block(tmp_path: Path) -> None:
    """Every comment line outside the replaced block is byte-for-byte preserved."""
    from mergecraft.config.io import patch_config_dict

    path = _write(tmp_path, _COMMENTED_AGENTS)
    patch_config_dict(path, {"agents": {"reviewer": {"modelChain": ["openai/gpt-5.3-codex"]}}})
    raw = path.read_text(encoding="utf-8")
    outside = [
        "# top-of-file note",
        "# trailing note belongs to tracing",
    ]
    for comment in outside:
        assert comment in raw, f"comment outside the replaced block was dropped: {comment!r}"
