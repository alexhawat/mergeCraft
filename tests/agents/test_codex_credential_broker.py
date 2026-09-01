"""Plan 18 W1.2 — Codex credential-broker wire-up RED contracts (implementation W3).

Pins throwaway bearer env, auth.json hygiene (D3), loopback ``model_providers``
(D1/D4), subscription-auth inactivity (D3a), broker fail-closed posture (D10),
and lane-B sandbox symbol isolation (D8).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.agents.support_codex_credential_broker import (
    USABLE_SUBSCRIPTION_AUTH_JSON,
    auth_json_text,
    broker_run_record_fields,
    brokered_codex_context,
    load_codex_module,
    parse_codex_config,
    prepare_codex_brokered_run,
    referenced_names_in_function,
    resolve_codex_broker_posture,
)
from tests.security.support_agent_isolation import (
    LANE_B_SANDBOX_SYMBOLS,
    REAL_OPENAI_API_KEY_FIXTURE,
    assert_credential_absent,
    load_broker_module,
    require_broker_symbol,
)

from mergecraft.types import MERGECRAFT_MCP_NAME, MERGECRAFT_VERIFIER_MCP_NAME


def _simulate_root_chown(monkeypatch: pytest.MonkeyPatch, codex_module: Any) -> None:
    from mergecraft.utils import privilege as privilege_module

    class _FakePw:
        pw_name = "mergecraft"
        pw_uid = 1001
        pw_gid = 1001
        pw_dir = "/home/mergecraft"

    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege_module, "_in_action_image", lambda: True)
    monkeypatch.setattr(codex_module, "_FORBIDDEN_TEMP_ROOTS", ())
    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _FakePw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    captured: list[list[str]] = []

    def _fake_chown_run(cmd: list[str], **kwargs: object) -> object:
        captured.append(list(cmd))
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_chown_run)


def _baseline_mcp_tables(ctx_path: Path) -> dict[str, Any]:
    """Capture MCP table shape before broker wiring for unchanged-table assertions."""
    codex_module = load_codex_module()
    ctx = brokered_codex_context(ctx_path)
    config_path = codex_module.write_mcp_config(ctx)
    parsed = parse_codex_config(Path(config_path))
    return parsed.get("mcp_servers", {})


def test_brokered_agent_env_carries_throwaway_not_live_openai_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under the broker fixture the agent env gets a throwaway bearer, not ``OPENAI_API_KEY``."""
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    ctx = brokered_codex_context(tmp_path)
    prepared = prepare_codex_brokered_run(ctx)

    env = prepared.agent_env
    bearer_env = require_broker_symbol(load_broker_module(), "CODEX_BROKER_BEARER_ENV")
    assert env.get(bearer_env), "throwaway bearer must be present in agent env"
    assert env.get("OPENAI_API_KEY") != REAL_OPENAI_API_KEY_FIXTURE
    assert REAL_OPENAI_API_KEY_FIXTURE not in env.values()


def test_auth_json_contains_no_real_api_credential_after_setup_and_chown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3 — ``$CODEX_HOME/auth.json`` after ``_setup_codex_auth`` + chown has no real key."""
    codex_module = load_codex_module()
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    _simulate_root_chown(monkeypatch, codex_module)

    ctx = brokered_codex_context(tmp_path)
    prepared = prepare_codex_brokered_run(ctx)
    _ = prepared.agent_env

    auth_text = auth_json_text(codex_module, ctx)
    assert auth_text, "brokered API-key path must still emit auth.json or an explicit stub"
    assert_credential_absent(auth_text)
    assert REAL_OPENAI_API_KEY_FIXTURE not in auth_text


def test_model_providers_base_url_points_at_loopback_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``model_providers.<id>.base_url`` must be the loopback broker with ``/v1`` (D1)."""
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    ctx = brokered_codex_context(tmp_path)
    prepared = prepare_codex_brokered_run(ctx)

    codex_module = load_codex_module()
    config_path = codex_module._codex_home(ctx) / "config.toml"
    parsed = parse_codex_config(config_path)
    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    assert providers, "model_providers must be populated"

    broker_base = prepared.broker_base_url
    assert broker_base is not None
    assert broker_base.startswith("http://127.0.0.1:")
    assert broker_base.endswith("/v1")
    for block in providers.values():
        assert isinstance(block, dict)
        assert block.get("base_url") == broker_base


