"""One shared ``./`` prefix strip, applied once (#1563).

``str.lstrip("./")`` removes every leading ``.`` and ``/`` character, so
``.github/x.py`` becomes ``github/x.py`` and ``../traces`` becomes ``traces``.
The helper removes exactly one leading ``./`` and nothing else: a leading dot
that starts a real name, a ``../`` traversal and an absolute path are left
untouched.
"""

from __future__ import annotations

import pytest

from mergecraft.review_policy.paths import strip_dot_slash_prefix


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("./a/b.py", "a/b.py", id="one-dot-slash-prefix"),
        pytest.param(".github/x.py", ".github/x.py", id="dotted-name-kept"),
        pytest.param("../traces", "../traces", id="parent-traversal-kept"),
        pytest.param(".venv-dev/x", ".venv-dev/x", id="dotted-directory-kept"),
        pytest.param("/abs/x", "/abs/x", id="absolute-path-kept"),
        pytest.param("a/./b", "a/./b", id="inner-dot-slash-kept"),
        pytest.param("././a", "./a", id="only-one-prefix-removed"),
        pytest.param("a/b.py", "a/b.py", id="plain-path-unchanged"),
        pytest.param("", "", id="empty"),
    ],
)
def test_strip_dot_slash_prefix(raw: str, expected: str) -> None:
    """Each row is a path shape the lstrip character set used to corrupt."""
    assert strip_dot_slash_prefix(raw) == expected
