"""Shared helpers for plan 18 W1.2 — Codex credential-broker wire-up tests."""

from __future__ import annotations

import ast
import importlib
import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context
from tests.security.support_agent_isolation import (
    REAL_OPENAI_API_KEY_FIXTURE,
    codex_module_path,
    load_broker_module,
    require_broker_symbol,
)

__all__ = ["REAL_OPENAI_API_KEY_FIXTURE"]

if TYPE_CHECKING:
    from mergecraft.agents.shared import AgentRunContext


USABLE_SUBSCRIPTION_AUTH_JSON = json.dumps(
    {
        "tokens": {
            "access_token": "chatgpt-subscription-access-token",
            "refresh_token": "chatgpt-subscription-refresh-token",
        }
    }
)


def load_codex_module() -> Any:
    try:
        return importlib.import_module("mergecraft.agents.codex")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.codex not implemented: {exc}")


def parse_codex_config(config_path: Path | str) -> dict[str, Any]:
    return tomllib.loads(Path(config_path).read_text(encoding="utf-8"))


def brokered_codex_context(
    tmp_path: Path,
    *,
    resolved_model: str = "openai/gpt-5.3-codex",
    mcp_server_url: str = "http://127.0.0.1:3764/mcp",
    mcp_auth_token: str = "mcp-bearer-pin-token",
) -> AgentRunContext:
    ctx = make_agent_run_context(tmp_path, resolved_model=resolved_model)
    ctx.mcp_server_url = mcp_server_url
    ctx.mcp_auth_token = mcp_auth_token
    return ctx


def prepare_codex_brokered_run(
    ctx: AgentRunContext,
    *,
    openai_api_key: str = REAL_OPENAI_API_KEY_FIXTURE,
) -> Any:
    """W3 entry point — start broker, build env, auth, and MCP config."""
    codex_module = load_codex_module()
    prepare = getattr(codex_module, "prepare_codex_brokered_run", None)
    if prepare is None:
        pytest.fail("mergecraft.agents.codex.prepare_codex_brokered_run not implemented")
    return prepare(ctx, openai_api_key=openai_api_key)


def resolve_codex_broker_posture() -> Any:
    module = load_broker_module()
    resolve = require_broker_symbol(module, "resolve_codex_broker_posture")
    return resolve()


def broker_run_record_fields(posture: Any) -> dict[str, str]:
    module = load_broker_module()
    if hasattr(module, "broker_run_record_fields"):
        return dict(module.broker_run_record_fields(posture))
    if hasattr(module, "codex_broker_run_record"):
        return dict(module.codex_broker_run_record(posture))
    pytest.fail(f"{module.__name__} missing broker run-record helper")


def referenced_names_in_function(function_name: str) -> set[str]:
    """Return names referenced in ``function_name`` inside ``agents/codex.py``."""
    source = codex_module_path().read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            names: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    names.add(child.id)
                elif isinstance(child, ast.Attribute):
                    names.add(child.attr)
            return names
    return set()


def auth_json_text(codex_module: Any, ctx: AgentRunContext) -> str:
    codex_home = codex_module._codex_home(ctx)
    auth_path = codex_home / "auth.json"
    if not auth_path.exists():
        return ""
    return auth_path.read_text(encoding="utf-8")
