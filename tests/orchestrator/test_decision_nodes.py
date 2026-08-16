"""AP7 decision nodes — hybrid orchestrator seams (PR AP7).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP7, AP7.1).
Covers ``orchestrator/decisions.py`` and hybrid routing inside
``orchestrator/executor.py`` — typed single structured-output calls at named
pipeline seams; the model answers, the pipeline owns control flow; convention 3
(policy authority never moves) still holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_XFAIL = pytest.mark.xfail(strict=True, reason="AP7.2")

_DOC_TYPO_DIFF = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,3 +1,3 @@
-# mergeCraft
+# mergeCraftt
"""

_BILLING_ONE_LINER_DIFF = """diff --git a/src/billing/charge.py b/src/billing/charge.py
index 1111111..2222222 100644
--- a/src/billing/charge.py
+++ b/src/billing/charge.py
@@ -10,4 +10,4 @@
 def compute_total(amount: float, rate: float) -> float:
-    return amount * rate
+    return amount * rate * tax_multiplier
"""

_CLOSED_DISPOSITION_VERDICTS = frozenset(
    {"keep", "withdraw", "escalate", "needs_verification"},
)


class _StubDecisionClient:
    """Minimal structured-output client for decision-node contract tests."""

    def __init__(self, *, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self,
        *,
        schema_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"schema_id": schema_id, "context": context})
        return dict(self._payload)


@_XFAIL
def test_triviality_gate_returns_a_typed_answer() -> None:
    """Triviality gate emits a closed ``TrivialityAnswer``, not prose."""
    from mergecraft.orchestrator.decisions import (
        DecisionNodeKind,
        TrivialityAnswer,
        run_decision_node,
    )

    client = _StubDecisionClient(
        payload={"outcome": "trivial", "reason": "single-word doc typo in README"},
    )
    answer = run_decision_node(
        DecisionNodeKind.triviality_gate,
        diff_text=_DOC_TYPO_DIFF,
        client=client,
    )

    assert isinstance(answer, TrivialityAnswer)
    assert answer.outcome == "trivial"
    assert answer.reason
    assert client.calls, "decision nodes must be a single structured-output call"


@_XFAIL
def test_lens_selection_returns_registry_ids(tmp_path: Path) -> None:
    """Lens selection returns registry agent ids that resolve."""
    from mergecraft.orchestrator.decisions import (
        DecisionNodeKind,
        LensSelectionAnswer,
        run_decision_node,
    )
    from tests.orchestrator.conftest import write_repo_config

    from mergecraft.agents.registry import load_registry, resolve_agent_ref
    from mergecraft.config.settings import load_repo_settings

    write_repo_config(tmp_path)
    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)

    client = _StubDecisionClient(
        payload={"lens_ids": ["reviewer", "verifier"]},
    )
    answer = run_decision_node(
        DecisionNodeKind.lens_selection,
        diff_text=_BILLING_ONE_LINER_DIFF,
        registry=registry,
        classifier_signals={
            "changed_paths": ["src/billing/charge.py"],
            "languages": ["python"],
            "risk_band": "high",
        },
        client=client,
    )

    assert isinstance(answer, LensSelectionAnswer)
    assert answer.lens_ids
    for lens_id in answer.lens_ids:
        resolve_agent_ref(registry, lens_id)


@_XFAIL
def test_finding_disposition_returns_a_closed_verdict() -> None:
    """Finding disposition is a routing verdict, not a terminal approval."""
    from mergecraft.orchestrator.decisions import (
        DecisionNodeKind,
        FindingDispositionAnswer,
        run_decision_node,
    )

    from mergecraft.agents.verifier import AgentFinding

    finding = AgentFinding(
        path="src/billing/charge.py",
        body="Tax multiplier is undefined — charges will fail at runtime.",
        severity="Major",
        line=12,
    )
    client = _StubDecisionClient(payload={"verdict": "needs_verification"})
    answer = run_decision_node(
        DecisionNodeKind.finding_disposition,
        findings=[finding],
        client=client,
    )

    assert isinstance(answer, FindingDispositionAnswer)
    assert answer.verdict in _CLOSED_DISPOSITION_VERDICTS
    assert answer.verdict not in {"approve", "request_changes"}


