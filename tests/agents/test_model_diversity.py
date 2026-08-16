"""AP3 model diversity suite — verification never shares the authoring family.

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP3).
Covers ``mergecraft.agents.model_diversity`` — generalizes #45 /
``PINNED_JUDGE_MODELS`` from a single hard-coded Claude entry into a
declared policy that holds for every harness.

AP3.1: two tests; all ``xfail`` until AP3.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_AP3_XFAIL = pytest.mark.xfail(reason="AP3.2", strict=True)

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""

_SAME_FAMILY_OVERRIDE = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    model: anthropic/claude-sonnet
  verifier:
    model: anthropic/claude-haiku
"""


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _load_registry(tmp_path: Path) -> object:
    from mergecraft.agents.registry import load_registry

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def _stub_slug_runnability(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve.has_credentials_for_slug",
        lambda _slug: True,
    )
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )


@_AP3_XFAIL
def test_verification_never_runs_on_the_authoring_family(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """#45 generalized — verifier must not share the reviewer's provider family."""
    from mergecraft.agents.model_diversity import (
        ModelDiversityViolation,
        assert_verification_diverse,
        resolve_diverse_verification_model,
    )

    from mergecraft.agents.registry import AgentRole, resolve_agent_model

    _stub_slug_runnability(monkeypatch)
    _write_config(tmp_path, _SAME_FAMILY_OVERRIDE)
    settings = load_repo_settings(root=tmp_path)
    registry = _load_registry(tmp_path)
    reviewer = registry.resolve_role(AgentRole.reviewer)
    verifier = registry.resolve_role(AgentRole.verifier)
    reviewer_model = resolve_agent_model(reviewer, settings=settings).dispatched_model
    verifier_model = resolve_agent_model(verifier, settings=settings).dispatched_model

    with pytest.raises(ModelDiversityViolation, match="authoring family"):
        assert_verification_diverse(
            authoring_slug=reviewer_model,
            verification_slug=verifier_model,
        )

    diverse = resolve_diverse_verification_model(
        authoring_slug=reviewer_model,
        registry=registry,
        settings=settings,
    )
    assert diverse.dispatched_model != reviewer_model
    assert_verification_diverse(
        authoring_slug=reviewer_model,
        verification_slug=diverse.dispatched_model,
    )


@_AP3_XFAIL
def test_policy_holds_across_harnesses(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Model-diversity policy applies for Claude, OpenCode and Codex harness contexts."""
    from mergecraft.agents.model_diversity import enforce_policy_for_harness

    _stub_slug_runnability(monkeypatch)
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    settings = load_repo_settings(root=tmp_path)
    registry = _load_registry(tmp_path)

    for harness in ("claude", "opencode", "codex"):
        enforce_policy_for_harness(registry=registry, settings=settings, harness=harness)
