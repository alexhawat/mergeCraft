"""Lane A AP1.4 — OpenCode review-mode permission narrowing (MCB-06 / D4)."""

from __future__ import annotations

import json
from pathlib import Path

from mergecraft.agents.opencode import build_security_config
from mergecraft.agents.shared import AgentRunContext
from mergecraft.mcp.tool_state import init_tool_state


def _ctx(tmp_path: Path) -> AgentRunContext:
    return AgentRunContext(
        payload={"shell": "restricted", "push": "restricted"},
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions="review",
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_auth_token="token",
    )


def _permissions(tmp_path: Path) -> dict[str, object]:
    raw = build_security_config(_ctx(tmp_path), "anthropic/claude-sonnet")
    config = json.loads(raw)
    perms = config.get("permission")
    assert isinstance(perms, dict)
    return perms


def test_review_mode_denies_webfetch(tmp_path: Path) -> None:
    assert _permissions(tmp_path).get("webfetch") == "deny"


def test_review_mode_external_directory_allowlists_checkout_and_evidence(
    tmp_path: Path,
) -> None:
    from tests.agents.conftest import make_agent_run_context

    from mergecraft.agents.opencode import _evidence_dir

    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet")
    external = _permissions(tmp_path).get("external_directory")
    assert isinstance(external, dict)
    checkout = tmp_path.resolve().as_posix()
    evidence = _evidence_dir(ctx).resolve().as_posix()
    assert external.get("*") == "deny"
    assert external.get(checkout) == "allow"
    assert external.get(f"{checkout}/**") == "allow"
    assert evidence != checkout
    assert external.get(evidence) == "allow"
    assert external.get(f"{evidence}/**") == "allow"


def test_review_mode_denies_edit(tmp_path: Path) -> None:
    assert _permissions(tmp_path).get("edit") == "deny"


def test_review_mode_read_is_allowlisted_to_the_checkout(tmp_path: Path) -> None:
    read = _permissions(tmp_path).get("read")
    assert read != {"*": "allow"}
    assert isinstance(read, dict)
    assert any(str(tmp_path) in str(v) or v == "allow" for v in read.values())


def test_review_mode_denies_git_config_under_checkout(tmp_path: Path) -> None:
    read = _permissions(tmp_path).get("read")
    assert isinstance(read, dict)
    checkout = tmp_path.resolve().as_posix()
    assert read.get(f"{checkout}/.git/config") == "deny"
    assert read.get(f"{checkout}/.git/**") == "deny"


def test_bash_stays_denied(tmp_path: Path) -> None:
    """Guard — bash denial is already true on trunk; must not regress under AP5."""
    assert _permissions(tmp_path).get("bash") == "deny"


def _split_ctx(tmp_path: Path) -> tuple[AgentRunContext, Path]:
    """A run whose temp dir (and diff) sits outside the checkout, as in production."""
    from mergecraft.mcp.verdict import establish_offline_review_scope

    run_dir = tmp_path / "run"
    repo = tmp_path / "repo"
    run_dir.mkdir()
    repo.mkdir()
    ctx = AgentRunContext(
        payload={"shell": "restricted", "push": "restricted"},
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(run_dir),
        subagent_denied_tools=(),
        instructions="review",
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        mcp_auth_token="token",
    )
    establish_offline_review_scope(ctx.tool_state, diff_path=str(run_dir / "review.diff"))
    return ctx, run_dir


def test_the_review_diff_outside_the_checkout_is_reachable(tmp_path: Path) -> None:
    """OpenCode asks for ``<dir>/**``; without this grant ``read`` refuses the diff."""
    ctx, run_dir = _split_ctx(tmp_path)

    external = json.loads(build_security_config(ctx, "anthropic/claude-sonnet"))["permission"][
        "external_directory"
    ]

    assert external[f"{run_dir.resolve().as_posix()}/**"] == "allow"


def test_private_temp_dir_children_stay_denied(tmp_path: Path) -> None:
    """The isolated auth store, config dir and scratch HOME must not ride the diff grant."""
    ctx, run_dir = _split_ctx(tmp_path)

    external = json.loads(build_security_config(ctx, "anthropic/claude-sonnet"))["permission"][
        "external_directory"
    ]

    keys = list(external)
    grant = keys.index(f"{run_dir.resolve().as_posix()}/**")
    for child in ("opencode-xdg-data", "opencode-xdg-config", "home"):
        deny = f"{run_dir.resolve().as_posix()}/{child}/**"
        assert external[deny] == "deny"
        # Last match wins: each deny must come after the grant it narrows.
        assert keys.index(deny) > grant
