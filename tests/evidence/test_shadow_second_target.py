"""R4 RED suite — a second shadow target through the existing recorder (#737).

Wave plan: the verification/evals/receipts wave plan (R4). Test-plan doc:
``docs/test-plans/30-verification-evals-receipts.md``.

This wave adds a **second shadow target** — a different pinned model id and/or
prompt version — to the recorder that already exists in
``mergecraft.evidence.shadow``. It does **not** rebuild that recorder.

Pinned contracts:

* **Second target** — a ``ShadowTarget`` value (``target_id``, ``model``,
  ``prompt_version``) is declared beside the live target and recorded through
  the existing ``record_shadow_prediction`` call, which grows an additive
  ``target=`` keyword. No second JSONL writer is introduced.
* **Disagreement table** — ``disagreement_report`` rows carry the target
  identity so the table can be grouped by lane *and* by rule *and* by target.
* **Silent live path** (R-D5) — shadow predicts and records, never
  ``enforce_action``; a disagreement never flips ``decide_approval()`` and a
  recording failure never fails the live run/PR. The *comparison job* is the
  one place that fails closed.
* **Fail closed on the job** (R-D5) — ``compare_shadow_targets`` propagates a
  recording failure; missing shadow data is never rendered as agreement.
* **Missing outcome** — ``disagreement=None`` is preserved and the row is not
  dropped.
* **Audit trail** — a Logfire span is emitted on ``record_shadow_prediction``
  while the JSONL row is still written.

House style matches ``tests/evidence/test_gate_actions.py`` and
``tests/evidence/test_verdict_shadow.py``: helpers at the top, one behaviour
per test, lazy imports for symbols the R4 implementation wave lands.

The R4 implementation wave (``bbb1e3aa``) satisfied every contract below; the
reconciliation run (``f8c575d3-5a2f-433a-9e6a-8c978fcd25d9``) removed the
non-strict ``xfail`` markers so these are real passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.evidence.packet import MergeEvidencePacket


# ── helpers ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Prediction:
    """Minimal model-shaped prediction the existing recorder already accepts."""

    outcome: str
    diagnostic: str
    lane: str = "review"
    metadata: dict[str, Any] = field(default_factory=dict)


def _packet(**overrides: Any) -> MergeEvidencePacket:
    """Minimal packet so ``record_shadow_prediction`` keeps its existing signature."""
    from mergecraft.evidence.packet import (
        PACKET_SCHEMA_VERSION,
        AgentMetadata,
        MergeEvidencePacket,
    )

    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#42",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "self_assessment": None,
        "decision": None,
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
    }
    base.update(overrides)
    return MergeEvidencePacket(**base)


def _make_target(target_id: str, model: str, prompt_version: str | None = None) -> Any:
    """Build a ``ShadowTarget`` (lazy import — the symbol lands in R4)."""
    from mergecraft.evidence.shadow import ShadowTarget

    return ShadowTarget(target_id=target_id, model=model, prompt_version=prompt_version)


def _ctx(tmp_path: Path) -> Any:
    """A ``ToolContext`` shaped like the one ``main()`` holds at end-of-run."""
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.utils.github import GitHubClient

    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True)
        ),
        github=GitHubClient(token=""),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        tmpdir=str(tmp_path),
    )


# ── a second target runs through the existing recorder ───────────────────────


def test_second_target_records_through_the_existing_recorder(tmp_path: Path) -> None:
    """A different pinned model id/prompt version is stamped on the same JSONL row.

    The recorder is the one that already exists; the target is additive. A
    second JSONL writer would be a rebuild of ``evidence/shadow.py`` and is out
    of scope (#737).
    """
    from mergecraft.evidence.shadow import load_shadow_records, record_shadow_prediction

    live = _make_target("live", "claude-sonnet-4-5")
    shadow_b = _make_target("shadow-b", "claude-opus-4-1", prompt_version="2.0.0")
    target_path = tmp_path / "shadow.jsonl"

    record_shadow_prediction(
        _packet(),
        change_id="acme/demo#1",
        run_id="run-live",
        policy_id="default",
        output_path=target_path,
        target=live,
    )
    record_shadow_prediction(
        _packet(),
        change_id="acme/demo#1",
        run_id="run-shadow",
        policy_id="default",
        output_path=target_path,
        target=shadow_b,
    )

    rows = load_shadow_records(target_path)
    assert [row.target_id for row in rows] == ["live", "shadow-b"]
    assert rows[1].target_model == "claude-opus-4-1"
    assert rows[1].target_prompt_version == "2.0.0"
    assert rows[0].target_prompt_version is None


def test_recording_without_a_target_leaves_target_fields_unset(tmp_path: Path) -> None:
    """The target is optional: a legacy call records a row with no target identity."""
    from mergecraft.evidence.shadow import load_shadow_records, record_shadow_prediction

    target_path = tmp_path / "shadow.jsonl"
    record_shadow_prediction(
        _packet(),
        change_id="acme/demo#1",
        run_id="run-legacy",
        policy_id="default",
        output_path=target_path,
    )
    row = load_shadow_records(target_path)[0]
    assert row.target_id is None
    assert row.target_model is None
    assert row.target_prompt_version is None


# ── the disagreement table distinguishes targets by lane and by rule ─────────


def test_disagreement_report_distinguishes_targets_by_lane_and_rule(tmp_path: Path) -> None:
    """Two targets, same change, different lanes/rules/actions → distinguishable rows."""
    from mergecraft.evidence.shadow import (
        disagreement_report,
        load_shadow_records,
        record_shadow_prediction,
    )

    live = _make_target("live", "claude-sonnet-4-5")
    shadow_b = _make_target("shadow-b", "claude-opus-4-1", prompt_version="2.0.0")
    target_path = tmp_path / "shadow.jsonl"

    record_shadow_prediction(
        _packet(change_id="acme/demo#1"),
        change_id="acme/demo#1",
        run_id="run-live",
        policy_id="live",
        output_path=target_path,
        target=live,
        prediction=_Prediction(outcome="block", diagnostic="rule-block", lane="high"),
        actual_outcome="merged",
    )
    record_shadow_prediction(
        _packet(change_id="acme/demo#1"),
        change_id="acme/demo#1",
        run_id="run-shadow",
        policy_id="shadow-b",
        output_path=target_path,
        target=shadow_b,
        prediction=_Prediction(outcome="merged", diagnostic="rule-merge", lane="low"),
        actual_outcome="merged",
    )

    report = disagreement_report(
        load_shadow_records(target_path),
        outcomes={"acme/demo#1": "merged"},
    )
    assert len(report) == 2
    assert {row["target_id"] for row in report} == {"live", "shadow-b"}

    by_target_lane = {(row["target_id"], row["lane"]) for row in report}
    assert by_target_lane == {("live", "high"), ("shadow-b", "low")}

    by_target_rule = {(row["target_id"], row["rule_id"]) for row in report}
    assert by_target_rule == {("live", "rule-block"), ("shadow-b", "rule-merge")}

    flags = {row["target_id"]: row["disagreement"] for row in report}
    assert flags == {"live": True, "shadow-b": False}

    models = {row["target_id"]: row["target_model"] for row in report}
    assert models == {"live": "claude-sonnet-4-5", "shadow-b": "claude-opus-4-1"}


def test_report_keeps_a_record_without_an_outcome(tmp_path: Path) -> None:
    """A record with no outcome stays in the table with ``disagreement=None``."""
    from mergecraft.evidence.shadow import (
        disagreement_report,
        load_shadow_records,
        record_shadow_prediction,
    )

    target_path = tmp_path / "shadow.jsonl"
    record_shadow_prediction(
        _packet(),
        change_id="acme/demo#1",
        run_id="run-1",
        policy_id="default",
        output_path=target_path,
        prediction=_Prediction(outcome="block", diagnostic="rule-block", lane="high"),
    )
    report = disagreement_report(load_shadow_records(target_path), outcomes={})
    assert len(report) == 1, "a record without an outcome must not be dropped"
    assert report[0]["disagreement"] is None
    assert report[0]["actual_outcome"] is None


# ── R-D5: the live path stays silent ─────────────────────────────────────────


def test_recording_never_calls_enforce_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Predict and record only — the recorder must never apply the action."""
    import mergecraft.evidence.shadow as shadow

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        msg = "enforce_action must not run on the shadow path"
        raise AssertionError(msg)

    monkeypatch.setattr(shadow, "enforce_action", _forbidden)
    shadow.record_shadow_prediction(
        _packet(),
        change_id="acme/demo#1",
        run_id="run-1",
        policy_id="default",
        output_path=tmp_path / "shadow.jsonl",
    )


def test_shadow_recording_does_not_flip_decide_approval(tmp_path: Path) -> None:
    """A recorded disagreement leaves ``decide_approval()`` and the packet untouched."""
    from mergecraft.agents.gates import decide_approval
    from mergecraft.evidence.shadow import record_shadow_prediction

    packet = _packet()
    before = decide_approval(packet, run_succeeded=True, tier="trusted")

    record_shadow_prediction(
        packet,
        change_id="acme/demo#1",
        run_id="run-1",
        policy_id="default",
        output_path=tmp_path / "shadow.jsonl",
        prediction=_Prediction(outcome="block", diagnostic="rule-block", lane="high"),
        actual_outcome="merged",
    )

    after = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert after.model_dump() == before.model_dump()
    assert packet.decision is None, "the shadow recorder mutated the packet"


def test_live_emit_swallows_a_shadow_recording_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-D5 — a shadow-record failure must never fail the live run/PR.

    The optional comparison job is the one place that fails closed. The live
    emit path keeps its audit artifact and swallows the shadow error.
    """
    import mergecraft.evidence.shadow as shadow
    from mergecraft.evidence.packet import Decision
    from mergecraft.evidence.run_packet import emit_run_packet

    attempts: list[Any] = []

    def _boom(*args: Any, **kwargs: Any) -> Any:
        attempts.append(args)
        msg = "shadow log unwritable"
        raise OSError(msg)

    monkeypatch.setattr(shadow, "record_shadow_prediction", _boom)
    packet = _packet(
        change_id="acme/demo#42",
        decision=Decision(
            verdict="neutral",
            reason="shadow-mode decision",
            decided_by="mergecraft.agents.gates.decide_approval",
            mode="shadow",
        ),
    )

    written = emit_run_packet(_ctx(tmp_path), packet=packet)
    assert attempts, "the live emit path never reached the shadow recorder"
    assert written is not None
    assert written.is_file(), "a shadow failure must not stop the evidence packet"


def test_live_emit_stamps_the_live_target(tmp_path: Path) -> None:
    """Production shadow rows name the live target, not an unlabelled legacy row."""
    from mergecraft.evidence.packet import Decision
    from mergecraft.evidence.run_packet import emit_run_packet
    from mergecraft.evidence.shadow import load_shadow_records
    from mergecraft.evidence.shadow_compare import LIVE_TARGET

    change_id = "acme/demo#live-target-stamp"
    packet = _packet(
        change_id=change_id,
        decision=Decision(
            verdict="neutral",
            reason="shadow-mode decision",
            decided_by="mergecraft.agents.gates.decide_approval",
            mode="shadow",
        ),
    )
    written = emit_run_packet(_ctx(tmp_path), packet=packet)
    assert written is not None
    # CI sets RUNNER_TEMP, so every emit in the job appends to one shadow log.
    rows = [
        row
        for row in load_shadow_records(written.with_name("merge-evidence-shadow.jsonl"))
        if row.change_id == change_id
    ]
    assert len(rows) == 1
    assert rows[0].target_id == LIVE_TARGET.target_id
    assert rows[0].target_model == LIVE_TARGET.model


def test_keyless_job_omits_an_unexecuted_second_target(tmp_path: Path) -> None:
    """A hand-authored second-target row is not published as that model's output."""
    from mergecraft.evidence.shadow import load_shadow_records
    from mergecraft.evidence.shadow_compare import main

    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"change_id":"acme/demo#101","target_id":"live","outcome":"block",'
        '"diagnostic":"high_risk_migration","lane":"high","actual_outcome":"merged"}\n'
        '{"change_id":"acme/demo#101","target_id":"shadow-b","outcome":"auto_merge",'
        '"diagnostic":"low_risk_passing","lane":"low","actual_outcome":"merged"}\n',
        encoding="utf-8",
    )
    output = tmp_path / "out.jsonl"
    assert main(["--corpus", str(corpus), "--output", str(output)]) == 0
    rows = load_shadow_records(output)
    assert {row.target_id for row in rows} == {"live"}


