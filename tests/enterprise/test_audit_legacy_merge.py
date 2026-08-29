"""Thermos BR8 follow-up — legacy + primary audit JSONL merge (MCB-21, D13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.enterprise.audit import (
    DEFAULT_AUDIT_REL,
    MERGECRAFT_AUDIT_ROOT_ENV,
    _merge_audit_event_lists,
    load_audit_events,
    resolve_audit_log_path,
)


@pytest.fixture(autouse=True)
def _external_audit_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_root = tmp_path / "audit-root"
    audit_root.mkdir()
    monkeypatch.setenv(MERGECRAFT_AUDIT_ROOT_ENV, str(audit_root))


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def test_load_audit_events_merges_legacy_and_primary_history(tmp_path: Path) -> None:
    """External sink events merge with legacy ``.mergecraft/audit.jsonl`` history."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    legacy_path = workspace / DEFAULT_AUDIT_REL
    _write_jsonl(
        legacy_path,
        [
            {
                "event_type": "legacy_run",
                "outcome": "completed",
                "run_id": "legacy-run-1",
                "context": {"phase": "pre-migration"},
            }
        ],
    )

    primary_path = resolve_audit_log_path(root=workspace)
    _write_jsonl(
        primary_path,
        [
            {
                "event_type": "primary_run",
                "outcome": "completed",
                "run_id": "primary-run-1",
                "context": {"phase": "post-migration"},
            }
        ],
    )

    events = load_audit_events(root=workspace)
    assert [event["run_id"] for event in events] == ["legacy-run-1", "primary-run-1"]
    assert events[0]["event_type"] == "legacy_run"
    assert events[1]["event_type"] == "primary_run"


def test_load_audit_events_dedupes_identical_events_across_sinks(tmp_path: Path) -> None:
    """Duplicate bodies across legacy and primary sinks appear once in export order."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shared = {
        "event_type": "run_lifecycle",
        "outcome": "completed",
        "run_id": "shared-run",
        "context": {"note": "same payload"},
    }

    _write_jsonl(workspace / DEFAULT_AUDIT_REL, [shared])
    _write_jsonl(resolve_audit_log_path(root=workspace), [dict(shared)])

    events = load_audit_events(root=workspace)
    assert len(events) == 1
    assert events[0]["run_id"] == "shared-run"


def test_merge_audit_event_lists_orders_legacy_before_primary() -> None:
    """``_merge_audit_event_lists`` preserves legacy-first ordering with dedupe."""
    legacy = [{"run_id": "legacy", "event_type": "a", "outcome": "ok", "context": {}}]
    primary = [{"run_id": "primary", "event_type": "b", "outcome": "ok", "context": {}}]
    merged = _merge_audit_event_lists(primary, legacy)
    assert [event["run_id"] for event in merged] == ["legacy", "primary"]
