"""BR1.6 / BR7 — audit log hash chain verification (MCB-21, D13)."""

from __future__ import annotations

import json
from pathlib import Path


def _write_chain(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def test_verify_detects_a_rewritten_record(tmp_path: Path) -> None:
    """D13: tampered records break the hash chain."""
    from mergecraft.enterprise.audit import verify_audit_chain

    path = tmp_path / "audit.jsonl"
    _write_chain(
        path,
        [
            {"event_type": "a", "outcome": "ok", "context": {}, "artifact_id": "1"},
            {"event_type": "b", "outcome": "ok", "context": {}, "artifact_id": "2"},
        ],
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["outcome"] = "tampered"
    lines[1] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    breaks = verify_audit_chain(path)
    assert breaks == [2]


def test_verify_detects_a_truncated_log(tmp_path: Path) -> None:
    """D13: truncation is detectable via chain verification."""
    from mergecraft.enterprise.audit import verify_audit_chain

    path = tmp_path / "audit.jsonl"
    _write_chain(
        path,
        [
            {"event_type": "a", "outcome": "ok", "context": {}, "artifact_id": "1"},
            {"event_type": "b", "outcome": "ok", "context": {}, "artifact_id": "2"},
            {"event_type": "c", "outcome": "ok", "context": {}, "artifact_id": "3"},
        ],
    )
    lines = path.read_text(encoding="utf-8").splitlines()[:2]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    breaks = verify_audit_chain(path)
    assert breaks
