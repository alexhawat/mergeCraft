"""The merge-evidence packet carries the run's changed-line coverage.

``coverage`` is a minor bump of the packet schema: ``hunks_total``, ``hunks_covered``,
``lines_total``, ``lines_covered``, ``uncovered[{path,start_line,end_line,cause}]`` and
``complete``. The orchestrator writes it from the run's own checkout and delivery state;
no agent can set it. The ``mergecraft-approval`` summary states it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    MergeEvidencePacket,
    packet_output_schema,
)
from mergecraft.evidence.run_packet import build_run_packet
from tests.evidence.support import sample_minimal_packet_dict
from tests.evidence.test_run_packet import _make_ctx

if TYPE_CHECKING:
    from pathlib import Path

_AUTHORITATIVE = (
    "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
    "@@ -1,2 +1,3 @@\n keep\n+added\n keep\n"
    "diff --git a/src/b.py b/src/b.py\n--- a/src/b.py\n+++ b/src/b.py\n"
    "@@ -5,0 +6,4 @@\n+one\n+two\n+three\n+four\n"
)
_DELIVERED_A_ONLY = _AUTHORITATIVE.split("diff --git a/src/b.py")[0]


@pytest.fixture(autouse=True)
def _isolate_packet_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)


def test_the_schema_version_is_bumped_by_a_minor_for_the_coverage_section() -> None:
    major, minor, _patch = (int(part) for part in PACKET_SCHEMA_VERSION.split("."))

    assert (major, minor) >= (1, 14)


def test_coverage_is_in_the_packet_json_schema_with_every_field() -> None:
    schema = packet_output_schema()

    coverage = schema["properties"]["coverage"]
    props = coverage.get("properties") or coverage["anyOf"][0].get("properties")
    assert props is not None, coverage
    assert {
        "hunks_total",
        "hunks_covered",
        "lines_total",
        "lines_covered",
        "uncovered",
        "complete",
    } <= set(props)


def test_an_uncovered_row_names_path_range_and_cause() -> None:
    schema = packet_output_schema()
    text = json.dumps(schema["properties"]["coverage"]) + json.dumps(schema.get("$defs", {}))

    for token in ("start_line", "end_line", "cause", "diff_truncated", "no_inline_patch"):
        assert token in text
    for cause in ("excluded_generated", "not_delivered", "budget_exhausted"):
        assert cause in text


def test_a_packet_without_coverage_still_validates() -> None:
    packet = MergeEvidencePacket.model_validate(sample_minimal_packet_dict())

    assert packet.coverage is None


def test_coverage_round_trips_through_json() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(authoritative_diff=_AUTHORITATIVE, delivered_diff=_DELIVERED_A_ONLY)
    payload = sample_minimal_packet_dict()
    payload["coverage"] = section.model_dump(mode="json")

    packet = MergeEvidencePacket.model_validate(payload)

    assert packet.coverage == section
    assert MergeEvidencePacket.model_validate_json(packet.model_dump_json()) == packet


def test_the_run_packet_records_a_complete_coverage_for_a_fully_delivered_diff(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path, diff_text=_AUTHORITATIVE)
    ctx.tool_state.coverage.authoritative_diff = _AUTHORITATIVE

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.coverage is not None
    assert packet.coverage.complete is True
    assert packet.coverage.hunks_total == packet.coverage.hunks_covered == 2


def test_the_run_packet_lists_a_hunk_the_reviewer_never_received(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, diff_text=_DELIVERED_A_ONLY)
    ctx.tool_state.coverage.authoritative_diff = _AUTHORITATIVE

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.coverage is not None
    assert packet.coverage.complete is False
    [row] = packet.coverage.uncovered
    assert (row.path, row.start_line, row.end_line, row.cause) == (
        "src/b.py",
        6,
        9,
        "not_delivered",
    )


def test_the_run_packet_records_files_the_api_sent_no_patch_for(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, diff_text=_AUTHORITATIVE)
    ctx.tool_state.coverage.authoritative_diff = _AUTHORITATIVE
    ctx.tool_state.coverage.unreviewable_paths = ["big/huge.py"]

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.coverage is not None
    assert [(r.path, r.cause) for r in packet.coverage.uncovered] == [
        ("big/huge.py", "no_inline_patch")
    ]
    assert packet.coverage.complete is False


def test_the_run_packet_records_a_truncated_files_listing(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, diff_text=_AUTHORITATIVE)
    ctx.tool_state.coverage.authoritative_diff = _AUTHORITATIVE
    ctx.tool_state.coverage.diff_truncated = True

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.coverage is not None
    assert [r.cause for r in packet.coverage.uncovered] == ["diff_truncated"]


def test_a_mediated_read_recorded_in_the_trajectory_covers_a_missing_hunk(
    tmp_path: Path,
) -> None:
    from mergecraft.evidence.trajectory import record_tool_call

    ctx = _make_ctx(tmp_path, diff_text=_DELIVERED_A_ONLY)
    ctx.tool_state.coverage.authoritative_diff = _AUTHORITATIVE
    record_tool_call(
        ctx.tool_state,
        tool="shell",
        arguments={"command": "cat src/b.py"},
        ok=True,
    )

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.coverage is not None
    assert packet.coverage.complete is True


def test_a_run_with_no_diff_records_no_coverage_section(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, diff_text=None)

    assert build_run_packet(ctx, run_succeeded=True).coverage is None


def test_the_policy_is_read_from_the_pinned_settings_snapshot(tmp_path: Path) -> None:
    from mergecraft.evidence.coverage import coverage_policy

    from mergecraft.config.settings import RepoSettings
    from mergecraft.config.settings_snapshot import capture_run_scope_snapshot

    ctx = _make_ctx(tmp_path, diff_text=_AUTHORITATIVE)
    assert coverage_policy(ctx) == "inconclusive"

    warn = RepoSettings.model_validate({"review": {"coverage": {"onIncomplete": "warn"}}})
    capture_run_scope_snapshot(ctx, root=tmp_path, settings=warn)

    assert coverage_policy(ctx) == "warn"
