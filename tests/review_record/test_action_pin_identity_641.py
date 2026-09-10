"""#641 — run record surfaces baked image source next to the Action pin."""

from __future__ import annotations

from mergecraft.evidence.build import build_packet
from mergecraft.findings.ledger import render_deterministic_review_block
from tests.review_record.conftest import make_scoped_finding


def _packet():
    return build_packet(
        change_id="acme/demo#641",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["action.yml"],
        findings=[make_scoped_finding(scope="change", severity="Minor")],
        deterministic_checks=[],
    )


def test_run_record_lists_action_pin_and_image_source() -> None:
    pin = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    source = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    block = render_deterministic_review_block(
        packet=_packet(),
        trust_tier="trusted",
        action_pin_sha=pin,
        image_source_sha=source,
    )
    assert f"- **Action pin:** `{pin}`" in block
    assert f"- **Image source:** `{source}`" in block
    assert "Pin lag" not in block


def test_run_record_flags_pin_equal_to_baked_source() -> None:
    sha = "cccccccccccccccccccccccccccccccccccccccc"
    block = render_deterministic_review_block(
        packet=_packet(),
        trust_tier="trusted",
        action_pin_sha=sha,
        image_source_sha=sha,
    )
    assert "- **Pin lag:**" in block
    assert "#641" in block
