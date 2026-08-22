"""Verification budget decoupled from inline placement (RC3, D2) — W2.1 RED suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.analyzers.support import INLINE_BUDGET, import_module

from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING

if TYPE_CHECKING:
    from pathlib import Path


def _critical_findings(count: int, *, prefix: str = "critical issue") -> list[object]:
    verifier = import_module("mergecraft.agents.verifier")
    return [
        verifier.AgentFinding(
            path=f"src/f{index:02d}.py",
            body=f"{prefix} {index}",
            severity="Critical",
        )
        for index in range(count)
    ]


def _learnings_with_withdrawn(fingerprint: str, *, reason: str = "False positive") -> str:
    marker = f"<!-- mergecraft-finding:v1:{fingerprint} -->"
    return f"# Learnings\n\n{WITHDRAWN_FINDINGS_HEADING}\n\n- {reason} {marker}\n"


def _resolve_verification_budget(settings: object) -> int:
    """W2.2 — ``review.verificationBudget`` with ``0`` meaning no cap."""
    review = getattr(settings, "review", None)
    assert review is not None, "review settings block is required (D2)"
    budget = review.verification_budget
    if budget == 0:
        return 0
    return budget


def test_verification_budget_defaults_to_twenty_four(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    review = getattr(settings, "review", None)
    assert review is not None
    assert review.verification_budget == 24


def test_verification_budget_zero_means_no_cap(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "review:\n  verificationBudget: 0\n",
        encoding="utf-8",
    )
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings.review.verification_budget == 0

    verifier = import_module("mergecraft.agents.verifier")
    findings = _critical_findings(30)
    plan = verifier.plan_agent_verifications(
        findings,
        budget=_resolve_verification_budget(settings),
    )
    assert len(plan.dispatch) == 30
    assert plan.skipped_over_budget == []


def test_ninth_critical_finding_is_still_verified(tmp_path: Path) -> None:
    """RC3 pin — verification depth must not be capped by inline placement (8)."""
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    verifier = import_module("mergecraft.agents.verifier")
    findings = _critical_findings(9)
    plan = verifier.plan_agent_verifications(
        findings,
        budget=_resolve_verification_budget(settings),
    )
    ninth = findings[8].identity()
    dispatched = {item.fingerprint for item in plan.dispatch}
    assert ninth in dispatched


def test_publication_still_caps_inline_at_eight() -> None:
    """D1 invariant — decoupling verification must not raise the inline cap."""
    budget = import_module("mergecraft.analyzers.budget")
    verifier = import_module("mergecraft.agents.verifier")

    placement = budget.place_findings(
        [],
        inline_budget=INLINE_BUDGET,
        agent_findings=[
            {
                "severity": "Major",
                "path": f"src/inline{index:02d}.py",
                "line": index,
                "body": f"inline filler {index}",
            }
            for index in range(1, INLINE_BUDGET + 3)
        ],
    )
    assert budget.default_inline_budget() == 8
    assert len(placement.inline) == INLINE_BUDGET
    assert len(placement.deferred) == 2
    assert verifier.plan_agent_verifications([], budget=INLINE_BUDGET).budget == INLINE_BUDGET


def test_withdrawn_and_below_severity_filters_run_before_the_budget(
    tmp_path: Path,
) -> None:
    """Preserves verifier.py filter order — pre-budget skips never consume slots."""
    from mergecraft.config.settings import load_repo_settings

    verifier = import_module("mergecraft.agents.verifier")
    withdrawn = verifier.AgentFinding(
        path="src/withdrawn.py",
        body="already refuted in learnings",
        severity="Critical",
    )
    withdrawn_id = withdrawn.identity()
    learnings = _learnings_with_withdrawn(withdrawn_id)

    minor = verifier.AgentFinding(
        path="src/nit.py",
        body="style nit",
        severity="Minor",
    )
    live = [
        verifier.AgentFinding(
            path=f"src/live{index}.py",
            body=f"live blocker {index}",
            severity="Critical",
        )
        for index in range(3)
    ]
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    plan = verifier.plan_agent_verifications(
        [minor, withdrawn, *live],
        budget=1,
        learnings_text=learnings,
    )

    assert minor.identity() in plan.skipped_below_severity
    assert withdrawn_id in plan.skipped_withdrawn
    assert len(plan.dispatch) == 1
    assert withdrawn_id not in {item.fingerprint for item in plan.dispatch}
    assert minor.identity() not in {item.fingerprint for item in plan.dispatch}
    assert _resolve_verification_budget(settings) == 24


def test_over_budget_verifications_are_recorded_not_silently_dropped(
    tmp_path: Path,
) -> None:
    """Over-budget fingerprints must surface in ``skipped_over_budget`` (feeds W3)."""
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    verifier = import_module("mergecraft.agents.verifier")
    findings = _critical_findings(25)
    plan = verifier.plan_agent_verifications(
        findings,
        budget=_resolve_verification_budget(settings),
    )
    overflow_id = findings[24].identity()
    assert overflow_id in plan.skipped_over_budget
    assert len(plan.dispatch) == 24
    assert overflow_id not in {item.fingerprint for item in plan.dispatch}
