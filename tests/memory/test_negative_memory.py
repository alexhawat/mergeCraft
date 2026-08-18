"""DG7 negative memory — bounded suppression with audit trail (convention 7).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG7).
Implementation: **DG7.2** — bounded negative memory in ``utils/learnings.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests.memory.support import make_finding, memory_store_path


def test_do_not_flag_x_when_y_is_stored(tmp_path: Path) -> None:
    """Store ``do not flag X when Y`` and suppress matching findings."""
    from mergecraft.utils.memory import NegativeMemoryStore, apply_negative_memory

    repo = tmp_path / "repo"
    repo.mkdir()
    store = NegativeMemoryStore(path=memory_store_path(repo), max_entries=32)
    store.add_rule(
        pattern="unused import os",
        when="path ends with __init__.py",
        reason="Package re-exports require the import for side effects.",
    )

    suppressed_finding = make_finding(
        message="Unused import os",
        path="src/pkg/__init__.py",
        start_line=1,
        end_line=1,
    )
    reported_finding = make_finding(
        message="Unused import os",
        path="src/app/handler.py",
        start_line=3,
        end_line=3,
    )

    result = apply_negative_memory(
        findings=[suppressed_finding, reported_finding],
        store=store,
        repo_root=repo,
    )

    assert suppressed_finding not in result.reported
    assert suppressed_finding in result.suppressed
    assert reported_finding in result.reported
    assert result.suppression_reasons[suppressed_finding.fingerprint]


def test_negative_memory_is_bounded_and_auditable(tmp_path: Path) -> None:
    """Negative memory is capped and every suppression carries an audit record (convention 7)."""
    from mergecraft.utils.memory import NegativeMemoryStore, apply_negative_memory

    repo = tmp_path / "repo"
    repo.mkdir()
    max_entries = 3
    store = NegativeMemoryStore(path=memory_store_path(repo), max_entries=max_entries)

    for idx in range(max_entries + 2):
        store.add_rule(
            pattern=f"pattern-{idx}",
            when="path ends with app.py",
            reason=f"audit reason {idx}",
        )

    assert len(store.list_rules()) <= max_entries
    audit = store.audit_trail()
    assert audit
    assert all(entry.reason for entry in audit)

    finding = make_finding(
        message="pattern-4",
        path="src/app.py",
        start_line=10,
        end_line=10,
    )
    result = apply_negative_memory(findings=[finding], store=store, repo_root=repo)
    if finding in result.suppressed:
        assert result.suppression_reasons[finding.fingerprint] in {entry.reason for entry in audit}


def test_over_suppression_is_detectable(tmp_path: Path) -> None:
    """A reviewer taught into silence must be visible in an over-suppression report."""
    from mergecraft.utils.memory import NegativeMemoryStore, detect_over_suppression

    repo = tmp_path / "repo"
    repo.mkdir()
    store = NegativeMemoryStore(path=memory_store_path(repo), max_entries=16)
    store.add_rule(
        pattern="any lint on generated files",
        when="file is generated",
        reason="Generated output is not hand-edited.",
    )

    findings = [
        make_finding(
            message=f"Lint finding {idx}",
            path=f"src/generated/file_{idx}.py",
            start_line=1,
            end_line=1,
        )
        for idx in range(6)
    ]

    report = detect_over_suppression(
        findings=findings,
        store=store,
        repo_root=repo,
        threshold_ratio=0.5,
    )

    assert report.is_over_suppressed
    assert report.suppressed_count >= 3
    assert report.audit_entries
    assert any("generated" in entry.reason.lower() for entry in report.audit_entries)
