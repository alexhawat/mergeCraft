"""Negative fixture: assert only inside a conditional branch."""

from __future__ import annotations


def test_branch_assert() -> None:
    flag = True
    if flag:
        assert flag
