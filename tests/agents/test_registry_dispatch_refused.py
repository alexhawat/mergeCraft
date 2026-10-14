"""``dispatch: ensemble | shadow`` is refused, not silently accepted.

The key was validated, merged into the binding and read by nothing, so an
operator could believe a second reviewer was shadowing the run. Agent
resolution refuses the unimplemented modes with a config error that names the
mode; ``single`` and an omitted key still resolve.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.agents.registry import AgentRole, RegistryValidationError, load_registry
from mergecraft.config.settings import load_repo_settings

_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
"""
_AGENT_KEY = "shadow-reviewer"


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _load(tmp_path: Path) -> object:
    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


@pytest.mark.parametrize("mode", ["ensemble", "shadow"])
def test_unimplemented_dispatch_mode_is_refused(tmp_path: Path, mode: str) -> None:
    """An agent entry naming an unimplemented mode is refused, naming the mode."""
    _write_config(
        tmp_path,
        _MODELS_YAML
        + f"""
agents:
  {_AGENT_KEY}:
    role: reviewer
    dispatch: {mode}
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    with pytest.raises(RegistryValidationError, match=mode) as excinfo:
        _load(tmp_path)
    message = str(excinfo.value).casefold()
    assert "dispatch" in message
    assert "not implemented" in message or "unsupported" in message

    # Surviving surface: the same entry resolves once dispatch is omitted.
    _write_config(
        tmp_path,
        _MODELS_YAML
        + f"""
agents:
  {_AGENT_KEY}:
    role: reviewer
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    omitted = _load(tmp_path).resolve_role(AgentRole.reviewer)
    assert omitted.dispatch == "single"

    # Surviving surface: an explicit ``single`` is accepted as well.
    _write_config(
        tmp_path,
        _MODELS_YAML
        + f"""
agents:
  {_AGENT_KEY}:
    role: reviewer
    dispatch: single
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    explicit = _load(tmp_path).resolve_role(AgentRole.reviewer)
    assert explicit.dispatch == "single"