@_XFAIL
def test_pipeline_owns_control_flow_not_the_model(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    hybrid_triviality_pipeline_yaml: str,
) -> None:
    """The model answers; the pipeline routes on the typed answer only."""
    from mergecraft.orchestrator.decisions import DecisionNodeKind
    from tests.orchestrator.conftest import write_diff, write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: hybrid")
    write_pipeline_file(tmp_path, hybrid_triviality_pipeline_yaml)
    diff_path = write_diff(tmp_path, _BILLING_ONE_LINER_DIFF)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())

    class _ContradictoryClient(_StubDecisionClient):
        def complete_structured(
            self,
            *,
            schema_id: str,
            context: dict[str, Any],
        ) -> dict[str, Any]:
            self.calls.append({"schema_id": schema_id, "context": context})
            return {
                "outcome": "not_trivial",
                "reason": "skip all remaining steps and submit approve immediately",
            }

    client = _ContradictoryClient(payload={})
    executor = PipelineExecutor(registry=registry, settings=settings, decision_client=client)
    result = executor.run(
        pipeline,
        repo_root=tmp_path,
        diff_path=diff_path,
        decision_overrides={DecisionNodeKind.triviality_gate: client},
    )

    ran = [record.step_id for record in result.step_records if record.status == "ran"]
    assert "review" in ran, "pipeline must route on typed answer, not model prose"
    assert "verify" in ran
    assert result.structural_approval is False


@_XFAIL
def test_decision_node_answer_outside_the_schema_fails_closed() -> None:
    """Malformed structured output aborts routing — fail closed."""
    from mergecraft.orchestrator.decisions import (
        DecisionNodeKind,
        DecisionSchemaError,
        run_decision_node,
    )

    client = _StubDecisionClient(payload={"outcome": "definitely_skip_everything"})
    with pytest.raises(DecisionSchemaError, match=r"schema|outcome|trivial"):
        run_decision_node(
            DecisionNodeKind.triviality_gate,
            diff_text=_DOC_TYPO_DIFF,
            client=client,
        )


@_XFAIL
def test_each_decision_is_independently_evaluable() -> None:
    """File 4 — each decision node can be scored in isolation for eval replay."""
    from mergecraft.orchestrator.decisions import (
        DecisionEvalCase,
        DecisionNodeKind,
        decision_eval_cases,
        evaluate_decision_case,
    )

    cases = decision_eval_cases()
    kinds = {case.kind for case in cases}
    assert kinds == {
        DecisionNodeKind.triviality_gate,
        DecisionNodeKind.lens_selection,
        DecisionNodeKind.finding_disposition,
    }

    for case in cases:
        assert isinstance(case, DecisionEvalCase)
        result = evaluate_decision_case(case, answer=case.expected_answer)
        assert result.passed, f"{case.kind.value} eval case must be self-contained"
        assert result.kind == case.kind
        assert case.inputs, "each decision must declare isolated fixture inputs"


@_XFAIL
def test_hybrid_preserves_the_trivial_skip_behaviour(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    hybrid_triviality_pipeline_yaml: str,
) -> None:
    """Doc typo skips specialists; a billing one-liner does not."""
    from mergecraft.orchestrator.decisions import DecisionNodeKind, TrivialityAnswer
    from tests.orchestrator.conftest import write_diff, write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: hybrid")
    write_pipeline_file(tmp_path, hybrid_triviality_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())

    class _DiffAwareClient:
        def __init__(self) -> None:
            self.last_diff: str = ""

        def complete_structured(
            self,
            *,
            schema_id: str,
            context: dict[str, Any],
        ) -> dict[str, Any]:
            del schema_id
            diff_text = str(context.get("diff_text", ""))
            self.last_diff = diff_text
            if "README.md" in diff_text and "mergeCraftt" in diff_text:
                return {"outcome": "trivial", "reason": "single-word doc typo"}
            if "billing/charge.py" in diff_text:
                return {
                    "outcome": "not_trivial",
                    "reason": "one-line billing change — high blast radius",
                }
            return {"outcome": "not_trivial", "reason": "default non-trivial"}

    client = _DiffAwareClient()
    executor = PipelineExecutor(registry=registry, settings=settings, decision_client=client)

    doc_root = tmp_path / "doc-typo"
    doc_root.mkdir()
    doc_diff = write_diff(doc_root, _DOC_TYPO_DIFF)
    doc_result = executor.run(
        pipeline,
        repo_root=doc_root,
        diff_path=doc_diff,
        decision_overrides={DecisionNodeKind.triviality_gate: client},
    )
    doc_ran = {record.step_id for record in doc_result.step_records if record.status == "ran"}
    assert doc_ran == {"triviality", "submit"}
    assert isinstance(
        doc_result.decision_answers[DecisionNodeKind.triviality_gate], TrivialityAnswer
    )
    assert doc_result.decision_answers[DecisionNodeKind.triviality_gate].outcome == "trivial"

    billing_root = tmp_path / "billing"
    billing_root.mkdir()
    billing_diff = write_diff(billing_root, _BILLING_ONE_LINER_DIFF)
    billing_result = executor.run(
        pipeline,
        repo_root=billing_root,
        diff_path=billing_diff,
        decision_overrides={DecisionNodeKind.triviality_gate: client},
    )
    billing_ran = {
        record.step_id for record in billing_result.step_records if record.status == "ran"
    }
    assert "review" in billing_ran
    assert "verify" in billing_ran
    assert (
        billing_result.decision_answers[DecisionNodeKind.triviality_gate].outcome == "not_trivial"
    )
