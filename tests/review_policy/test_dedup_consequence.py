"""The property ``review_policy`` protects: normalization decides dedup (N4).

``findings/dedup.py`` builds its bucket key from ``normalize_repo_path``. Two
findings whose paths normalize to the same key are deduplicated when their
messages agree; two whose paths do not collapse to the same key never meet in a
bucket and are therefore both kept. These tests drive the real entry point
(``dedupe_findings``) rather than re-deriving the key, so a change in
normalization provably changes what publishes.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.findings.support import make_finding

#: Identical message, span, and category — only the path differs.
_MESSAGE = "Missing timeout on the retry loop"

#: Path pairs that ``normalize_repo_path`` collapses to one key.
_SAME_KEY_PAIRS: list[tuple[str, str]] = [
    ("./src/app.py", "src/app.py"),
    ("a/src/app.py", "src/app.py"),
    ("b/src/app.py", "src/app.py"),
    ("./a/src/app.py", "src/app.py"),
    ("src\\app.py", "src/app.py"),
    ("  src/app.py  ", "src/app.py"),
]

#: Path pairs every distinction in the normalizer keeps apart.
_DIFFERENT_KEY_PAIRS: list[tuple[str, str]] = [
    ("src/app.py", "src/other.py"),
    ("src/app.py", "src/App.py"),
    ("src/app.py", "src//app.py"),
    ("src/app.py", "/src/app.py"),
    ("src/app.py", "../src/app.py"),
]


def _finding(path: str) -> Any:
    return make_finding(message=_MESSAGE, path=path, start_line=10, end_line=10)


@pytest.mark.parametrize(("first", "second"), _SAME_KEY_PAIRS)
def test_paths_normalizing_to_the_same_key_dedup(first: str, second: str) -> None:
    """A prefix or separator difference is invisible to the dedup key."""
    from mergecraft.findings.dedup import dedupe_findings
    from mergecraft.review_policy.paths import normalize_repo_path

    assert normalize_repo_path(first) == normalize_repo_path(second)
    assert len(dedupe_findings([_finding(first), _finding(second)])) == 1


@pytest.mark.parametrize(("first", "second"), _DIFFERENT_KEY_PAIRS)
def test_paths_not_normalizing_to_the_same_key_do_not_dedup(first: str, second: str) -> None:
    """Every distinction the normalizer preserves keeps two findings apart."""
    from mergecraft.findings.dedup import dedupe_findings
    from mergecraft.review_policy.paths import normalize_repo_path

    assert normalize_repo_path(first) != normalize_repo_path(second)
    assert len(dedupe_findings([_finding(first), _finding(second)])) == 2


def test_dedup_key_is_the_normalized_path_plus_span_and_category() -> None:
    """The public key is ``(normalized path, start, end, category)``."""
    from mergecraft.findings.dedup import location_key
    from mergecraft.review_policy.paths import normalize_repo_path

    finding = _finding("./src/app.py")

    assert location_key(finding) == (
        normalize_repo_path("./src/app.py"),
        10,
        10,
        "Functional Correctness",
    )
