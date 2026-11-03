"""Tests for layered config loading (D2 / W4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.config.layered import load_layered_config_dict, merge_config_dicts

if TYPE_CHECKING:
    import pytest


def test_merge_config_dicts_deep_merges_agents() -> None:
    merged = merge_config_dicts(
        {"agents": {"reviewer": {"modelChain": ["anthropic/claude-sonnet"]}}},
        {"agents": {"reviewer": {"modelChain": ["openai/gpt-5.3-codex"]}}},
    )
    assert merged["agents"]["reviewer"]["modelChain"] == ["openai/gpt-5.3-codex"]


def test_load_layered_config_dict_merges_local_overlay(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "agents:\n  reviewer:\n    modelChain:\n      - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )
    (cfg_dir / "config.local.yaml").write_text(
        "agents:\n  reviewer:\n    modelChain:\n      - openai/gpt-5.3-codex\n",
        encoding="utf-8",
    )
    loaded = load_layered_config_dict(root=tmp_path)
    assert loaded["agents"]["reviewer"]["modelChain"] == ["openai/gpt-5.3-codex"]


# ── CF3.1 — one resolver reports the contributing files (CF-D9) ─────────────
#
# Four code paths resolved "the config file" four ways, so ``doctor`` could
# diagnose a config the local review never ran with. ``resolve_config_sources``
# is the single read-view resolver: it returns the contributing files in
# precedence order (lowest first) plus a flag for a ``MERGECRAFT_CONFIG`` that
# points at a file that does not exist.


def _sources(tmp_path: Path):
    from mergecraft.config.layered import resolve_config_sources

    return resolve_config_sources(tmp_path)


def _names(sources) -> tuple[str, ...]:
    return tuple(Path(path).name for path in sources.files)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def _write_pair(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text("model: anthropic/claude-sonnet\n", encoding="utf-8")
    (cfg_dir / "config.local.yaml").write_text("model: openai/gpt-5.3-codex\n", encoding="utf-8")


def test_resolve_config_sources_lists_committed_and_local(tmp_path: Path, monkeypatch) -> None:
    """Off CI the local overlay contributes, lowest precedence first."""
    _clear_env(monkeypatch)
    _write_pair(tmp_path)
    sources = _sources(tmp_path)
    assert _names(sources) == ("config.yaml", "config.local.yaml")
    assert sources.env_config_missing is False
    assert all(Path(path).is_absolute() for path in sources.files)
    assert sources.files[0].parent == (tmp_path / ".mergecraft").resolve()


def test_resolve_config_sources_omits_local_on_ci(tmp_path: Path, monkeypatch) -> None:
    """In GitHub Actions the local overlay never contributes."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _write_pair(tmp_path)
    sources = _sources(tmp_path)
    assert _names(sources) == ("config.yaml",)
    assert sources.env_config_missing is False


def test_resolve_config_sources_env_file_is_the_only_contributor(
    tmp_path: Path, monkeypatch
) -> None:
    """A present ``MERGECRAFT_CONFIG`` short-circuits committed and local."""
    _clear_env(monkeypatch)
    _write_pair(tmp_path)
    env_config = tmp_path / "elsewhere.yaml"
    env_config.write_text("model: nous/tencent/hy3\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(env_config))
    sources = _sources(tmp_path)
    assert _names(sources) == ("elsewhere.yaml",)
    assert sources.env_config_missing is False


def test_resolve_config_sources_flags_missing_env_file(tmp_path: Path, monkeypatch) -> None:
    """A missing ``MERGECRAFT_CONFIG`` is flagged, not silently ignored."""
    _clear_env(monkeypatch)
    _write_pair(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(tmp_path / "nope.yaml"))
    sources = _sources(tmp_path)
    assert sources.env_config_missing is True
    assert _names(sources) == ("config.yaml", "config.local.yaml")


def test_resolve_config_sources_empty_repo(tmp_path: Path, monkeypatch) -> None:
    """No committed file, no local overlay, no env file: nothing contributes."""
    _clear_env(monkeypatch)
    sources = _sources(tmp_path)
    assert sources.files == ()
    assert sources.env_config_missing is False


# ── MERGECRAFT_CONFIG: the locator read, through a model (49b) ──────────────
#
# The locator is an env *layer* read: the merge arithmetic stays in the
# resolver, the parse moves into ``ConfigLocatorEnv``. An empty value means
# "absent" (it already does today), and a whitespace-only value is still
# "present but not a file", so the doctor keeps reporting it — a frozen quirk,
# not a bug to fix here.


def test_resolve_config_sources_empty_env_config_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MERGECRAFT_CONFIG=""`` resolves exactly like an unset variable."""
    _clear_env(monkeypatch)
    _write_pair(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", "")
    sources = _sources(tmp_path)
    assert _names(sources) == ("config.yaml", "config.local.yaml")
    assert sources.env_config_missing is False


def test_resolve_config_sources_blank_env_config_is_flagged_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whitespace-only value stays "present but missing" — today's behaviour."""
    _clear_env(monkeypatch)
    _write_pair(tmp_path)
    monkeypatch.setenv("MERGECRAFT_CONFIG", "   ")
    sources = _sources(tmp_path)
    assert sources.env_config_missing is True


def test_load_layered_config_dict_empty_env_config_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The layered loader treats an empty locator as unset too."""
    _clear_env(monkeypatch)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("model: anthropic/claude-sonnet\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", "")
    loaded = load_layered_config_dict(root=tmp_path)
    assert loaded["model"] == "anthropic/claude-sonnet"


def _config_locator_env():
    from mergecraft.config.env import ConfigLocatorEnv

    return ConfigLocatorEnv


def _located_field() -> str:
    model = _config_locator_env()
    for name, field in model.model_fields.items():
        if field.validation_alias == "MERGECRAFT_CONFIG":
            return name
    raise AssertionError("ConfigLocatorEnv does not declare MERGECRAFT_CONFIG")


def test_config_locator_env_declares_the_exact_name() -> None:
    """``ConfigLocatorEnv`` names ``MERGECRAFT_CONFIG`` exactly, with no prefix arithmetic."""
    model = _config_locator_env()
    declared = {
        field.validation_alias
        for field in model.model_fields.values()
        if isinstance(field.validation_alias, str)
    }
    assert declared == {"MERGECRAFT_CONFIG"}, declared


def test_config_locator_env_keeps_the_empty_value_rule() -> None:
    """An empty value is absent; a whitespace-only value is still present."""
    model = _config_locator_env()
    field_name = _located_field()

    assert getattr(model.from_env({"MERGECRAFT_CONFIG": ""}), field_name) is None
    assert getattr(model.from_env({}), field_name) is None
    assert getattr(model.from_env({"MERGECRAFT_CONFIG": "   "}), field_name) is not None
    assert (
        getattr(model.from_env({"MERGECRAFT_CONFIG": "/tmp/x.yaml"}), field_name) == "/tmp/x.yaml"
    )


def test_config_locator_env_reads_nothing_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mapping-only read never falls back to ``os.environ``."""
    model = _config_locator_env()
    field_name = _located_field()
    monkeypatch.setenv("MERGECRAFT_CONFIG", "/tmp/from-process-env.yaml")

    assert getattr(model.from_env({}), field_name) is None
