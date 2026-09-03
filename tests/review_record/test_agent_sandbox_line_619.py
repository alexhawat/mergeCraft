"""#619 Task 7 — the resolved agentSandbox decision renders in the run record.

``resolve_agent_sandbox_decision`` (config/trust_policy.py) already reaches
the manifest via ``agent_sandbox_manifest_fields``, but never the sticky
progress comment / review preamble a human actually reads. This pins the
new ``- **Agent sandbox:** …`` line in ``render_deterministic_review_block``.
"""

from __future__ import annotations

from mergecraft.config.trust_policy import AgentSandboxDecision
from mergecraft.evidence.build import build_packet
from mergecraft.findings.ledger import render_deterministic_review_block
from tests.review_record.conftest import make_scoped_finding


def _packet():
    return build_packet(
        change_id="acme/demo#619",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=[make_scoped_finding(scope="change", severity="Minor")],
        deterministic_checks=[],
    )


def test_agent_sandbox_line_renders_with_a_decision() -> None:
    decision = AgentSandboxDecision(
        honour=True,
        reason="operator override granted for a same-repo dispatch",
        configured_tier="dispatch",
        resolved_from="base_snapshot",
        event_name="pull_request",
        head_status="same-repo",
        operator_override_requested=True,
        granting_tier="dispatch",
    )
    block = render_deterministic_review_block(
        packet=_packet(),
        trust_tier="trusted",
        agent_sandbox_decision=decision,
    )
    assert "- **Agent sandbox:** `dispatch` tier, head `same-repo` — override granted" in block


def test_agent_sandbox_line_names_a_refused_override() -> None:
    decision = AgentSandboxDecision(
        honour=False,
        reason="fork PR head — override refused",
        configured_tier="merged-only",
        resolved_from="live_load",
        event_name="pull_request",
        head_status="fork",
        operator_override_requested=True,
    )
    block = render_deterministic_review_block(
        packet=_packet(),
        trust_tier="untrusted",
        agent_sandbox_decision=decision,
    )
    assert "- **Agent sandbox:** `merged-only` tier, head `fork` — override refused" in block


def test_agent_sandbox_line_absent_when_no_decision_resolved() -> None:
    block = render_deterministic_review_block(
        packet=_packet(),
        trust_tier="trusted",
    )
    assert "**Agent sandbox:**" not in block
    # Green guard: the neighboring pre-merge lines still render normally.
    assert "- **Trust tier:** `trusted`" in block
