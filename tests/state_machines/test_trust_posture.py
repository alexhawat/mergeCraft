"""Trust posture frozen snapshot."""

from __future__ import annotations

from mergecraft.analyzers.trust_posture import trust_posture_from_tool_state
from mergecraft.mcp.tool_state import init_tool_state


def test_untrusted_authority_blocks_github_approve() -> None:
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    ts.trust_tier = "untrusted"
    ts.authority_trust = "untrusted"
    posture = trust_posture_from_tool_state(ts)
    assert posture.may_approve_on_github() is False


def test_trusted_execution_allows_full_analyzers() -> None:
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    ts.trust_tier = "trusted"
    posture = trust_posture_from_tool_state(ts, analyzers_mode="full")
    assert posture.may_run_full_analyzers() is True
