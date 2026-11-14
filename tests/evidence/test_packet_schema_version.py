"""The packet schema version and its documentation move together (#1056 part 2).

``BlastRadiusClassification`` gained ``reasons`` and ``checklist``, an additive
shape change, so ``PACKET_SCHEMA_VERSION`` took the next minor: ``1.18.0``; the
lite tier's triage fields then moved it to ``1.19.0``, and ``triage.reapproval``
(#1284) to ``1.20.0``. Stored review metrics (#1381) move it to ``1.21.0``.
``docs/evidence-packet.md`` states the current version, carries a history row
for it, and documents the real ``blast_radius`` shape.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mergecraft.classify.blast_radius import classify_blast_radius
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, AgentMetadata, MergeEvidencePacket

_DOC = Path(__file__).resolve().parents[2] / "docs" / "evidence-packet.md"
_CURRENT = re.compile(r"The current version is `(?P<version>\d+\.\d+\.\d+)`\.")
_HISTORY_ROW = re.compile(r"^- `(?P<version>\d+\.\d+\.\d+)`")


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _history_entry(version: str) -> str:
    """The text of the ``- `<version>` — …`` history bullet, continuation lines included."""
    lines = _doc().splitlines()
    for index, line in enumerate(lines):
        match = _HISTORY_ROW.match(line)
        if match and match["version"] == version:
            entry = [line]
            for following in lines[index + 1 :]:
                if (
                    not following.strip()
                    or _HISTORY_ROW.match(following)
                    or following.startswith("#")
                ):
                    break
                entry.append(following)
            return "\n".join(entry)
    raise AssertionError(f"docs/evidence-packet.md has no `{version}` history row")


def _blast_radius_section() -> str:
    lines = _doc().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("### `blast_radius`"):
            body = [line]
            for following in lines[index + 1 :]:
                if following.startswith(("### ", "## ")):
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError("docs/evidence-packet.md has no `blast_radius` section")


def test_the_packet_schema_version_is_1_21_0() -> None:
    assert PACKET_SCHEMA_VERSION == "1.21.0"


def test_a_new_packet_defaults_to_the_current_version() -> None:
    field = MergeEvidencePacket.model_fields["schema_version"]

    assert field.default == "1.21.0"


def test_the_docs_state_the_current_version() -> None:
    match = _CURRENT.search(_doc())

    assert match is not None
    assert match["version"] == PACKET_SCHEMA_VERSION
    assert "The current version is `1.21.0`." in _doc()


def test_the_docs_history_row_names_the_new_blast_radius_fields() -> None:
    entry = _history_entry("1.18.0")

    assert "reasons" in entry
    assert "checklist" in entry


def test_the_docs_history_row_names_the_lite_triage_fields() -> None:
    entry = _history_entry("1.19.0")

    assert "lite" in entry
    assert "tokens_used" in entry


def test_the_docs_history_row_names_the_reapproval_section() -> None:
    entry = _history_entry("1.20.0")

    assert "reapproval" in entry


def test_the_docs_blast_radius_section_documents_the_real_shape() -> None:
    section = _blast_radius_section()

    assert "BlastRadiusClassification" in section
    for field in ("lane", "auto_merge_lane", "reason", "next_action", "categories"):
        assert f"`{field}`" in section
    assert "`reasons`" in section
    assert "`checklist`" in section
    assert "nullable until Batch B" not in section


def test_a_packet_round_trips_blast_radius_reasons_and_checklist() -> None:
    classification = classify_blast_radius({"changed_paths": ["docs/guide.md"]})
    packet = MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="acme/demo#1056",
        agent=AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        files_changed=["docs/guide.md"],
        findings=[],
        deterministic_checks=[],
        blast_radius=classification,
    )
    wire: Any = packet.model_dump(mode="json")["blast_radius"]
    restored = MergeEvidencePacket.model_validate_json(packet.model_dump_json())

    assert "signal.missing.diff" in [row["code"] for row in wire["reasons"]]
    assert all(set(row) == {"code", "lane", "message"} for row in wire["reasons"])
    assert {"gate": "inputs", "passed": False} in wire["checklist"]
    assert {"gate": "tests", "passed": None} in wire["checklist"]
    assert restored.blast_radius == classification
