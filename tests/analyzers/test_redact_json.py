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


# --- Mixed JSON + plaintext -------------------------------------------------
#
# Output that *begins* with valid JSON routes into the mixed-content scanner,
# which copied every non-JSON slice through verbatim. A plaintext secret after
# the JSON was returned unredacted. Only this ordering leaked: text-first
# output returns earlier, through the plain `redact_secrets` path.

_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz1234"


def test_a_secret_after_leading_json_is_redacted() -> None:
    """The reported case."""
    from mergecraft.analyzers.redact import redact_analyzer_output

    out = redact_analyzer_output(f'{{"a":1}} token={_TOKEN}', tool_id="t")

    assert _TOKEN not in out
    assert '"a": 1' in out, "the JSON half must survive"


def test_a_secret_between_two_json_documents_is_redacted() -> None:
    from mergecraft.analyzers.redact import redact_analyzer_output

    out = redact_analyzer_output(f'{{"a":1}} {_TOKEN} {{"b":2}}', tool_id="t")

    assert _TOKEN not in out
    assert '"a": 1' in out
    assert '"b": 2' in out


def test_a_secret_before_json_is_still_redacted() -> None:
    """Guard the other ordering, which took a different code path."""
    from mergecraft.analyzers.redact import redact_analyzer_output

    out = redact_analyzer_output(f'token={_TOKEN} {{"a":1}}', tool_id="t")

    assert _TOKEN not in out


def test_a_secret_split_by_an_unparsable_brace_is_redacted() -> None:
    """A stray brace must not split a secret out of the pattern's reach.

    The scanner emits an unparsable ``{`` one character at a time. Redacting
    each fragment as it was appended would let a brace inside a secret break
    the match; the literal run is buffered and redacted whole instead.
    """
    from mergecraft.analyzers.redact import redact_analyzer_output

    out = redact_analyzer_output(f'{{"a":1}} prefix{{ {_TOKEN}', tool_id="t")

    assert _TOKEN not in out


def test_benign_mixed_content_is_left_intact() -> None:
    """Guard the guard: redacting literal runs must not mangle ordinary text."""
    from mergecraft.analyzers.redact import redact_analyzer_output

    out = redact_analyzer_output('{"a":1} plain tail', tool_id="t")

    assert "plain tail" in out
    assert '"a": 1' in out
