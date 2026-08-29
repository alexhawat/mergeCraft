"""W1.4 — registry multiplicity for agent roster (wave plan 11, green after W5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.cli.support_agent_roster import two_reviewer_config, write_config

from mergecraft.agents.registry import AgentRole, RegistryValidationError, load_registry
from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _load(tmp_path: Path) -> object:
    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def _reviewer_bindings(registry: object) -> list[object]:
    resolve_roles = getattr(registry, "resolve_roles", None)
    if resolve_roles is None:
        pytest.fail("Registry.resolve_roles is not implemented")
    return list(resolve_roles(AgentRole.reviewer))


def _reviewer_level_ids(registry: object) -> list[tuple[str, ...]]:
    resolve_role_levels = getattr(registry, "resolve_role_levels", None)
    if resolve_role_levels is None:
        pytest.fail("Registry.resolve_role_levels is not implemented")
    levels = resolve_role_levels(AgentRole.reviewer)
    return [tuple(binding.agent_id for binding in level) for level in levels]


def test_two_lensless_reviewer_bindings_survive_load_registry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    reviewers = _reviewer_bindings(registry)
    agent_ids = {binding.agent_id for binding in reviewers}
    assert "mergecraft-reviewer" in agent_ids or "reviewer" in registry._bindings
    assert any("reviewer2" in binding.agent_id for binding in reviewers)


def test_resolve_role_returns_binding_keyed_reviewer_not_last_wins(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    primary = registry.resolve_role(AgentRole.reviewer)
    assert primary.agent_id == "mergecraft-reviewer"
    assert "reviewer2" not in primary.agent_id


def test_resolve_roles_returns_both_reviewers_in_stable_order(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    reviewers = _reviewer_bindings(registry)
    assert len(reviewers) == 2
    ids = [binding.agent_id for binding in reviewers]
    assert ids[0] == "mergecraft-reviewer"
    assert ids[1] == "reviewer2"


def test_registry_validate_rejects_empty_model_chain(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
agents:
  reviewer2:
    role: reviewer
    modelChain: []
""",
    )
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    with pytest.raises(RegistryValidationError, match=r"empty model_chain|empty"):
        registry.validate()


def test_registry_validate_rejects_unreachable_lens(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
agents:
  lens-missing:
    lens: does-not-exist
    role: reviewer
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    with pytest.raises(RegistryValidationError, match=r"unreachable lens|lens missing trigger"):
        registry.validate()


def test_resolve_role_levels_all_parallel_one_level(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    assert _reviewer_level_ids(registry) == [
        ("mergecraft-reviewer", "reviewer2"),
    ]


def test_resolve_role_levels_full_chain_one_per_level(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
  reviewer2:
    role: reviewer
    after: reviewer
    modelChain:
      - openai/gpt-5.3-codex
  reviewer3:
    role: reviewer
    after: reviewer2
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    assert _reviewer_level_ids(registry) == [
        ("mergecraft-reviewer",),
        ("reviewer2",),
        ("reviewer3",),
    ]


def test_resolve_role_levels_diamond_two_siblings_same_level(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
  reviewer-b:
    role: reviewer
    after: reviewer
    modelChain:
      - openai/gpt-5.3-codex
  reviewer-c:
    role: reviewer
    after: reviewer
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    monkeypatch.chdir(tmp_path)
    registry = _load(tmp_path)
    assert _reviewer_level_ids(registry) == [
        ("mergecraft-reviewer",),
        ("reviewer-b", "reviewer-c"),
    ]
