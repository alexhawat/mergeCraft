"""Disposition ledger — every raw analyzer hit ends with one recorded disposition (#941)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from mergecraft.analyzers.finding import Finding, make_finding

_DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1,2 +1,6 @@\n"
    " keep\n"
    "+one\n"
    "+two\n"
    "+three\n"
    "+four\n"
    " tail\n"
)


def _hit(
    *,
    tool: str = "ruff",
    rule: str = "F401",
    path: str = "src/app.py",
    line: int = 2,
    message: str = "unused import",
    severity: str = "Minor",
) -> Finding:
    return make_finding(
        tool=tool,
        rule_id=rule,
        category="Maintainability & Code Quality",
        severity=severity,
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


def _ledger_with(*findings: Finding):
    from mergecraft.analyzers.dispositions import DispositionLedger

    ledger = DispositionLedger()
    ledger.register_raw(list(findings))
    return ledger


# --------------------------------------------------------------------------- identity


def test_hit_id_is_stable_across_stage_mutations_and_distinguishes_hits() -> None:
    from mergecraft.analyzers.dispositions import hit_id_for

    base = _hit()
    assert hit_id_for(base) == hit_id_for(base.model_copy(update={"introduced_by_pr": "true"}))
    assert hit_id_for(base) == hit_id_for(base.model_copy(update={"severity": "Major"}))
    assert hit_id_for(base) != hit_id_for(_hit(line=3))
    assert hit_id_for(base) != hit_id_for(_hit(message="something else"))
    assert hit_id_for(base) != hit_id_for(_hit(rule="F811"))
    assert hit_id_for(base) != hit_id_for(_hit(tool="pylint"))


def test_a_missing_or_blank_reason_is_rejected() -> None:
    from mergecraft.analyzers.dispositions import DispositionEntry

    for reason in ("", "   "):
        with pytest.raises(ValidationError):
            DispositionEntry(
                hit_id="h1", disposition="dropped:baseline", stage="baseline", reason=reason
            )
    ok = DispositionEntry(
        hit_id="h1", disposition="dropped:baseline", stage="baseline", reason="existed on base"
    )
    assert ok.reason == "existed on base"


def test_unknown_disposition_kinds_are_rejected() -> None:
    from mergecraft.analyzers.dispositions import DispositionEntry

    with pytest.raises(ValidationError):
        DispositionEntry(hit_id="h1", disposition="vanished", stage="x", reason="because")


def test_recording_without_a_reason_never_silently_defaults() -> None:
    ledger = _ledger_with(_hit())
    from mergecraft.analyzers.dispositions import hit_id_for

    with pytest.raises((ValueError, ValidationError)):
        ledger.record(hit_id_for(_hit()), "dropped:out_of_scope", stage="scope", reason="")


# --------------------------------------------------------------------------- per stage


def test_scoping_records_out_of_scope_drops() -> None:
    from mergecraft.analyzers.scope import apply_scope_exceptions

    inside = _hit(line=3)
    outside = _hit(line=40, message="far away")
    ledger = _ledger_with(inside, outside)

    kept = apply_scope_exceptions([inside, outside], diff_text=_DIFF, ledger=ledger)

    assert kept == [inside]
    entry = ledger.entry_for(outside)
    assert entry is not None
    assert (entry.disposition, entry.stage) == ("dropped:out_of_scope", "out_of_scope")
    assert entry.reason.strip()
    assert ledger.entry_for(inside) is None


def test_generated_path_policy_records_dropped_generated() -> None:
    from mergecraft.analyzers.scope import filter_generated_scope

    generated = _hit(path="package-lock.json", line=1, message="lockfile noise")
    source = _hit()
    ledger = _ledger_with(generated, source)
    diff = (
        "diff --git a/package-lock.json b/package-lock.json\n"
        "--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1 +1,2 @@\n x\n+y\n"
    ) + _DIFF

    kept = filter_generated_scope([generated, source], diff_text=diff, ledger=ledger)

    dropped = ledger.entry_for(generated)
    if source in kept and generated not in kept:
        assert dropped is not None
        assert (dropped.disposition, dropped.stage) == ("dropped:generated", "generated")
        assert dropped.reason.strip()
    else:  # the policy kept it: then no drop may be recorded for it
        assert dropped is None


def test_withdrawn_memory_records_the_learnings_fingerprint() -> None:
    from mergecraft.analyzers.scope import suppress_withdrawn_findings
    from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING

    refuted = _hit(message="refuted by the author")
    survivor = _hit(message="still valid")
    ledger = _ledger_with(refuted, survivor)
    learnings = (
        f"{WITHDRAWN_FINDINGS_HEADING}\n\n"
        f"- not a bug <!-- mergecraft-finding:v1:{refuted.fingerprint} -->\n"
    )

    kept = suppress_withdrawn_findings([refuted, survivor], learnings, ledger=ledger)

    assert kept == [survivor]
    entry = ledger.entry_for(refuted)
    assert entry is not None
    assert (entry.disposition, entry.stage) == ("dropped:withdrawn", "withdrawn")
    assert entry.ref == refuted.fingerprint


def test_baseline_suppression_records_the_base_match_and_persists_the_audit_rows() -> None:
    from mergecraft.analyzers.baseline_suppression import suppress_baseline_findings

    old = _hit(path="src/old.py", line=9, message="pre-existing complaint")
    fresh = _hit(path="src/app.py", line=3, message="new complaint")
    ledger = _ledger_with(old, fresh)

    result = suppress_baseline_findings(
        head_findings=[old, fresh],
        base_findings=[old],
        diff_text=_DIFF,
        base_comparison="full",
        ledger=ledger,
    )

    assert result.reported == [fresh]
    entry = ledger.entry_for(old)
    assert entry is not None
    assert (entry.disposition, entry.stage) == ("dropped:baseline", "baseline")
    assert entry.ref == old.fingerprint
    audit = ledger.suppression_audit
    assert {row.decision for row in audit} == {"suppressed", "reported"}
    assert all(row.reason.strip() for row in audit)


def test_clustering_points_merged_hits_at_the_surviving_fingerprint() -> None:
    from mergecraft.analyzers.cluster import cluster_findings

    first = _hit(tool="ruff", rule="F401")
    second = _hit(tool="pylint", rule="W0611")
    ledger = _ledger_with(first, second)

    survivors = cluster_findings([first, second], ledger=ledger)

    assert len(survivors) == 1
    merged = [entry for entry in ledger.entries() if entry.disposition == "merged"]
    assert len(merged) == 1
    assert merged[0].ref == survivors[0].fingerprint
    assert merged[0].stage == "cluster"
    assert merged[0].reason.strip()


def test_dedupe_records_merged_hits() -> None:
    from mergecraft.findings.dedup import dedupe_findings

    strong = _hit(severity="Major", message="possible sql injection in query builder")
    weak = _hit(severity="Minor", message="possible SQL injection in the query builder")
    ledger = _ledger_with(strong, weak)

    survivors = dedupe_findings([strong, weak], ledger=ledger)

    assert len(survivors) == 1
    merged = [entry for entry in ledger.entries() if entry.disposition == "merged"]
    assert len(merged) == 1
    assert merged[0].ref == survivors[0].fingerprint
    assert merged[0].stage == "dedupe"


def test_verifier_drop_records_its_reason_against_the_hit() -> None:
    ledger = _ledger_with(_hit(severity="Major"))
    hit = _hit(severity="Major")
    ledger.close([hit])
    assert ledger.entry_for(hit).disposition == "kept"

    ledger.record_verifier(
        hit.fingerprint, verdict="drop", reason="guarded by the caller", new_severity=None
    )

    entry = ledger.entry_for(hit)
    assert (entry.disposition, entry.stage) == ("dropped:verifier", "verifier")
    assert "guarded by the caller" in entry.reason
    assert ledger.orphans() == []


def test_verifier_downgrade_is_a_terminal_downgraded_with_old_and_new_severity() -> None:
    hit = _hit(severity="Major")
    ledger = _ledger_with(hit)
    ledger.close([hit])

    ledger.record_verifier(
        hit.fingerprint, verdict="downgrade", reason="only on a cold path", new_severity="Minor"
    )

    entry = ledger.entry_for(hit)
    assert entry.disposition == "downgraded"
    assert "Major" in entry.reason
    assert "Minor" in entry.reason


def test_confirming_verdict_keeps_the_hit() -> None:
    hit = _hit(severity="Major")
    ledger = _ledger_with(hit)
    ledger.close([hit])
    ledger.record_verifier(
        hit.fingerprint, verdict="confirm", reason="reproduced", new_severity=None
    )
    assert ledger.entry_for(hit).disposition == "kept"


# --------------------------------------------------------------------------- closure


def test_closure_names_a_hit_that_no_stage_accounted_for() -> None:
    from mergecraft.analyzers.dispositions import hit_id_for

    lost = _hit(message="silently lost")
    kept = _hit(message="published")
    ledger = _ledger_with(lost, kept)

    ledger.close([kept])

    assert ledger.orphans() == [hit_id_for(lost)]
    summary = ledger.summary()
    assert summary.raw == 2
    assert summary.kept == 1
    assert summary.orphaned == [hit_id_for(lost)]


def test_summary_counts_close_over_the_raw_set() -> None:
    hits = [_hit(line=n, message=f"m{n}") for n in range(1, 6)]
    ledger = _ledger_with(*hits)
    ledger.record(
        _id(hits[0]), "dropped:out_of_scope", stage="out_of_scope", reason="outside every hunk"
    )
    ledger.record(_id(hits[1]), "dropped:baseline", stage="baseline", reason="on base")
    ledger.record(_id(hits[2]), "merged", stage="cluster", reason="same root cause", ref="fp")
    ledger.close(hits[3:])

    summary = ledger.summary()

    assert summary.raw == 5
    assert summary.kept == 2
    assert summary.merged == 1
    assert summary.dropped_by_stage == {"out_of_scope": 1, "baseline": 1}
    assert (
        summary.kept + summary.merged + summary.downgraded + sum(summary.dropped_by_stage.values())
        == summary.raw
    )
    assert summary.orphaned == []


def _id(finding: Finding) -> str:
    from mergecraft.analyzers.dispositions import hit_id_for

    return hit_id_for(finding)


def test_row_summary_renders_raw_kept_and_drop_counts_by_stage() -> None:
    hits = [_hit(line=n, message=f"m{n}") for n in range(1, 15)]
    ledger = _ledger_with(*hits)
    for hit in hits[:9]:
        ledger.record(_id(hit), "dropped:out_of_scope", stage="out_of_scope", reason="outside")
    for hit in hits[9:11]:
        ledger.record(_id(hit), "dropped:baseline", stage="baseline", reason="on base")
    ledger.close(hits[11:])

    assert ledger.row_summary() == "ruff 14 raw → 3 kept (9 out_of_scope, 2 baseline)"


# --------------------------------------------------------------------------- pipeline


def _run_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: list[Finding],
    *,
    diff_text: str = _DIFF,
) -> Any:
    from mergecraft.analyzers import adapters, pipeline
    from mergecraft.analyzers.registry import get_manifest

    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("ruff")])
    monkeypatch.setattr(
        adapters,
        "run_adapter",
        lambda **_: adapters.AdapterRunResult(findings=list(raw)),
    )
    return pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
        diff_text=diff_text,
        shell="restricted",
    )


def test_pipeline_gives_every_raw_hit_exactly_one_terminal_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_hunk = _hit(line=3)
    out_of_hunk = _hit(line=40, message="not in the diff")
    twin_a = _hit(line=4, tool="ruff", rule="E501", message="line too long")
    twin_b = _hit(line=4, tool="ruff", rule="E501x", message="line too long")

    state = _run_pipeline(tmp_path, monkeypatch, [in_hunk, out_of_hunk, twin_a, twin_b])

    ledger = state.dispositions
    assert ledger is not None
    summary = ledger.summary()
    assert summary.raw == 4
    assert summary.orphaned == []
    assert summary.dropped_by_stage.get("out_of_scope") == 1
    assert (
        summary.kept + summary.merged + summary.downgraded + sum(summary.dropped_by_stage.values())
        == summary.raw
    )
    assert ledger.entry_for(out_of_hunk).disposition == "dropped:out_of_scope"


def test_pipeline_pre_merge_row_shows_raw_kept_and_stage_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [_hit(line=3), _hit(line=40, message="far"), _hit(line=41, message="farther")]

    state = _run_pipeline(tmp_path, monkeypatch, hits)

    assert state.pre_merge_summary is not None
    assert "ruff 3 raw → 1 kept (2 out_of_scope)" in state.pre_merge_summary


def test_a_leaky_stage_leaves_a_named_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stage that loses a hit without recording it must be caught by the closure check."""
    from mergecraft.analyzers import pipeline

    kept = _hit(line=3, message="published")
    lost = _hit(line=4, message="swallowed by a buggy stage")

    def _leaky_scope(findings: list[Finding], **_kwargs: Any) -> list[Finding]:
        return [finding for finding in findings if finding.message != lost.message]

    monkeypatch.setattr(pipeline, "scope_findings", _leaky_scope)

    state = _run_pipeline(tmp_path, monkeypatch, [kept, lost])

    assert state.dispositions is not None
    assert state.dispositions.orphans() == [_id(lost)]