def test_keyless_job_keeps_an_executed_second_target(tmp_path: Path) -> None:
    """A second target is recorded when the corpus says a run produced the row."""
    from mergecraft.evidence.shadow import load_shadow_records
    from mergecraft.evidence.shadow_compare import main

    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"change_id":"acme/demo#101","target_id":"live","outcome":"block",'
        '"diagnostic":"high_risk_migration","lane":"high","actual_outcome":"merged"}\n'
        '{"change_id":"acme/demo#101","target_id":"shadow-b","outcome":"auto_merge",'
        '"diagnostic":"low_risk_passing","lane":"low","actual_outcome":"merged",'
        '"executed":true}\n',
        encoding="utf-8",
    )
    output = tmp_path / "out.jsonl"
    assert main(["--corpus", str(corpus), "--output", str(output)]) == 0
    rows = load_shadow_records(output)
    assert {row.target_id for row in rows} == {"live", "shadow-b"}


def test_keyless_job_does_not_synthesize_partial_second_target_coverage(tmp_path: Path) -> None:
    """A second target that ran on one change is not invented for the others."""
    from mergecraft.evidence.shadow import load_shadow_records
    from mergecraft.evidence.shadow_compare import main

    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"change_id":"acme/demo#101","target_id":"live","outcome":"block",'
        '"diagnostic":"high_risk_migration","lane":"high","actual_outcome":"merged"}\n'
        '{"change_id":"acme/demo#102","target_id":"live","outcome":"auto_merge",'
        '"diagnostic":"low_risk_passing","lane":"low","actual_outcome":"merged"}\n'
        '{"change_id":"acme/demo#101","target_id":"shadow-b","outcome":"auto_merge",'
        '"diagnostic":"low_risk_passing","lane":"low","actual_outcome":"merged",'
        '"executed":true}\n',
        encoding="utf-8",
    )
    output = tmp_path / "out.jsonl"
    assert main(["--corpus", str(corpus), "--output", str(output)]) == 0
    rows = load_shadow_records(output)
    covered = {(row.target_id, row.change_id) for row in rows}
    assert covered == {
        ("live", "acme/demo#101"),
        ("live", "acme/demo#102"),
        ("shadow-b", "acme/demo#101"),
    }
    shadow_rows = [row for row in rows if row.target_id == "shadow-b"]
    assert shadow_rows[0].action == "auto_merge"


