"""CA #452 RED — short id rendered consistently across every output surface (D2).

Pins that markdown, structured JSON, agent JSONL, and PR comment renderers
surface the same ``MC-…`` id for one ``Finding``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tests.analyzers.support_short_id import require_callable, sample_finding

_MC_ID_RE = re.compile(r"MC-[0-9a-f]{6,}")


def _short_id_for(finding: Any) -> str:
    finding_short_id = require_callable("finding_short_id")
    return finding_short_id(finding.fingerprint)


def _extract_short_id(payload: dict[str, Any]) -> str:
    for key in ("short_id", "id", "finding_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("MC-"):
            return value
    msg = f"no MC- short id field in payload keys={sorted(payload)}"
    raise AssertionError(msg)


def test_render_finding_markdown_includes_short_id() -> None:
    """Markdown review output quotes the stable short id."""
    render_finding_markdown = require_callable("render_finding_markdown")
    finding = sample_finding()
    short_id = _short_id_for(finding)
    rendered = render_finding_markdown(finding, short_id=short_id)
    assert short_id in rendered
    assert _MC_ID_RE.search(rendered)


def test_finding_json_record_includes_short_id_field() -> None:
    """Structured JSON exports carry the short id beside the fingerprint."""
    finding_json_record = require_callable("finding_json_record")
    finding = sample_finding()
    short_id = _short_id_for(finding)
    payload = finding_json_record(finding, short_id=short_id)
    assert payload["fingerprint"] == finding.fingerprint
    assert _extract_short_id(payload) == short_id


def test_finding_agent_jsonl_record_includes_short_id_field() -> None:
    """Agent JSONL finding events include the same short id as structured JSON."""
    finding_json_record = require_callable("finding_json_record")
    finding = sample_finding()
    short_id = _short_id_for(finding)
    payload = finding_json_record(finding, short_id=short_id)
    assert _extract_short_id(payload) == short_id
    # round-trip as JSONL line without losing the id
    line = json.dumps({"event": "finding", "finding": payload}, ensure_ascii=False)
    parsed = json.loads(line)["finding"]
    assert _extract_short_id(parsed) == short_id


def test_render_finding_pr_comment_includes_short_id() -> None:
    """PR inline comment bodies surface the short id for human quoting."""
    render_finding_pr_comment = require_callable("render_finding_pr_comment")
    finding = sample_finding()
    short_id = _short_id_for(finding)
    body = render_finding_pr_comment(finding, short_id=short_id)
    assert short_id in body
    assert _MC_ID_RE.search(body)


def test_all_output_surfaces_share_the_same_short_id() -> None:
    """Acceptance — one finding renders the identical ``MC-…`` everywhere."""
    render_finding_markdown = require_callable("render_finding_markdown")
    finding_json_record = require_callable("finding_json_record")
    render_finding_pr_comment = require_callable("render_finding_pr_comment")

    finding = sample_finding()
    short_id = _short_id_for(finding)

    markdown = render_finding_markdown(finding, short_id=short_id)
    json_record = finding_json_record(finding, short_id=short_id)
    jsonl_record = finding_json_record(finding, short_id=short_id)
    pr_comment = render_finding_pr_comment(finding, short_id=short_id)

    assert short_id in markdown
    assert _extract_short_id(json_record) == short_id
    assert _extract_short_id(jsonl_record) == short_id
    assert short_id in pr_comment