@settings(max_examples=40, deadline=None)
@given(
    specs=st.lists(
        st.tuples(
            st.sampled_from(["src/app.py", "src/other.py", "docs/readme.md"]),
            st.integers(min_value=1, max_value=12),
            st.sampled_from(["unused import", "line too long", "shadowed name"]),
            st.sampled_from(["F401", "E501", "F811"]),
        ),
        min_size=0,
        max_size=14,
    )
)
def test_property_every_raw_hit_has_exactly_one_terminal_disposition(
    specs: list[tuple[str, int, str, str]],
) -> None:
    """For arbitrary raw sets through the full pipeline nothing is lost or double-counted."""
    import tempfile

    from mergecraft.analyzers import adapters, pipeline
    from mergecraft.analyzers.registry import get_manifest

    raw = [
        _hit(path=path, line=line, message=message, rule=rule)
        for path, line, message, rule in specs
    ]
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as patch:
        patch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("ruff")])
        patch.setattr(
            adapters, "run_adapter", lambda **_: adapters.AdapterRunResult(findings=list(raw))
        )
        state = pipeline.run_analyzer_pipeline(
            repo_root=Path(tmp),
            changed_files=["src/app.py"],
            tier="trusted",
            diff_text=_DIFF,
            shell="restricted",
        )

    ledger = state.dispositions
    assert ledger is not None
    summary = ledger.summary()
    distinct = {_id(finding) for finding in raw}
    assert summary.raw == len(distinct)
    assert summary.orphaned == []
    assert (
        summary.kept + summary.merged + summary.downgraded + sum(summary.dropped_by_stage.values())
        == summary.raw
    )
    ids = [entry.hit_id for entry in ledger.entries()]
    assert len(ids) == len(set(ids)) == len(distinct)
