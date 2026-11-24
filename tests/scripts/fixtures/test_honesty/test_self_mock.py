"""Negative fixture: patch targets the module under test."""

from __future__ import annotations

from unittest.mock import patch


def test_patches_under_test() -> None:
    with patch("mergecraft.scripts.fixtures.test_honesty.self_mock.helper", return_value=1):
        assert True


def helper() -> int:
    return 0
