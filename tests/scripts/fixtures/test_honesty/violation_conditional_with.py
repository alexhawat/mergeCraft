"""Negative fixture: assert under ``if`` inside ``with``."""

from __future__ import annotations

from unittest.mock import patch


def test_assert_under_if_in_with() -> None:
    flag = True
    with patch("os.getcwd", return_value="/tmp"):
        if flag:
            assert flag