"""Result-set pins name the corpus trees and whether the checkout was clean (W3.3-4).

``run_structural_replay`` runs against a real throwaway git checkout: the
recorded tree ids must match what git reports for the corpus directories, and a
tracked change must flip ``working_tree_clean``.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mergecraft.evals.benchmark import git_tree_id, run_structural_replay
from mergecraft.evals.store import Case, add_case
from mergecraft.utils.learnings import LearningProvenance

_WHEN = datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [*_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True, env=_ENV
    ).stdout.strip()


def _case(case_id: str) -> Case:
    return Case(
        id=case_id,
        title=case_id,
        category="missed_finding",
        submitted_at=_WHEN,
        run_id="synthetic",
        pr_number=1,
        failure_mode="wrong_decision",
        expected_finding="synthetic",
        expected_decision="neutral",
        replay_command=f"mergecraft eval replay {case_id}",
        provenance=LearningProvenance(
            run_id="synthetic",
            pr_number=1,
            source_field="eval_bank",
            author_login="synthetic",
            author_association="OWNER",
            trust_tier="trusted",
            timestamp=_WHEN,
        ),
        body="",
        recorded_findings=[],
        run_succeeded=True,
        trust_tier="trusted",
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    add_case(root / "evals" / "cases", _case("pin-001"))
    detection = root / "evals" / "bench" / "mergecraft"
    detection.mkdir(parents=True)
    (detection / "marker.txt").write_text("corpus\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    monkeypatch.chdir(root)
    return root


def test_pins_record_the_bank_tree_and_a_clean_checkout(repo: Path) -> None:
    result = run_structural_replay(Path("evals/cases"), providers=("claude",))

    assert result.pins.bank_tree == _git(repo, "rev-parse", "HEAD:evals/cases")
    assert result.pins.working_tree_clean is True


def test_a_tracked_change_marks_the_checkout_dirty(repo: Path) -> None:
    (repo / "evals" / "bench" / "mergecraft" / "marker.txt").write_text(
        "edited\n", encoding="utf-8"
    )

    result = run_structural_replay(Path("evals/cases"), providers=("claude",))

    assert result.pins.working_tree_clean is False


def test_detection_corpus_tree_is_the_detection_directory_tree(repo: Path) -> None:
    assert git_tree_id(Path("evals/bench/mergecraft")) == _git(
        repo, "rev-parse", "HEAD:evals/bench/mergecraft"
    )
    assert git_tree_id(Path("evals/does-not-exist")) is None


def test_full_benchmark_pins_the_detection_corpus_tree(repo: Path) -> None:
    from mergecraft.evals.live_run import run_full_benchmark

    result = run_full_benchmark(
        Path("evals/cases"),
        detection_corpus_dir=Path("evals/bench/mergecraft"),
        results_dir=repo / "results",
        providers=("claude",),
        detection_provider="claude",
        detection_model="claude/none",
    )

    assert result.pins.detection_corpus_tree == _git(
        repo, "rev-parse", "HEAD:evals/bench/mergecraft"
    )
