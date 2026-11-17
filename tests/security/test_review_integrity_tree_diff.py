"""Checkout integrity failures name which paths changed."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.security.review_integrity import (
    format_tree_change_detail,
    snapshot_tree,
    verify_tree_unchanged,
)


def _checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return checkout


def test_unchanged_tree_passes(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    (checkout / "keep.txt").write_text("ok\n", encoding="utf-8")
    before = snapshot_tree(checkout)
    verify_tree_unchanged(checkout, before)


def test_one_modified_file_is_named(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    path = checkout / "src" / "a.py"
    path.parent.mkdir(parents=True)
    path.write_text("v1\n", encoding="utf-8")
    before = snapshot_tree(checkout)
    path.write_text("v2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"modified: src/a\.py") as exc:
        verify_tree_unchanged(checkout, before)
    assert "added:" not in str(exc.value)
    assert "removed:" not in str(exc.value)


def test_one_added_file_is_named(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    before = snapshot_tree(checkout)
    (checkout / "new.txt").write_text("hi\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"added: new\.txt") as exc:
        verify_tree_unchanged(checkout, before)
    assert "modified:" not in str(exc.value)


def test_one_removed_file_is_named(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    victim = checkout / "gone.txt"
    victim.write_text("bye\n", encoding="utf-8")
    before = snapshot_tree(checkout)
    victim.unlink()
    with pytest.raises(RuntimeError, match=r"removed: gone\.txt") as exc:
        verify_tree_unchanged(checkout, before)
    assert "added:" not in str(exc.value)


def test_many_changes_are_truncated(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    before = snapshot_tree(checkout)
    for i in range(25):
        (checkout / f"file-{i:02d}.txt").write_text("x\n", encoding="utf-8")
    detail = format_tree_change_detail(before.fingerprints, snapshot_tree(checkout).fingerprints)
    assert "added:" in detail
    assert "(+5 more)" in detail
    assert detail.count("file-") == 20


def test_error_lists_paths_not_contents(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    secret = checkout / "secret.txt"
    secret.write_text("super-secret-payload\n", encoding="utf-8")
    before = snapshot_tree(checkout)
    secret.write_text("other-secret-payload\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        verify_tree_unchanged(checkout, before)
    text = str(exc.value)
    assert "super-secret" not in text
    assert "other-secret" not in text
    assert "modified: secret.txt" in text
