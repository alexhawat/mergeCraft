"""DG8.1 — deterministic TODO scan for risky additions."""

from __future__ import annotations


def _scan_todo_additions(diff: str) -> list[object]:
    from mergecraft.pr.todo_detection import scan_todo_additions

    return scan_todo_additions(diff)


def test_risky_todo_additions_are_flagged(sample_diff: str) -> None:
    """New TODO/FIXME/HACK lines introduced by the diff are surfaced with path + line."""
    findings = _scan_todo_additions(sample_diff)

    assert findings, "expected at least one TODO finding for the planted guard comment"
    finding = findings[0]
    assert finding.path == "src/auth/login.py"
    assert finding.line >= 1
    text = getattr(finding, "text", "")
    assert "TODO" in text.upper()
    assert finding.risk_level in {"low", "medium", "high"}
