"""A zero-length archive member must not end the extraction.

``extract_zip_texts`` stopped on the first empty chunk. An empty chunk means
two unrelated things — the read budget is exhausted, or the member is
genuinely zero bytes — and treating them alike discarded every later member.
A CI archive whose first matching entry is an empty log lost all the logs
after it, with no truncation marker to show anything had gone.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from mergecraft.ci.archive_bounds import extract_zip_texts


def _zip(*members: tuple[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buffer.getvalue()


def _log(name: str) -> bool:
    return name.endswith(".log")


def test_an_empty_first_member_does_not_discard_the_rest() -> None:
    """The reported case: the loss was silent, which is what made it dangerous."""
    raw = _zip(("empty.log", b""), ("second.log", b"kept"), ("third.log", b"also kept"))

    texts = extract_zip_texts(raw, name_filter=_log)

    assert "kept" in "".join(texts)
    assert "also kept" in "".join(texts)


def test_an_empty_member_between_two_populated_ones_is_skipped() -> None:
    raw = _zip(("a.log", b"first"), ("blank.log", b""), ("c.log", b"last"))

    joined = "".join(extract_zip_texts(raw, name_filter=_log))

    assert "first" in joined
    assert "last" in joined


def test_an_archive_of_only_empty_members_yields_no_text() -> None:
    """Skipping empties must not invent content, or mark a truncation."""
    raw = _zip(("a.log", b""), ("b.log", b""))

    texts = extract_zip_texts(raw, name_filter=_log)

    assert "".join(texts) == ""


def test_the_filter_still_excludes_non_matching_members() -> None:
    """Guard the guard: continuing past empties must not widen the filter."""
    raw = _zip(("skip.txt", b"ignored"), ("keep.log", b"wanted"))

    joined = "".join(extract_zip_texts(raw, name_filter=_log))

    assert "wanted" in joined
    assert "ignored" not in joined
