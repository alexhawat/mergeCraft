"""AP3 ensemble dispatch suite — parallel models, shadow, and cardinality guards.

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP3).
Covers ``mergecraft.agents.ensemble`` — ``dispatch`` modes ``single`` (default),
``ensemble``, and ``shadow`` (reusing ``evidence/shadow.py`` record machinery).
Locked decision **D7**: orchestrator cannot be ensembled.

AP3.1: seven tests; green after AP3.2. #238 pins empty-vs-empty as agreement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

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


def test_empty_vs_empty_is_agreement_without_confidence_boost(tmp_path: Path) -> None:
    """Two empty finding sets agree without a confidence boost or judge dispatch."""
    from mergecraft.agents.ensemble import EnsembleRun, ModelRun, reconcile_ensemble

    run = EnsembleRun(
        agent_id="mergecraft-reviewer",
        model_runs=(
            ModelRun(model="anthropic/claude-sonnet", findings=()),
            ModelRun(model="openai/gpt-5.3-codex", findings=()),
        ),
    )
    reconciliation = reconcile_ensemble(run)
    assert reconciliation.agreement is True
    assert reconciliation.confidence_boost == 0
    assert reconciliation.judge_dispatch is None
    assert reconciliation.merged_findings == ()


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


def test_orchestrator_cannot_be_ensembled(tmp_path: Path) -> None:
    """D7 — ensemble/shadow apply to discovery and verification agents only."""
    from mergecraft.agents.ensemble import EnsembleCardinalityError, validate_ensemble_eligible
    from mergecraft.agents.registry import AgentRole

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    orchestrator = registry.resolve_role(AgentRole.orchestrator)
    with pytest.raises(EnsembleCardinalityError, match="orchestrator"):
        validate_ensemble_eligible(orchestrator)


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


# ---------------------------------------------------------------------------
# W14.3 / #262 — the disagreement path drops secondary-only findings (D15)
# ---------------------------------------------------------------------------
#
# ``reconcile_ensemble`` returns ``merged_findings=tuple(left.findings)`` when
# the two key sets differ, so anything only the right-hand model found exists
# nowhere except the judge brief. D15: union left+right by ``_finding_key``,
# keep ``judge_dispatch``.

_LEFT_ONLY = {
    "path": "pkg/auth.go",
    "body": "race on session refresh",
    "severity": "Major",
    "line": 41,
}
_RIGHT_ONLY = {
    "path": "pkg/billing.go",
    "body": "refund can be applied twice",
    "severity": "Critical",
    "line": 88,
}
_SHARED = {
    "path": "pkg/store.go",
    "body": "unchecked error on write",
    "severity": "Major",
    "line": 12,
}


def _disagreeing_run(
    left: tuple[dict[str, object], ...],
    right: tuple[dict[str, object], ...],
) -> object:
    from mergecraft.agents.ensemble import EnsembleRun, ModelRun

    return EnsembleRun(
        agent_id="mergecraft-reviewer",
        model_runs=(
            ModelRun(model="anthropic/claude-sonnet", findings=left),
            ModelRun(model="openai/gpt-5.3-codex", findings=right),
        ),
    )


def _keys(rows: tuple[dict[str, object], ...]) -> set[tuple[str, str]]:
    from mergecraft.agents.ensemble import _finding_key

    return {_finding_key(row) for row in rows}


@pytest.mark.xfail(
    reason="green after W17: disagreement returns left.findings only, dropping right-only rows",
    strict=False,
)
def test_disagreement_keeps_a_right_only_finding(tmp_path: Path) -> None:
    """#262 / D15 — a finding only the secondary model reported must survive."""
    from mergecraft.agents.ensemble import _finding_key, reconcile_ensemble

    reconciliation = reconcile_ensemble(_disagreeing_run((_LEFT_ONLY,), (_RIGHT_ONLY,)))

    assert reconciliation.agreement is False
    assert _finding_key(_RIGHT_ONLY) in _keys(reconciliation.merged_findings)


@pytest.mark.xfail(
    reason="green after W17: the union must carry both sides' exclusive findings",
    strict=False,
)
def test_disagreement_unions_both_sides(tmp_path: Path) -> None:
    """The merge is a union, not a swap: neither side may be dropped.

    Pinning both directions stops a fix that simply returns
    ``right.findings`` instead of ``left.findings``.
    """
    from mergecraft.agents.ensemble import _finding_key, reconcile_ensemble

    reconciliation = reconcile_ensemble(
        _disagreeing_run((_SHARED, _LEFT_ONLY), (_SHARED, _RIGHT_ONLY))
    )

    merged_keys = _keys(reconciliation.merged_findings)
    assert _finding_key(_LEFT_ONLY) in merged_keys
    assert _finding_key(_RIGHT_ONLY) in merged_keys
    assert _finding_key(_SHARED) in merged_keys


