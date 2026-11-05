"""Path glob matching: linear time on hostile globs, root anchoring, ``**`` (#1056 part 3).

Declared scope globs come from a pull request body, so the matcher must stay
fast on any glob the parser accepts. Compiling ``**`` to ``(?:[^/]+/)*`` and
``*`` to ``[^/]*`` backtracks catastrophically: a 38-character run of ``**/``
segments, or ``*a*a*a…*b`` against one long segment, takes minutes. Each
hostile case runs in a fresh interpreter with a hard wall-clock deadline, so a
regression fails in seconds instead of hanging the suite; inside the child the
timed call must finish in 50 ms and return the right answer.

The scope matcher (``path_full_matches_glob``) is anchored at the repository
root; the pipeline matcher (``path_matches_glob``) keeps its right-anchored
relative match and lets ``**`` cross directories.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from mergecraft.utils.path_globs import path_full_matches_glob, path_matches_glob

_CALL_BUDGET_S = 0.05
_CHILD_DEADLINE_S = 10.0

_PROBE = """
import json, sys, time
from mergecraft.utils.path_globs import path_full_matches_glob, path_matches_glob
fn = {"full": path_full_matches_glob, "relative": path_matches_glob}[sys.argv[1]]
pattern, path = sys.argv[2], sys.argv[3]
fn(pattern, "warm")  # compile and cache outside the timed call
start = time.perf_counter()
result = fn(pattern, path)
print(json.dumps({"result": result, "elapsed": time.perf_counter() - start}))
"""

_DEEP_STARS = "**/" * 12 + "zz"  # 38 characters, accepted by every scope bound
_E2E_STARS = "**/" * 14 + "zz"  # 44 characters: hung the run packet build
_STAR_RUN = "*a" * 8 + "*b"  # 18 characters
_THIRTY_SEGMENTS = "/".join(["a"] * 29)

HOSTILE_CASES: list[tuple[str, str, str, bool]] = [
    ("double-star-run-miss", _DEEP_STARS, f"{_THIRTY_SEGMENTS}/b", False),
    ("double-star-run-hit", _DEEP_STARS, f"{_THIRTY_SEGMENTS}/zz", True),
    ("star-run-miss", _STAR_RUN, "a" * 60, False),
    ("star-run-hit", _STAR_RUN, "a" * 60 + "b", True),
    ("e2e-glob-miss", _E2E_STARS, "/".join(["d"] * 28) + "/f.md", False),
]


def _run_probe(kind: str, pattern: str, path: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _PROBE, kind, pattern, path],
            capture_output=True,
            text=True,
            timeout=_CHILD_DEADLINE_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"{kind} match of {pattern!r} did not finish in {_CHILD_DEADLINE_S:.0f} s "
            "(catastrophic backtracking)"
        )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return dict(json.loads(completed.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("kind", ["full", "relative"])
@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [(pattern, path, expected) for _id, pattern, path, expected in HOSTILE_CASES],
    ids=[case_id for case_id, _pattern, _path, _expected in HOSTILE_CASES],
)
def test_a_hostile_glob_matches_in_linear_time_with_the_right_answer(
    kind: str, pattern: str, path: str, expected: bool
) -> None:
    outcome = _run_probe(kind, pattern, path)

    assert outcome["result"] is expected
    assert outcome["elapsed"] < _CALL_BUDGET_S, outcome


# ── ``**`` crosses directories ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        (".github/**", ".github/workflows/ci.yml"),
        ("a/**/d.py", "a/b/c/d.py"),
        ("a/**/d.py", "a/d.py"),
        ("src/**", "src/a/b/c.py"),
        ("src/**/*.py", "src/c.py"),
    ],
    ids=["dot-dir-tree", "middle-double-star", "middle-zero-dirs", "trailing", "suffix-zero-dirs"],
)
def test_double_star_crosses_directories(pattern: str, path: str) -> None:
    assert path_matches_glob(pattern, path) is True
    assert path_full_matches_glob(pattern, path) is True


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        (".github/**", "docs/workflows/ci.yml"),
        ("a/**/d.py", "a/b/c/e.py"),
        ("a/*/d.py", "a/b/c/d.py"),
    ],
    ids=["other-tree", "other-name", "single-star-stays-in-one-segment"],
)
def test_double_star_does_not_match_outside_its_tree(pattern: str, path: str) -> None:
    assert path_full_matches_glob(pattern, path) is False
    assert path_matches_glob(pattern, path) is False


# ── the scope matcher is anchored at the repository root ─────────────────────


@pytest.mark.parametrize(
    ("pattern", "inside", "outside"),
    [
        ("tests/**", "tests/x.py", "src/tests/x.py"),
        ("README.md", "README.md", "docs/README.md"),
        ("*.md", "a.md", "docs/a.md"),
    ],
    ids=["tree", "root-file", "suffix-only"],
)
def test_the_scope_matcher_is_anchored_at_the_root(pattern: str, inside: str, outside: str) -> None:
    assert path_full_matches_glob(pattern, inside) is True
    assert path_full_matches_glob(pattern, outside) is False


# ── character-class negation and a trailing ``**`` ───────────────────────────


@pytest.mark.parametrize("matcher", [path_full_matches_glob, path_matches_glob])
@pytest.mark.parametrize(
    ("pattern", "hit", "miss"),
    [("[!a]*", "b.py", "a.py"), ("[!a-c]x", "dx", "bx")],
    ids=["negated-char", "negated-range"],
)
def test_a_negated_class_excludes_its_members(
    matcher: Any, pattern: str, hit: str, miss: str
) -> None:
    assert matcher(pattern, hit) is True
    assert matcher(pattern, miss) is False


@pytest.mark.parametrize("matcher", [path_full_matches_glob, path_matches_glob])
def test_a_trailing_double_star_matches_zero_segments(matcher: Any) -> None:
    assert matcher("docs/**", "docs") is True
    assert matcher("docs/**", "docs/a/b.md") is True
    assert matcher("docs/**", "documents") is False
