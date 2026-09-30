"""CF5 — SaaS residue out of the standalone runtime (D8).

Removed (no reader anywhere):

- both ``AccountPlan`` literals (``config/settings.py`` and ``mcp/context.py``)
  and the ``config`` re-export;
- ``RunContextData.plan`` and ``ToolContext.plan``;
- ``proxy_model`` / ``proxyModel`` producers and the dead ``or`` reads.

Kept (live or tested): ``api_token`` and ``mcp/upload.py``'s remote arm
(pinned by ``tests/mcp/test_empty_upload_bearer_469.py``), the local fallback,
and the provider/model catalog.
"""

from __future__ import annotations

import dataclasses

import mergecraft.config as config_mod
import mergecraft.config.settings as settings_mod
import mergecraft.mcp.context as context_mod
from mergecraft.config.settings import RepoInfo, RunContextData
from mergecraft.mcp.context import ToolContext
from mergecraft.utils.payload import resolve_payload


def test_tool_context_has_no_plan_field() -> None:
    names = {field.name for field in dataclasses.fields(ToolContext)}
    assert "plan" not in names, f"ToolContext still carries a hosted-plan field: {sorted(names)}"


def test_account_plan_literal_is_removed_everywhere() -> None:
    for module in (context_mod, config_mod, settings_mod):
        assert not hasattr(module, "AccountPlan"), f"{module.__name__}.AccountPlan must be removed"


def test_run_context_data_has_no_hosted_plan_or_proxy_model_fields() -> None:
    fields = RunContextData.model_fields
    assert "plan" not in fields
    assert "proxy_model" not in fields


def test_payload_has_no_proxy_model_key() -> None:
    payload = resolve_payload(resolved_prompt_input="do work")
    assert "proxyModel" not in payload, "the dead proxyModel producer must be removed"


def test_run_context_data_still_carries_api_token() -> None:
    """Keep — ``api_token`` drives the tested upload remote arm."""
    data = RunContextData.model_validate(
        {
            "repo": {"owner": "acme", "name": "demo"},
            "repoSettings": {},
            "apiToken": "upload-token",
        }
    )
    assert data.api_token == "upload-token"


def test_repo_info_is_unchanged() -> None:
    info = RepoInfo(owner="acme", name="demo")
    assert info.data == {}
