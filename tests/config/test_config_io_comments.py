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


# ── CF-final — a top-level *sequence* value is a block too ───────────────────
#
# ``yaml.safe_dump`` renders every top-level sequence item at column 0
# (``models:\n- a\n- b``), unlike a mapping whose children are indented. The
# block-span reader stopped at the first zero-indented line, so it treated a
# sequence's own items as "the next top-level key": it replaced only the
# ``models:`` header line and left the previous items behind. Repeated writes
# then grew without bound and unioned the old values with the new ones — the
# exact defect this contract exists to prevent. The mapping-valued fixtures
# above never exercised the sequence shape.

_SEQUENCE_LIST_BODY = """\
# keep this note
models:
- anthropic/claude-sonnet
other: 1
"""


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "# keep this note\nmodels:\n  - anthropic/claude-sonnet\nother: 1\n",
            id="indented-sequence",
        ),
        pytest.param(_SEQUENCE_LIST_BODY, id="column-zero-sequence"),
    ],
)
def test_replace_config_block_replaces_a_whole_block_sequence(body: str) -> None:
    """A block-sequence value is replaced as a unit — no leftover items."""
    from mergecraft.config.io import replace_config_block

    result = replace_config_block(body, "models", ["nous/tencent/hy3"])
    loaded = yaml.safe_load(result)
    assert loaded["models"] == ["nous/tencent/hy3"], f"old sequence item survived:\n{result}"
    assert "anthropic/claude-sonnet" not in result, f"old item left behind:\n{result}"
    assert loaded["other"] == 1
    assert "# keep this note" in result


def test_top_level_block_span_includes_column_zero_sequence_items() -> None:
    """A column-0 ``- item`` line belongs to its key's block, not the next key."""
    from mergecraft.config.io import _top_level_block_span

    lines = ["models:\n", "- nous/a\n", "- nous/b\n", "other: 1\n"]
    assert _top_level_block_span(lines, "models") == (0, 3)


def test_replace_config_block_is_byte_stable_for_a_sequence() -> None:
    """A second identical write is a no-op, not a second copy of the items."""
    from mergecraft.config.io import replace_config_block

    body = "# keep this note\nmodels:\n  - anthropic/claude-sonnet\n"
    first = replace_config_block(body, "models", ["nous/tencent/hy3"])
    second = replace_config_block(first, "models", ["nous/tencent/hy3"])
    assert second == first, f"second write changed the file:\n{second}"
    assert yaml.safe_load(second)["models"] == ["nous/tencent/hy3"]


def test_replace_config_block_does_not_union_successive_sequence_values() -> None:
    """Two different list values in sequence leave only the later one."""
    from mergecraft.config.io import replace_config_block

    body = "# keep this note\nmodels:\n  - anthropic/claude-sonnet\n"
    first = replace_config_block(body, "models", ["nous/a"])
    second = replace_config_block(first, "models", ["nous/b"])
    assert yaml.safe_load(second)["models"] == ["nous/b"], f"values were unioned:\n{second}"


def test_replace_config_block_handles_a_one_line_sequence_value() -> None:
    """Guard — the flow form ``models: [x]`` is still a one-line block."""
    from mergecraft.config.io import replace_config_block

    body = "# keep this note\nmodels: [anthropic/claude-sonnet]\n"
    result = replace_config_block(body, "models", ["nous/a", "nous/b"])
    assert yaml.safe_load(result)["models"] == ["nous/a", "nous/b"], result
    assert "# keep this note" in result


def test_patch_config_dict_is_idempotent_for_list_values(tmp_path: Path) -> None:
    """``patch_config_dict`` on a list value is stable across repeated writes."""
    from mergecraft.config.io import patch_config_dict

    path = _write(tmp_path, "# keep this note\nmodels:\n  - anthropic/claude-sonnet\n")
    patch_config_dict(path, {"models": ["nous/tencent/hy3"]})
    first = path.read_text(encoding="utf-8")
    patch_config_dict(path, {"models": ["nous/tencent/hy3"]})
    second = path.read_text(encoding="utf-8")
    assert second == first, f"repeated write changed the file:\n{second}"
    assert yaml.safe_load(second)["models"] == ["nous/tencent/hy3"]
    assert second.count("nous/tencent/hy3") == 1, f"value duplicated:\n{second}"
