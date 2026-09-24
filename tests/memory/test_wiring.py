"""DG7 review-run wiring — memory applied on the precision path."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.memory.support import feedback_store_path, make_finding, memory_store_path

if TYPE_CHECKING:
    import pytest


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


def test_corrupt_feedback_json_does_not_crash_review_memory(tmp_path: Path) -> None:
    """Corrupt feedback.json degrades to no suppression on trusted reviews."""
    from mergecraft.utils.learnings import apply_repo_memory_to_findings

    repo = tmp_path / "repo"
    repo.mkdir()
    feedback_path = feedback_store_path(repo)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text("{not valid json", encoding="utf-8")

    dismissed = make_finding(
        message="Would be dismissed if store loaded",
        path="src/app.py",
        start_line=1,
        end_line=1,
    )

    surviving = apply_repo_memory_to_findings(
        [dismissed],
        repo_root=repo,
        trust_tier="trusted",
    )

    assert dismissed in surviving


def test_unreadable_memory_store_reports_every_finding(tmp_path: Path) -> None:
    """A suppression store that cannot be read must fail open, not closed."""
    from mergecraft.utils.learnings import apply_repo_memory_to_findings

    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = memory_store_path(repo)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    # Non-UTF-8 bytes are an input the loader genuinely cannot tolerate:
    # ``_read_json`` raises ``UnicodeDecodeError`` before any rule is parsed.
    # ``{"rules": [{}]}`` is tolerated by the hardened loader (it loads as an
    # empty store), so it never reached the fail-open guard this test names.
    memory_path.write_bytes(b'\xff\xfe{"rules": []}')
    finding = make_finding(
        message="Real regression",
        path="src/app.py",
        start_line=4,
        end_line=4,
    )

    surviving = apply_repo_memory_to_findings([finding], repo_root=repo, trust_tier="trusted")

    assert surviving == [finding]


def test_memory_store_construction_failure_reports_every_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected store failure skips suppression rather than dropping findings."""
    import mergecraft.utils.memory as memory_mod
    from mergecraft.utils.learnings import apply_repo_memory_to_findings

    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = memory_store_path(repo)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text('{"rules": []}', encoding="utf-8")

    def _explode(**_kwargs: object) -> object:
        msg = "malformed memory store"
        raise RuntimeError(msg)

    monkeypatch.setattr(memory_mod, "NegativeMemoryStore", _explode)
    finding = make_finding(
        message="Real regression",
        path="src/app.py",
        start_line=4,
        end_line=4,
    )

    surviving = apply_repo_memory_to_findings([finding], repo_root=repo, trust_tier="trusted")

    assert surviving == [finding]
