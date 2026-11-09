"""Env overrides are restored even when the settings load raises (#1256)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

if TYPE_CHECKING:
    from pathlib import Path

_KEYS = ("MERGECRAFT_TRUST_TIER", "MERGECRAFT_TRACING", "MERGECRAFT_TRACING_TO")


async def test_env_restored_when_load_repo_settings_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("MERGECRAFT_TRUST_TIER", "trusted")
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.delenv("MERGECRAFT_TRACING_TO", raising=False)
    before = {key: os.environ.get(key) for key in _KEYS}

    def _boom(**_kwargs: object) -> object:
        raise ValueError("settings exploded")

    monkeypatch.setattr(offline_mod, "load_repo_settings", _boom)
    workspace = ResolvedWorkspace(cwd=tmp_path, git_common_dir=tmp_path / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=tmp_path, invocation_root=tmp_path)

    with pytest.raises(ValueError, match="settings exploded"):
        await offline_mod._run_offline_diff_review(
            cwd=tmp_path,
            workspace=workspace,
            spec=spec,
            review_root=tmp_path,
            tracing_cli=["--tracing", "--tracing-to", "stdout"],
        )

    assert {key: os.environ.get(key) for key in _KEYS} == before
