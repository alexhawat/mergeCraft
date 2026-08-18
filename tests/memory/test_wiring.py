"""DG7 review-run wiring — memory applied on the precision path."""

from __future__ import annotations

from pathlib import Path

from tests.memory.support import feedback_store_path, make_finding, memory_store_path


def test_precision_pipeline_applies_repo_memory_before_publication(tmp_path: Path) -> None:
    """Dismissed feedback and negative memory suppress findings on the precision path."""
    from mergecraft.findings.precision_pipeline import apply_precision_pipeline
    from mergecraft.utils.memory import (
        FeedbackOutcome,
        NegativeMemoryStore,
        record_finding_feedback,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    dismissed = make_finding(
        message="Stale warning",
        path="src/app.py",
        start_line=1,
        end_line=1,
    )
    record_finding_feedback(
        store_path=feedback_store_path(repo),
        fingerprint=dismissed.fingerprint,
        outcome=FeedbackOutcome.DISMISSED,
        reason="Already fixed upstream",
        pr_number=7,
    )
    store = NegativeMemoryStore(path=memory_store_path(repo), max_entries=8)
    store.add_rule(
        pattern="lint noise",
        when="path ends with __init__.py",
        reason="Package re-exports require the import.",
    )

    dismissed = make_finding(
        message="Stale warning",
        path="src/app.py",
        start_line=1,
        end_line=1,
    )
    suppressed = make_finding(
        message="lint noise in generated init",
        path="src/pkg/__init__.py",
        start_line=2,
        end_line=2,
    )
    reported = make_finding(
        message="Real regression",
        path="src/app.py",
        start_line=10,
        end_line=10,
    )

    refined = apply_precision_pipeline(
        [dismissed, suppressed, reported],
        dedupe=False,
        repo_root=repo,
    )

    assert dismissed not in refined
    assert suppressed not in refined
    assert reported in refined


def test_untrusted_tier_skips_repo_memory_suppression(tmp_path: Path) -> None:
    """Fork-authored feedback.json/memory.json must not suppress findings (D5/D9)."""
    from mergecraft.utils.learnings import apply_repo_memory_to_findings
    from mergecraft.utils.memory import (
        FeedbackOutcome,
        NegativeMemoryStore,
        record_finding_feedback,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    dismissed = make_finding(
        message="Stale warning",
        path="src/app.py",
        start_line=1,
        end_line=1,
    )
    record_finding_feedback(
        store_path=feedback_store_path(repo),
        fingerprint=dismissed.fingerprint,
        outcome=FeedbackOutcome.DISMISSED,
        reason="Attacker-suppressed",
        pr_number=99,
    )
    store = NegativeMemoryStore(path=memory_store_path(repo), max_entries=8)
    store.add_rule(
        pattern="lint noise",
        when="path ends with __init__.py",
        reason="Broad fork rule.",
    )
    suppressed = make_finding(
        message="lint noise in generated init",
        path="src/pkg/__init__.py",
        start_line=2,
        end_line=2,
    )

    surviving = apply_repo_memory_to_findings(
        [dismissed, suppressed],
        repo_root=repo,
        trust_tier="untrusted",
    )

    assert dismissed in surviving
    assert suppressed in surviving
