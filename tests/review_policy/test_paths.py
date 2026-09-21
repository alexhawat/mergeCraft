"""``normalize_repo_path`` — the dedup-key normalization contract (N4).

``findings/dedup.py`` buckets a finding by
``(normalize_repo_path(path), start_line, end_line, category)``, so every
transformation here changes which findings count as duplicates and therefore
which ones publish. This table pins the normalizations the implementation
performs *and* the ones it deliberately does not: case is preserved, duplicate
separators are not collapsed, ``../`` is not resolved, and absolute paths are
not made relative. Expected values are derived from ``review_policy/paths.py``.
"""

from __future__ import annotations

import pytest

from mergecraft.review_policy.paths import normalize_repo_path

#: ``(raw, expected)`` pairs covering each documented and each *absent* transform.
_CASES: list[tuple[str, str]] = [
    # A plain repo-relative path is returned unchanged.
    ("src/app.py", "src/app.py"),
    # Leading ``./``.
    ("./src/app.py", "src/app.py"),
    # Diff ``a/`` and ``b/`` prefixes.
    ("a/src/app.py", "src/app.py"),
    ("b/src/app.py", "src/app.py"),
    # The prefixes chain across the loop: ``./`` then ``a/`` / ``b/``.
    ("./a/src/app.py", "src/app.py"),
    ("./b/src/app.py", "src/app.py"),
    # Windows separators become forward slashes, before the prefix strip.
    ("src\\main\\app.py", "src/main/app.py"),
    (".\\src\\app.py", "src/app.py"),
    ("a\\src\\app.py", "src/app.py"),
    ("C:\\src\\app.py", "C:/src/app.py"),
    # Surrounding whitespace is stripped; internal whitespace is not a case here.
    ("  ./src/app.py  ", "src/app.py"),
    ("\tsrc/app.py\n", "src/app.py"),
    # Not normalized: casing.
    ("src/App.py", "src/App.py"),
    ("SRC/APP.PY", "SRC/APP.PY"),
    # Not normalized: duplicate separators.
    ("src//app.py", "src//app.py"),
    ("src///app.py", "src///app.py"),
    # Not normalized: absolute paths stay absolute.
    ("/abs/path.py", "/abs/path.py"),
    ("/a/b/../c", "/a/b/../c"),
    # Not normalized: ``../`` traversal is not resolved.
    ("../src/app.py", "../src/app.py"),
    ("../a/src/app.py", "../a/src/app.py"),
    # Degenerate inputs.
    ("", ""),
    ("a", "a"),
    ("a/", ""),
    ("./", ""),
    ("b/", ""),
    # ``ab/`` is not the ``a/`` prefix.
    ("ab/foo", "ab/foo"),
    # Only one ``./`` is stripped: the loop does not revisit ``./``.
    ("././src", "./src"),
    ("a/./src", "./src"),
    ("b/../x", "../x"),
]


@pytest.mark.parametrize(("raw", "expected"), _CASES)
def test_normalize_repo_path(raw: str, expected: str) -> None:
    """Each row is a value the dedup bucket key depends on."""
    assert normalize_repo_path(raw) == expected
