"""BR1.2 / BR3 — structural JSON / JSONL analyzer redaction (MCB-04, D4)."""

from __future__ import annotations

import json
from pathlib import Path

# Fixed trufflehog-style canary without a pattern prefix.
_TRUFFLEHOG_CANARY = "9fK2mQx7Lp4Rv8Nw3Tz1Hj4Kd6"
_JSON_CANARY = f'{{"Raw": "{_TRUFFLEHOG_CANARY}"}}'
_JSONL_LINE_A = json.dumps({"line": 1, "Raw": _TRUFFLEHOG_CANARY})
_JSONL_LINE_B = json.dumps({"line": 2, "note": "clean"})
_JSONL_BLOB = f"{_JSONL_LINE_A}\n{_JSONL_LINE_B}\n"


def test_json_output_is_redacted() -> None:
    """MCB-04: JSON analyzer output must redact non-prefixed secret values."""
    from mergecraft.analyzers.redact import redact_analyzer_output

    redacted = redact_analyzer_output(_JSON_CANARY, tool_id="trufflehog")
    assert _TRUFFLEHOG_CANARY not in redacted


def test_redacted_json_still_parses() -> None:
    """D4: structural redaction keeps downstream JSON parseable."""
    from mergecraft.analyzers.redact import redact_analyzer_output

    redacted = redact_analyzer_output(_JSON_CANARY, tool_id="trufflehog")
    payload = json.loads(redacted)
    assert isinstance(payload, dict)


def test_jsonl_is_redacted_line_wise() -> None:
    """MCB-04: JSONL is handled per line, not wholesale ``redact_secrets``."""
    from mergecraft.analyzers.redact import redact_analyzer_output

    redacted = redact_analyzer_output(_JSONL_BLOB, tool_id="trufflehog_jsonl")
    assert _TRUFFLEHOG_CANARY not in redacted
    lines = [line for line in redacted.splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)


def test_trufflehog_fixture_canary_never_reaches_persisted_output(tmp_path: Path) -> None:
    """MCB-04: persisted analyzer blobs must not retain the planted canary."""
    from mergecraft.analyzers.parse import persist_analyzer_output
    from mergecraft.analyzers.redact import assert_no_canary, redact_analyzer_output

    redacted = redact_analyzer_output(_JSON_CANARY, tool_id="trufflehog")
    assert_no_canary(redacted, _TRUFFLEHOG_CANARY)
    out_dir = tmp_path / ".mergecraft" / "analyzer-runs"
    out_dir.mkdir(parents=True)
    path = persist_analyzer_output(redacted, tmpdir=out_dir, tool_id="trufflehog")
    material = path.read_text(encoding="utf-8")
    assert_no_canary(material, _TRUFFLEHOG_CANARY)
