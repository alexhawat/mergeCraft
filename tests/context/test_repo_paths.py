"""Tests for ``mergecraft.context.repo_paths``."""

from __future__ import annotations

from mergecraft.context.repo_paths import is_excluded_repo_path


def test_excluded_repo_paths_skip_common_vendor_dirs() -> None:
    assert is_excluded_repo_path(".venv/lib/python3.14/site-packages/foo.py")
    assert is_excluded_repo_path("node_modules/pkg/index.js")
    assert is_excluded_repo_path("src/demo/service.py") is False
