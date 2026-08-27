"""DQ1 RED — fail-soft short-id resolution on the render path (#493, DQ2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.analyzers.budget import place_findings
from mergecraft.analyzers.finding import (
    finding_short_id,
    make_finding,
    write_findings_json,
)
from tests.analyzers.support import INLINE_BUDGET

_NON_HEX_FINGERPRINT = "zzzzzzzzzzzzzzzzzzzzzzzzzz"
_HEX_FINGERPRINT = "a83f91c2d4e5f6a7b8c9d0e1"


def _finding(
    *,
    fingerprint: str,
    path: str = "src/demo.py",
    line: int = 10,
) -> object:
    return make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message=f"finding at {path}:{line}",
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
        fingerprint=fingerprint,
    )


def _capture_loguru_warnings() -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="WARNING")
    return captured, sink_id


@pytest.mark.xfail(reason="green after DQ2: fail-soft short-id render path", strict=False)
def test_non_hex_fingerprint_still_renders() -> None:
    """Render path must produce output without assigning a short id."""
    finding = _finding(fingerprint=_NON_HEX_FINGERPRINT)
    placement = place_findings([finding], inline_budget=INLINE_BUDGET)
    assert placement.mechanical_section is not None or placement.deferred_section is not None
    rendered = (placement.mechanical_section or "") + (placement.deferred_section or "")
    assert finding.message in rendered
    assert _NON_HEX_FINGERPRINT not in placement.short_ids


@pytest.mark.xfail(reason="green after DQ2: warning on non-hex fingerprint", strict=False)
def test_non_hex_fingerprint_logs_a_warning_with_path_context() -> None:
    """Skip short-id assignment must warn with fingerprint and path context."""
    from loguru import logger as loguru_logger

    finding = _finding(fingerprint=_NON_HEX_FINGERPRINT, path="src/warn_ctx.py", line=42)
    captured, sink_id = _capture_loguru_warnings()
    try:
        place_findings([finding], inline_budget=INLINE_BUDGET)
    finally:
        loguru_logger.remove(sink_id)

    combined = "\n".join(captured)
    assert combined, "expected a warning when short-id resolution skips non-hex fingerprint"
    assert _NON_HEX_FINGERPRINT in combined
    assert "src/warn_ctx.py" in combined


@pytest.mark.xfail(reason="green after DQ2: mixed hex/non-hex batch render", strict=False)
def test_mixed_batch_renders_hex_findings_with_ids_and_others_without() -> None:
    """Hex fingerprints keep short ids; non-hex findings render without them."""
    hex_finding = _finding(fingerprint=_HEX_FINGERPRINT, path="src/hex.py", line=1)
    non_hex_finding = _finding(
        fingerprint=_NON_HEX_FINGERPRINT,
        path="src/nonhex.py",
        line=2,
    )
    placement = place_findings([hex_finding, non_hex_finding], inline_budget=INLINE_BUDGET)
    rendered = (placement.mechanical_section or "") + (placement.deferred_section or "")
    hex_short_id = finding_short_id(_HEX_FINGERPRINT)
    assert hex_short_id in rendered
    assert _NON_HEX_FINGERPRINT not in placement.short_ids


def test_export_path_stays_strict_on_non_hex(tmp_path: Path) -> None:
    """Wire export must reject non-hex fingerprints (D9 strict path)."""
    finding = _finding(fingerprint=_NON_HEX_FINGERPRINT)
    payload = [
        {
            **finding.model_dump(),
            "fingerprint": _NON_HEX_FINGERPRINT,
        }
    ]
    with pytest.raises(ValueError, match=r"lowercase hex"):
        write_findings_json(tmp_path / "findings.json", payload)


def test_explain_by_id_stays_strict_on_non_hex() -> None:
    """Strict short-id helpers must reject non-hex fingerprints for explain/export."""
    with pytest.raises(ValueError, match=r"lowercase hex"):
        finding_short_id(_NON_HEX_FINGERPRINT)
