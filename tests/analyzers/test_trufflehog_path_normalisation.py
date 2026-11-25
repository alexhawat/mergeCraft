"""Trufflehog suppression paths keep a leading dot (#1563, D5, K-SAFE).

``_normalize_trufflehog_path`` is the suppression lookup key. ``lstrip("./")``
collapsed a dot-prefixed path onto its undotted form, so
``.tests/security/test_credentials.py`` matched the
``tests/security/test_credentials.py`` fixture suppression, while a root-level
``.venv-dev/…`` lost the dot that the venv marker needs. The two directions are
pinned together: what must stop being suppressed, and what must stay
suppressed.
"""

from __future__ import annotations

from mergecraft.analyzers.config import is_trufflehog_path_suppressed


def test_a_dot_prefixed_test_path_is_not_the_undotted_fixture() -> None:
    """``.tests/security/…`` is a different file from ``tests/security/…``."""
    assert is_trufflehog_path_suppressed(".tests/security/test_credentials.py") is False


def test_a_root_level_dotted_venv_path_hits_the_venv_marker() -> None:
    """``.venv-dev/…`` keeps the marker component ``.venv-dev``."""
    assert is_trufflehog_path_suppressed(".venv-dev/lib/x.py") is True


def test_the_undotted_fixture_path_is_still_suppressed() -> None:
    """K-SAFE: the intentional credential fixture stays exempt."""
    assert is_trufflehog_path_suppressed("tests/security/test_credentials.py") is True


def test_an_explicit_dot_slash_fixture_path_is_still_suppressed() -> None:
    """K-SAFE: one leading ``./`` is removed, so the fixture still matches."""
    assert is_trufflehog_path_suppressed("./tests/security/test_credentials.py") is True
