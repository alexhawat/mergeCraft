"""Shared YAML helpers for workflow lint scripts and CI contract tests."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import Any

import yaml

_PERMISSION_RANK = {
    "none": 0,
    "read": 1,
    "write": 2,
}


def load_workflow_file(path: Path) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def permission_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def permission_level_satisfies(have: str | None, need: str) -> bool:
    if have is None:
        return False
    have_rank = _PERMISSION_RANK.get(have, -1)
    need_rank = _PERMISSION_RANK.get(need, -1)
    if need_rank < 0:
        return have == need
    return have_rank >= need_rank


def missing_permissions(
    caller: dict[str, str],
    callee: dict[str, str],
) -> dict[str, str]:
    missing: dict[str, str] = {}
    for scope, need in callee.items():
        if not permission_level_satisfies(caller.get(scope), need):
            missing[scope] = need
    return missing
