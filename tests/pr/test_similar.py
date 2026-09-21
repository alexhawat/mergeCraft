"""Behavioral suite for ``pr/similar.py`` (plan 29 T3 / #768).

``similar.py`` had **zero** importers under ``tests/``. These tests drive the
public helpers and observe outcomes: Jaccard ordering and thresholds, the
limit boundary, input non-mutation, and a fixture git repository for
``_git_change_candidates`` (including the "not a repository" path).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mergecraft.pr.similar import (
    _git_change_candidates,
    _overlap_score,
    _tokens,
    find_similar_changes,
    find_similar_issues,
)

if TYPE_CHECKING:
    from pathlib import Path


# ── tokenization and scoring ───────────────────────────────────────────


def test_tokens_casefold_and_split_on_non_alphanumerics() -> None:
    assert _tokens("Fix LOGIN-timeout, please!") == frozenset({"fix", "login", "timeout", "please"})


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ({"a", "b"}, {"a", "b"}, 1.0),
        ({"a", "b"}, {"c", "d"}, 0.0),
        ({"a", "b", "c"}, {"b", "c", "d"}, 0.5),
        ({"a"}, {"a", "b", "c", "d"}, 0.25),
        (set(), {"a"}, 0.0),
        ({"a"}, set(), 0.0),
        (set(), set(), 0.0),
    ],
)
def test_overlap_score_is_jaccard(left: set[str], right: set[str], expected: float) -> None:
    assert _overlap_score(frozenset(left), frozenset(right)) == expected


def test_overlap_score_is_symmetric() -> None:
    left = frozenset({"alpha", "beta"})
    right = frozenset({"beta", "gamma"})
    assert _overlap_score(left, right) == _overlap_score(right, left)


# ── find_similar_issues ────────────────────────────────────────────────


def test_find_similar_issues_orders_by_score_and_drops_disjoint() -> None:
    candidates = [
        {"title": "Unrelated changelog", "number": 1},
        {"title": "Login timeout handling", "number": 2},
        {"title": "Fix login timeout", "number": 3},
        {"title": "   ", "number": 4},
        {"number": 5},
    ]

    matches = find_similar_issues(title="Fix login timeout", candidates=candidates)

    assert [match.title for match in matches] == ["Fix login timeout", "Login timeout handling"]
    assert [match.number for match in matches] == [3, 2]
    assert matches[0].score == 1.0
    assert matches[1].score == pytest.approx(0.5)


def test_find_similar_issues_respects_the_limit_boundary() -> None:
    candidates = [{"title": "Fix login timeout"}, {"title": "Login timeout handling"}]
    assert len(find_similar_issues(title="Fix login timeout", candidates=candidates, limit=1)) == 1
    assert find_similar_issues(title="Fix login timeout", candidates=candidates, limit=0) == []


def test_find_similar_issues_only_carries_integer_numbers() -> None:
    candidates = [{"title": "login", "number": "7"}, {"title": "login retry"}]

    matches = find_similar_issues(title="login", candidates=candidates)

    assert matches[0].title == "login"
    assert matches[0].number is None


def test_find_similar_issues_does_not_mutate_candidates() -> None:
    candidate = {"title": "Fix login timeout", "number": 7}

    find_similar_issues(title="login timeout", candidates=[candidate])

    assert candidate == {"title": "Fix login timeout", "number": 7}


def test_find_similar_issues_without_candidates_returns_empty() -> None:
    assert find_similar_issues(title="anything") == []


# ── find_similar_changes ───────────────────────────────────────────────


def test_find_similar_changes_scores_by_wanted_overlap() -> None:
    candidates = [
        {"title": "touches both", "sha": "sha-1", "paths": ["a.py", "b.py", "c.py"]},
        {"title": "touches one", "sha": "sha-2", "paths": ["a.py", "z.py"]},
        {"title": "disjoint", "sha": "sha-3", "paths": ["other.py"]},
    ]

    matches = find_similar_changes(paths=["a.py", "b.py"], candidates=candidates)

    assert [match.title for match in matches] == ["touches both", "touches one"]
    assert [match.paths for match in matches] == [["a.py", "b.py"], ["a.py"]]
    assert matches[0].score == 1.0
    assert matches[1].score == 0.5


def test_find_similar_changes_without_wanted_paths_lists_all_at_zero() -> None:
    candidates = [{"title": "x", "sha": "s", "paths": ["b.py", "a.py"]}]

    matches = find_similar_changes(paths=[], candidates=candidates)

    assert len(matches) == 1
    assert matches[0].score == 0.0
    assert matches[0].paths == ["a.py", "b.py"]


def test_find_similar_changes_drops_malformed_rows_and_coerces_fields() -> None:
    candidates = [
        {"title": 123, "sha": 456, "paths": "not-a-list"},
        {"title": "keep", "sha": None, "paths": ["a.py"]},
    ]

    matches = find_similar_changes(paths=["a.py"], candidates=candidates)

    assert len(matches) == 1
    assert matches[0].title == "keep"
    assert matches[0].sha is None


def test_find_similar_changes_respects_the_limit_boundary() -> None:
    candidates = [
        {"title": "a", "paths": ["a.py"]},
        {"title": "b", "paths": ["a.py", "b.py"]},
    ]
    matches = find_similar_changes(paths=["a.py", "b.py"], candidates=candidates, limit=1)
    assert len(matches) == 1
    assert matches[0].title == "b"


# ── fixture repository ─────────────────────────────────────────────────


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    for key, value in (
        ("user.email", "t@example.com"),
        ("user.name", "Test"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "config", key, value], cwd=root, check=True, capture_output=True)


def _commit(root: Path, filename: str, message: str) -> None:
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{filename}\n", encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=root, check=True, capture_output=True
    )


def test_git_change_candidates_reads_recent_commits_newest_first(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "a.py", "first change")
    _commit(tmp_path, "b.py", "second change")

    candidates = _git_change_candidates(tmp_path)

    assert [candidate["title"] for candidate in candidates] == ["second change", "first change"]
    assert candidates[0]["paths"] == ["b.py"]
    assert candidates[1]["paths"] == ["a.py"]
    assert all(len(str(candidate["sha"])) == 40 for candidate in candidates)


def test_git_change_candidates_returns_empty_without_a_git_dir(tmp_path: Path) -> None:
    assert _git_change_candidates(tmp_path) == []


def test_git_change_candidates_returns_empty_when_git_dir_is_not_a_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    assert _git_change_candidates(tmp_path) == []


def test_find_similar_changes_uses_git_candidates_when_repo_root_given(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "src/login.py", "fix login")

    matches = find_similar_changes(paths=["src/login.py"], repo_root=tmp_path)

    assert matches, "repo_root catalog produced no matches"
    assert matches[0].sha is not None
    assert matches[0].paths == ["src/login.py"]


__all__: list[str] = []