def test_mcp_table_unchanged_under_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broker wiring must not alter the MCP server table."""
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)

    before = _baseline_mcp_tables(tmp_path)
    ctx = brokered_codex_context(tmp_path)
    prepare_codex_brokered_run(ctx)
    codex_module = load_codex_module()
    after = parse_codex_config(codex_module._codex_home(ctx) / "config.toml").get("mcp_servers", {})

    assert before.keys() == after.keys()
    for name in (MERGECRAFT_MCP_NAME, MERGECRAFT_VERIFIER_MCP_NAME):
        if name in before:
            assert before[name] == after[name]


def test_subscription_auth_marks_broker_inactive_and_run_record_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3a — subscription auth keeps the broker inactive and records that explicitly."""
    monkeypatch.setenv("CODEX_AUTH_JSON", USABLE_SUBSCRIPTION_AUTH_JSON)
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)

    posture = resolve_codex_broker_posture()
    assert posture.active is False
    assert getattr(posture, "auth_mode", "") == "subscription"
    reason = str(getattr(posture, "reason", ""))
    assert reason, "inactive posture must carry an explicit reason"
    assert "inactive" in reason.casefold() or "subscription" in reason.casefold()

    record = broker_run_record_fields(posture)
    record_text = json.dumps(record)
    assert "inactive" in record_text.casefold() or "subscription" in record_text.casefold()


def test_subscription_auth_leaves_auth_json_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3a — subscription path must not delete or broker ``auth.json``."""
    codex_module = load_codex_module()
    monkeypatch.setenv("CODEX_AUTH_JSON", USABLE_SUBSCRIPTION_AUTH_JSON)
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    _simulate_root_chown(monkeypatch, codex_module)

    ctx = brokered_codex_context(tmp_path)
    codex_home = codex_module._codex_home(ctx)
    codex_module._setup_codex_auth(ctx, codex_home=codex_home)
    from mergecraft.utils.privilege import prepare_workspace_for_agent

    prepare_workspace_for_agent(str(codex_home))

    assert auth_json_text(codex_module, ctx) == USABLE_SUBSCRIPTION_AUTH_JSON


def test_broker_start_failure_does_not_silently_reinject_openai_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D10 — broker start failure must refuse or disclose unbrokered mode, never silent fallback."""
    broker_module = load_broker_module()
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)

    def _boom(*_args: object, **_kwargs: object) -> None:
        msg = "broker refused to start"
        raise RuntimeError(msg)

    monkeypatch.setattr(broker_module, "credential_broker", _boom)

    ctx = brokered_codex_context(tmp_path)
    codex_module = load_codex_module()
    prepare = getattr(codex_module, "prepare_codex_brokered_run", None)
    assert prepare is not None

    # Implementation may refuse (exception) or return an explicit unbrokered record.
    outcome: Any
    try:
        outcome = prepare(ctx, openai_api_key=REAL_OPENAI_API_KEY_FIXTURE)
    except Exception as exc:
        message = str(exc).casefold()
        assert "broker" in message or "credential" in message
        return

    env = outcome.agent_env
    record = broker_run_record_fields(outcome.posture)
    record_text = json.dumps(record).casefold()
    disclosed = (
        "unbrokered" in record_text
        or "inactive" in record_text
        or "failed" in record_text
        or "refused" in record_text
    )
    assert disclosed, "broker failure must be recorded explicitly (D10)"
    if env.get("OPENAI_API_KEY") == REAL_OPENAI_API_KEY_FIXTURE:
        pytest.fail("silent fallback re-injected the live OPENAI_API_KEY")


def test_build_env_does_not_reference_lane_b_sandbox_symbols() -> None:
    """D8 — broker wire-up must not touch lane-B sandbox gate symbols."""
    referenced = referenced_names_in_function("_build_env")
    overlap = referenced & set(LANE_B_SANDBOX_SYMBOLS)
    assert not overlap, f"_build_env must not reference lane-B symbols: {sorted(overlap)}"


def test_prepare_codex_brokered_run_does_not_reference_lane_b_sandbox_symbols() -> None:
    """D8 — dedicated broker prep must stay clear of lane-B sandbox gate symbols."""
    codex_module = load_codex_module()
    if not hasattr(codex_module, "prepare_codex_brokered_run"):
        pytest.fail("mergecraft.agents.codex.prepare_codex_brokered_run not implemented")

    referenced = referenced_names_in_function("prepare_codex_brokered_run")
    overlap = referenced & set(LANE_B_SANDBOX_SYMBOLS)
    assert not overlap, (
        f"prepare_codex_brokered_run must not reference lane-B symbols: {sorted(overlap)}"
    )


def test_lane_b_sandbox_symbols_remain_defined_in_codex_module() -> None:
    """D8 regression guard — lane-B symbols must remain present for parallel lane B."""
    codex_module = load_codex_module()
    for symbol in LANE_B_SANDBOX_SYMBOLS:
        assert hasattr(codex_module, symbol), f"{symbol} must remain in agents/codex.py"
