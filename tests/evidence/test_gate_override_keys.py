"""``gates.override`` validates its rule ids, not just its actions (#1564).

The module docstring promises a typo in an override is rejected. Values are
checked against the closed action vocabulary today; keys were accepted as free
text, so ``{has_blocker: block}`` was silently stored, never selected by
``select_rule_id`` and never applied.

Contract: ``resolve_effective_gate_policies`` raises ``ValueError`` for a key
that is not a rule in ``DEFAULT_GATE_POLICIES``, naming the key and listing the
valid rule ids — and it checks the key before the value.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import mergecraft.mcp.public as public_mod
from mergecraft.evidence.gate_policy import (
    DEFAULT_GATE_POLICIES,
    GateAction,
    resolve_effective_gate_policies,
)
from tests.mcp.public_mcp_support import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def test_every_default_rule_id_is_accepted() -> None:
    """Guard: every shipped rule id remains a legal override key."""
    resolved = {
        rule_id: resolve_effective_gate_policies({rule_id: GateAction.BLOCK.value})
        for rule_id in DEFAULT_GATE_POLICIES
    }

    assert all(policy[rule_id] is GateAction.BLOCK for rule_id, policy in resolved.items())
    assert all(set(policy) == set(DEFAULT_GATE_POLICIES) for policy in resolved.values())


def test_bad_value_is_still_rejected() -> None:
    """Guard: a value outside the closed action vocabulary still fails."""
    with pytest.raises(ValueError, match="closed action vocabulary") as excinfo:
        resolve_effective_gate_policies({"low_risk_passing": "not_an_action"})

    message = str(excinfo.value)
    assert "not_an_action" in message
    assert "closed action vocabulary" in message


def test_unknown_rule_id_is_rejected() -> None:
    """Bug: a mistyped rule id is an error that names it and the valid ids."""
    with pytest.raises(ValueError, match="has_blocker") as excinfo:
        resolve_effective_gate_policies({"has_blocker": "block"})

    message = str(excinfo.value)
    assert "has_blocker" in message
    assert "has_blockers" in message


def test_unknown_key_is_reported_before_a_bad_value() -> None:
    """Bug: the key is checked first, so the error names the typo, not the action."""
    with pytest.raises(ValueError, match="has_blocker") as excinfo:
        resolve_effective_gate_policies({"has_blocker": "not_an_action"})

    message = str(excinfo.value)
    assert "has_blocker" in message
    assert "outside the closed action vocabulary" not in message


def test_config_with_a_mistyped_override_key_fails_where_a_bad_value_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: a mistyped override key surfaces exactly where a bad value does."""
    from mergecraft.cli.mcp_serve import build_mcp_tool_context

    init_git_repo(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\ngates:\n  override:\n    has_blocker: block\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    ctx = build_mcp_tool_context(cwd=tmp_path)
    spec = next(tool for tool in public_mod.build_public_tools(ctx) if tool.name == "get_policy")

    payload = json.loads(asyncio.run(spec.execute({})).content[0]["text"])

    error = payload.get("error")
    assert isinstance(error, str), payload
    assert "has_blocker" in error
    assert "policy_rule_ids" not in payload
