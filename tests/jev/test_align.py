"""J1.8 — withdrawn re-raise and escalate-only semantic dedupe (G14, D7)."""

from __future__ import annotations

from typing import Any

from tests.jev.support import (
    J5_XFAIL,
    TRANSPORT_DIR,
    import_jev,
    load_withdrawn,
    make_agent_finding,
)


def _align() -> Any:
    return import_jev("policy")


@J5_XFAIL
async def test_withdrawn_reraise_is_detected() -> None:
    client_mod = import_jev("client")
    transport = client_mod.RecordedTransport.from_fixture(
        TRANSPORT_DIR / "align_withdrawn_reraise.json"
    )
    finding = make_agent_finding(
        message="wrap_agent_command drops uid without redirecting HOME",
        path="src/mergecraft/utils/privilege.py",
    )
    result = await _align().detect_withdrawn_reraise(
        finding,
        withdrawn_body=load_withdrawn("privilege_drop.md"),
        client=client_mod.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert result.pack_id == "align/v1"
    assert result.same_defect == "same"
    assert result.is_withdrawn_reraise is True
    assert result.scope == "run"
    assert result.blocking is False


@J5_XFAIL
async def test_semantic_dedupe_keeps_the_stronger_severity() -> None:
    client_mod = import_jev("client")
    transport = client_mod.RecordedTransport.from_fixture(TRANSPORT_DIR / "align_same_defect.json")
    weaker = make_agent_finding(
        message="duplicate finding, weaker copy",
        severity="Minor",
    )
    stronger = make_agent_finding(
        message="same defect, stronger copy",
        severity="Critical",
    )
    kept = await _align().semantic_dedupe_pair(
        weaker,
        stronger,
        client=client_mod.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert kept.severity == "Critical"
    assert kept.severity != "Minor"


@J5_XFAIL
async def test_semantic_dedupe_is_escalate_only_when_weaker_arrives_first() -> None:
    """Guard-deletion: keeping the first member must fail this test (N5)."""
    client_mod = import_jev("client")
    transport = client_mod.RecordedTransport.from_fixture(TRANSPORT_DIR / "align_same_defect.json")
    first = make_agent_finding(message="weaker copy arriving first", severity="Minor")
    second = make_agent_finding(message="stronger paraphrase", severity="Critical")
    kept = await _align().semantic_dedupe_pair(
        first,
        second,
        client=client_mod.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert kept.severity == "Critical"
    assert kept.source in {"agent", "classifier"}
