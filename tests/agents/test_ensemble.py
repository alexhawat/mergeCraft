"""AP3 ensemble dispatch suite — parallel models, shadow, and cardinality guards.

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP3).
Covers ``mergecraft.agents.ensemble`` — ``dispatch`` modes ``single`` (default),
``ensemble``, and ``shadow`` (reusing ``evidence/shadow.py`` record machinery).
Locked decision **D7**: orchestrator cannot be ensembled.

AP3.1: six tests; all ``xfail`` until AP3.2.
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

_ENSEMBLE_OVERRIDE = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    dispatch: ensemble
    modelChain:
      - anthropic/claude-sonnet
      - openai/gpt-5.3-codex
    budget: 2
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
def test_ensemble_runs_the_same_agent_on_two_models(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``dispatch: ensemble`` runs one binding on two models from its chain."""
    from mergecraft.agents.ensemble import plan_ensemble_models, run_ensemble_dispatch

    from mergecraft.agents.registry import AgentRole

    _stub_slug_runnability(monkeypatch)
    _write_config(tmp_path, _ENSEMBLE_OVERRIDE)
    settings = load_repo_settings(root=tmp_path)
    registry = _load_registry(tmp_path)
    reviewer = registry.resolve_role(AgentRole.reviewer)
    assert reviewer.dispatch == "ensemble"

    primary, secondary = plan_ensemble_models(reviewer, settings=settings)
    assert primary != secondary

    calls: list[str] = []

    def _execute(*, model: str, **_kwargs: object) -> list[dict[str, object]]:
        calls.append(model)
        return [{"path": "pkg/a.go", "body": f"finding from {model}", "severity": "Major"}]

    run = run_ensemble_dispatch(
        reviewer,
        registry=registry,
        settings=settings,
        execute=_execute,
    )
    assert set(calls) == {primary, secondary}
    assert len(run.model_runs) == 2
    assert run.model_runs[0].model in {primary, secondary}
    assert run.model_runs[1].model in {primary, secondary}


@_AP3_XFAIL
def test_agreement_raises_confidence(tmp_path: Path) -> None:
    """When both ensemble models agree, the merged signal gains confidence."""
    from mergecraft.agents.ensemble import EnsembleRun, ModelRun, reconcile_ensemble

    shared_finding = {
        "path": "pkg/auth.go",
        "body": "nil deref when session expires",
        "severity": "Critical",
        "line": 88,
    }
    run = EnsembleRun(
        agent_id="mergecraft-reviewer",
        model_runs=(
            ModelRun(model="anthropic/claude-sonnet", findings=(shared_finding,)),
            ModelRun(model="openai/gpt-5.3-codex", findings=(shared_finding,)),
        ),
    )
    reconciliation = reconcile_ensemble(run)
    assert reconciliation.agreement is True
    assert reconciliation.confidence_boost > 0
    assert len(reconciliation.merged_findings) == 1


@_AP3_XFAIL
def test_disagreement_is_routed_to_the_judge(tmp_path: Path) -> None:
    """Disagreeing ensemble outputs escalate to the judge role."""
    from mergecraft.agents.ensemble import EnsembleRun, ModelRun, reconcile_ensemble

    run = EnsembleRun(
        agent_id="mergecraft-reviewer",
        model_runs=(
            ModelRun(
                model="anthropic/claude-sonnet",
                findings=(
                    {
                        "path": "pkg/auth.go",
                        "body": "race on session refresh",
                        "severity": "Major",
                    },
                ),
            ),
            ModelRun(
                model="openai/gpt-5.3-codex",
                findings=(
                    {
                        "path": "pkg/auth.go",
                        "body": "benign logging noise",
                        "severity": "Minor",
                    },
                ),
            ),
        ),
    )
    reconciliation = reconcile_ensemble(run)
    assert reconciliation.agreement is False
    assert reconciliation.judge_dispatch is not None
    assert reconciliation.judge_dispatch.role == "judge"
    assert "race on session refresh" in reconciliation.judge_dispatch.brief
    assert "benign logging noise" in reconciliation.judge_dispatch.brief


@_AP3_XFAIL
def test_shadow_model_output_is_recorded_but_never_acted_on(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``dispatch: shadow`` records alternate output without changing the primary result."""
    from mergecraft.agents.ensemble import run_shadow_dispatch

    from mergecraft.agents.registry import AgentRole
    from mergecraft.evidence.shadow import load_shadow_records

    _stub_slug_runnability(monkeypatch)
    body = (
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    dispatch: shadow
    modelChain:
      - anthropic/claude-sonnet
      - openai/gpt-5.3-codex
"""
    )
    _write_config(tmp_path, body)
    settings = load_repo_settings(root=tmp_path)
    registry = _load_registry(tmp_path)
    reviewer = registry.resolve_role(AgentRole.reviewer)
    shadow_path = tmp_path / "merge-evidence-shadow.jsonl"

    primary_findings = [{"path": "pkg/a.go", "body": "primary only", "severity": "Major"}]
    shadow_findings = [{"path": "pkg/b.go", "body": "shadow only", "severity": "Critical"}]

    def _execute(*, model: str, primary: bool, **_kwargs: object) -> list[dict[str, object]]:
        return primary_findings if primary else shadow_findings

    result = run_shadow_dispatch(
        reviewer,
        registry=registry,
        settings=settings,
        execute=_execute,
        record_path=shadow_path,
    )
    assert result.primary_findings == primary_findings
    assert result.acted_findings == primary_findings
    records = load_shadow_records(shadow_path)
    assert len(records) == 1
    assert records[0].metadata["shadow_model_findings"] == shadow_findings


@_AP3_XFAIL
def test_orchestrator_cannot_be_ensembled(tmp_path: Path) -> None:
    """D7 — ensemble/shadow apply to discovery and verification agents only."""
    from mergecraft.agents.ensemble import EnsembleCardinalityError, validate_ensemble_eligible

    from mergecraft.agents.registry import AgentRole

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    orchestrator = registry.resolve_role(AgentRole.orchestrator)
    with pytest.raises(EnsembleCardinalityError, match="orchestrator"):
        validate_ensemble_eligible(orchestrator)


@_AP3_XFAIL
def test_ensemble_respects_the_agent_budget(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensemble fan-out honours the binding budget (file 2 CC3 integration)."""
    from mergecraft.agents.ensemble import run_ensemble_dispatch

    from mergecraft.agents.registry import AgentRole

    _stub_slug_runnability(monkeypatch)
    _write_config(tmp_path, _ENSEMBLE_OVERRIDE)
    settings = load_repo_settings(root=tmp_path)
    registry = _load_registry(tmp_path)
    reviewer = registry.resolve_role(AgentRole.reviewer)
    assert reviewer.budget == 2

    def _execute(*, model: str, **_kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "path": f"pkg/{model.replace('/', '-')}.go",
                "body": f"finding from {model}",
                "severity": "Major",
            }
            for _ in range(5)
        ]

    run = run_ensemble_dispatch(
        reviewer,
        registry=registry,
        settings=settings,
        execute=_execute,
    )
    total_findings = sum(len(model_run.findings) for model_run in run.model_runs)
    assert total_findings <= reviewer.budget