@pytest.mark.xfail(
    reason="green after W17: the union must deduplicate by _finding_key, not concatenate",
    strict=False,
)
def test_disagreement_union_deduplicates_a_shared_finding(tmp_path: Path) -> None:
    """A finding both models reported appears once, not twice.

    ``tuple(left.findings) + tuple(right.findings)`` would satisfy the two
    tests above while double-reporting every corroborated finding to the
    reviewer — the failure mode this arm exists to block.
    """
    from mergecraft.agents.ensemble import _finding_key, reconcile_ensemble

    reconciliation = reconcile_ensemble(
        _disagreeing_run((_SHARED, _LEFT_ONLY), (_SHARED, _RIGHT_ONLY))
    )

    merged = reconciliation.merged_findings
    assert len(merged) == 3
    shared_key = _finding_key(_SHARED)
    assert sum(1 for row in merged if _finding_key(row) == shared_key) == 1


@pytest.mark.xfail(
    reason="green after W17: an empty left side must not swallow the right side's findings",
    strict=False,
)
def test_disagreement_with_an_empty_left_side_keeps_the_right_findings(tmp_path: Path) -> None:
    """The worst case: the primary model found nothing, the secondary found a Critical.

    Today ``merged_findings`` is ``()`` — a Critical the ensemble paid for is
    invisible outside the judge brief.
    """
    from mergecraft.agents.ensemble import _finding_key, reconcile_ensemble

    reconciliation = reconcile_ensemble(_disagreeing_run((), (_RIGHT_ONLY,)))

    assert reconciliation.agreement is False
    assert _keys(reconciliation.merged_findings) == {_finding_key(_RIGHT_ONLY)}


def test_disagreement_still_dispatches_the_judge(tmp_path: Path) -> None:
    """Green guard (D15): the union must not replace the judge escalation.

    D15 is explicit that ``judge_dispatch`` stays — the union exists so the
    right-only finding is not *only* in the brief, not so the brief goes away.
    """
    from mergecraft.agents.ensemble import reconcile_ensemble

    reconciliation = reconcile_ensemble(_disagreeing_run((_LEFT_ONLY,), (_RIGHT_ONLY,)))

    assert reconciliation.agreement is False
    assert reconciliation.judge_dispatch is not None
    assert reconciliation.judge_dispatch.role == "judge"
    assert str(_LEFT_ONLY["body"]) in reconciliation.judge_dispatch.brief
    assert str(_RIGHT_ONLY["body"]) in reconciliation.judge_dispatch.brief


def test_disagreement_claims_no_confidence_boost(tmp_path: Path) -> None:
    """Green guard: unioning is not corroboration — no boost on disagreement."""
    from mergecraft.agents.ensemble import reconcile_ensemble

    reconciliation = reconcile_ensemble(_disagreeing_run((_LEFT_ONLY,), (_RIGHT_ONLY,)))

    assert reconciliation.confidence_boost == 0.0


def test_agreement_path_is_untouched_by_the_union(tmp_path: Path) -> None:
    """Green guard: identical key sets keep one copy and the boost (#238)."""
    from mergecraft.agents.ensemble import reconcile_ensemble

    reconciliation = reconcile_ensemble(_disagreeing_run((_SHARED,), (_SHARED,)))

    assert reconciliation.agreement is True
    assert reconciliation.confidence_boost > 0
    assert len(reconciliation.merged_findings) == 1
    assert reconciliation.judge_dispatch is None


def test_single_model_run_is_returned_unmerged(tmp_path: Path) -> None:
    """Green guard: a one-model run short-circuits before the union."""
    from mergecraft.agents.ensemble import EnsembleRun, ModelRun, reconcile_ensemble

    run = EnsembleRun(
        agent_id="mergecraft-reviewer",
        model_runs=(ModelRun(model="anthropic/claude-sonnet", findings=(_LEFT_ONLY,)),),
    )
    reconciliation = reconcile_ensemble(run)

    assert reconciliation.agreement is True
    assert len(reconciliation.merged_findings) == 1