def test_keyless_job_publishes_the_committed_corpus_as_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CI entry point reports recorded rows and does not run a second target."""
    from mergecraft.evidence.shadow import load_shadow_records
    from mergecraft.evidence.shadow_compare import DEFAULT_CORPUS_PATH, main

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    output = tmp_path / "out.jsonl"
    assert main(["--corpus", str(DEFAULT_CORPUS_PATH), "--output", str(output)]) == 0
    rows = load_shadow_records(output)
    assert rows
    assert {row.target_id for row in rows} == {"live"}
    published = summary.read_text(encoding="utf-8")
    assert "Recorded shadow corpus" in published
    assert "does not run a model" in published
    assert "shadow-b" not in published


# ── the comparison job: records both targets, fails closed on a write error ──


def test_comparison_job_records_every_target_and_publishes_the_table(tmp_path: Path) -> None:
    """The keyless comparison records one row per (target, change) and returns the table."""
    from mergecraft.evidence.shadow import load_shadow_records
    from mergecraft.evidence.shadow_compare import compare_shadow_targets

    targets = [
        _make_target("live", "claude-sonnet-4-5"),
        _make_target("shadow-b", "claude-opus-4-1", prompt_version="2.0.0"),
    ]
    packets = [_packet(change_id="acme/demo#1"), _packet(change_id="acme/demo#2")]
    predictions: dict[str, dict[str, _Prediction]] = {
        "live": {
            "acme/demo#1": _Prediction(outcome="block", diagnostic="r1", lane="high"),
            "acme/demo#2": _Prediction(outcome="merged", diagnostic="r2", lane="low"),
        },
        "shadow-b": {
            "acme/demo#1": _Prediction(outcome="merged", diagnostic="r3", lane="low"),
            "acme/demo#2": _Prediction(outcome="merged", diagnostic="r4", lane="low"),
        },
    }
    output_path = tmp_path / "shadow.jsonl"

    report = compare_shadow_targets(
        packets,
        targets=targets,
        output_path=output_path,
        predictions=predictions,
        outcomes={"acme/demo#1": "merged", "acme/demo#2": "merged"},
    )

    rows = load_shadow_records(output_path)
    assert len(rows) == 4
    assert {row.target_id for row in rows} == {"live", "shadow-b"}

    assert len(report) == 4
    assert {row["target_id"] for row in report} == {"live", "shadow-b"}
    live_flags = {
        row["rule_id"]: row["disagreement"] for row in report if row["target_id"] == "live"
    }
    shadow_flags = {
        row["rule_id"]: row["disagreement"] for row in report if row["target_id"] == "shadow-b"
    }
    assert live_flags == {"r1": True, "r2": False}
    assert shadow_flags == {"r3": False, "r4": False}


def test_comparison_job_fails_closed_when_recording_fails(tmp_path: Path) -> None:
    """A recording failure must surface as a job error — never as agreement."""
    from mergecraft.evidence.shadow_compare import compare_shadow_targets

    targets = [
        _make_target("live", "claude-sonnet-4-5"),
        _make_target("shadow-b", "claude-opus-4-1"),
    ]
    # A directory where the JSONL should be: the append fails and must propagate.
    output_path = tmp_path / "shadow.jsonl"
    output_path.mkdir()

    with pytest.raises((OSError, RuntimeError)):
        compare_shadow_targets([_packet()], targets=targets, output_path=output_path)


# ── Logfire span on the recorder; JSONL stays the audit trail ────────────────


def test_recording_emits_a_shadow_span_and_keeps_the_jsonl_audit_trail(tmp_path: Path) -> None:
    """A span lands on the tracer while the JSONL row is still written."""
    from mergecraft.evidence.shadow import record_shadow_prediction
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="shadow-session", run_id="shadow-run")
    target_path = tmp_path / "shadow.jsonl"

    record_shadow_prediction(
        _packet(change_id="acme/demo#1"),
        change_id="acme/demo#1",
        run_id="run-1",
        policy_id="live",
        output_path=target_path,
        target=_make_target("live", "claude-sonnet-4-5"),
        prediction=_Prediction(outcome="block", diagnostic="rule-block", lane="high"),
        actual_outcome="merged",
        tracer=tracer,
    )

    assert target_path.is_file(), "JSONL remains the audit trail"
    assert target_path.read_text(encoding="utf-8").strip(), "JSONL row is empty"

    spans = [event for event in sink.events if event.kind == "mergecraft.shadow.prediction"]
    assert len(spans) == 1, "record_shadow_prediction must emit exactly one shadow span"
    attrs = spans[0].attrs
    assert attrs["mergecraft.shadow.change_id"] == "acme/demo#1"
    assert attrs["mergecraft.shadow.target_id"] == "live"
    assert attrs["mergecraft.shadow.disagreement"] is True
