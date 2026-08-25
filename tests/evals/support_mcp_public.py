"""Shared helpers for MP1.6 public MCP tool-selection eval RED tests."""

from __future__ import annotations

import json
from typing import Any

from tests.analyzers.support import import_module
from tests.ci.workflow_support import REPO_ROOT

_EVAL_MOD = "mergecraft.evals.mcp_public"
_CASES_PATH = REPO_ROOT / "evals" / "mcp-public" / "cases.json"


def eval_module() -> Any:
    return import_module(_EVAL_MOD)


def load_cases() -> list[dict[str, Any]]:
    assert _CASES_PATH.is_file(), f"missing {_CASES_PATH.relative_to(REPO_ROOT)}"
    data = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list), "evals/mcp-public/cases.json must be a list"
    return data


def require_callable(name: str) -> Any:
    mod = eval_module()
    value = getattr(mod, name, None)
    assert value is not None, f"{_EVAL_MOD}.{name} is not implemented"
    assert callable(value), f"{_EVAL_MOD}.{name} must be callable"
    return value


def case_by_id(case_id: str) -> dict[str, Any]:
    for case in load_cases():
        if case.get("id") == case_id:
            return case
    msg = f"eval case {case_id!r} missing from corpus"
    raise KeyError(msg)


__all__ = ["case_by_id", "eval_module", "load_cases", "require_callable"]
