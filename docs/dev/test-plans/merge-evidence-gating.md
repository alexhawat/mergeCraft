# Merge evidence & gating (#47, #41) — Batch A test plan (WA-T RED)

Wave plan: `.ignorelocal/waves/issues-merge-evidence-gating-wave-plan.md`
Worktree: `mergecraft-evi-a-packet` @ `wave/evi-a-packet`

## Locked decisions exercised

| ID | Decision | Tests |
|----|----------|-------|
| **D3** | Packet composes `Finding`; JSON Schema derived from the Pydantic models (mirroring `analyzers/finding.py:138`) | `test_evidence_packet_schema_is_derived_not_handwritten`, `test_packet_findings_match_finding_model_json_schema` |
| **D3** | `extra="forbid"` on the packet (and nested models) | `test_evidence_packet_rejects_unknown_fields`, `test_evidence_packet_rejects_nested_unknown_fields` |
| **D7** | `schema_version` is required and a pinned literal — silent drift fails the test | `test_evidence_packet_requires_schema_version`, `test_packet_schema_version_is_pinned` |
| **D4** | Nullable-until-later sections (`blast_radius`, `trajectory`, `evals`) are typed `| None`, not omitted | `test_packet_contains_nullable_until_later_sections` |
| **D5** | `decide_approval()` consumed, not reimplemented; the function lives in `mergecraft.agents.gates` | `test_self_assessment_alone_blocks_auto_merge`, `test_decide_approval_does_not_treat_self_assessment_as_evidence` |
| **#41** | Self-assessment is recorded separately and never sufficient | `test_self_assessment_is_recorded_separately_from_evidence`, `test_self_assessment_field_carries_approved_and_sha`, `test_self_assessment_alone_blocks_auto_merge` |

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W1** | `tests/evidence/test_packet_schema.py::test_evidence_packet_schema_is_derived_not_handwritten` | `green after W1: packet model + derived schema` |
| **W1** | `tests/evidence/test_packet_schema.py::test_packet_findings_match_finding_model_json_schema` | `green after W1: findings composes Finding` |
| **W1** | `tests/evidence/test_packet_schema.py::test_evidence_packet_requires_schema_version` | `green after W1: schema_version field` |
| **W1** | `tests/evidence/test_packet_schema.py::test_packet_schema_version_is_pinned` | `green after W1: PACKET_SCHEMA_VERSION literal` |
| **W1** | `tests/evidence/test_packet_schema.py::test_packet_schema_round_trip_json_serializes` | `green after W1: packet serializes + re-validates` |
| **W1** | `tests/evidence/test_packet_round_trip.py::test_evidence_packet_round_trips_through_json` | `green after W1: packet round-trips through JSON` |
| **W1** | `tests/evidence/test_packet_round_trip.py::test_evidence_packet_round_trips_through_dict` | `green after W1: packet round-trips through dict` |
| **W1** | `tests/evidence/test_packet_round_trip.py::test_evidence_packet_rejects_unknown_fields` | `green after W1: extra="forbid"` |
| **W1** | `tests/evidence/test_packet_round_trip.py::test_evidence_packet_rejects_nested_unknown_fields` | `green after W1: extra="forbid" propagates` |
| **W1** | `tests/evidence/test_packet_sections.py::test_packet_contains_required_sections` | `green after W1: required top-level sections` |
| **W1** | `tests/evidence/test_packet_sections.py::test_packet_contains_nullable_until_later_sections` | `green after W1: nullable-until-later fields are typed ` |
| **W1** | `tests/evidence/test_packet_sections.py::test_packet_agent_section_carries_id_version_and_model` | `green after W1: AgentMetadata` |
| **W1** | `tests/evidence/test_packet_sections.py::test_packet_decision_section_exists` | `green after W1: decision section` |
| **W1/W2** | `tests/evidence/test_self_assessment.py::test_self_assessment_is_recorded_separately_from_evidence` | `green after W1: self_assessment field; W2: distinct from decision` |
| **W1/W2** | `tests/evidence/test_self_assessment.py::test_self_assessment_field_carries_approved_and_sha` | `green after W1: self_assessment shape` |
| **W1/W2** | `tests/evidence/test_self_assessment.py::test_self_assessment_alone_blocks_auto_merge` | `green after W2: decide_approval honours #41 hard rule` |
| **W1/W2** | `tests/evidence/test_self_assessment.py::test_decide_approval_does_not_treat_self_assessment_as_evidence` | `green after W2: decision field is authoritative` |

All cross-wave markers use `strict=False`.

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#47** | D3 — JSON Schema derived from Pydantic models | Unit | Happy — `properties.findings.items` matches `Finding.model_json_schema()` | `test_evidence_packet_schema_is_derived_not_handwritten` |
| **#47** | D3 — `findings: list[Finding]` typed | Unit | Annotation — `list[Finding]` | `test_packet_findings_match_finding_model_json_schema` |
| **#47** | D7 — `schema_version` required | Unit | Happy — field present, no default | `test_evidence_packet_requires_schema_version` |
| **#47** | D7 — version is a pinned literal | Unit | Drifts — missing or wrong value fails | `test_packet_schema_version_is_pinned` |
| **#47** | D3 — round-trip JSON | Unit | Happy — `model_dump_json()` → `model_validate_json()` is identity | `test_evidence_packet_round_trips_through_json` |
| **#47** | D3 — round-trip dict | Unit | Happy — `model_dump()` → re-validate is identity | `test_evidence_packet_round_trips_through_dict` |
| **#47** | D3 — `extra="forbid"` | Unit | Error — unknown top-level field rejected | `test_evidence_packet_rejects_unknown_fields` |
| **#47** | D3 — `extra="forbid"` propagates | Unit | Error — unknown nested field rejected | `test_evidence_packet_rejects_nested_unknown_fields` |
| **#47** | D4 — required sections present | Unit | All six required top-level sections present | `test_packet_contains_required_sections` |
| **#47** | D4 — nullable-until-later | Unit | `blast_radius`, `trajectory`, `evals` typed `| None`, not omitted | `test_packet_contains_nullable_until_later_sections` |
| **#47** | D4 — `agent` sub-model | Unit | `AgentMetadata` has `id`, `version`, `model` | `test_packet_agent_section_carries_id_version_and_model` |
| **#47** | D4 — `decision` section | Unit | `decision` field present on packet | `test_packet_decision_section_exists` |
| **#41** | D5 — `decide_approval` consumed | Unit | Happy — packet with self-assessment and no findings → not `auto_merge` | `test_self_assessment_alone_blocks_auto_merge` |
| **#41** | D5 — `decision` is authoritative | Unit | Edge — explicit `block` decision wins over an approving self-assessment | `test_decide_approval_does_not_treat_self_assessment_as_evidence` |
| **#41** | Split | Unit | Distinct fields, both populated | `test_self_assessment_is_recorded_separately_from_evidence` |
| **#41** | Split | Unit | `self_assessment` carries `approved` + `sha` | `test_self_assessment_field_carries_approved_and_sha` |

## Implementation notes for impl waves

- **W1:** Land `src/mergecraft/evidence/packet.py` with:
  - `class MergeEvidencePacket(BaseModel)` with `model_config = ConfigDict(extra="forbid")`,
  - module-level `PACKET_SCHEMA_VERSION = "1.0.0"`,
  - `findings: list[Finding]` (D3 — composes, does not replace `Finding`),
  - nullable-until-later fields `blast_radius: BlastRadius | None = None`, `trajectory: Trajectory | None = None`, `evals: Evals | None = None`,
  - `class AgentMetadata(BaseModel)` with `id`, `version`, `model`,
  - `def packet_output_schema() -> dict[str, Any]:` mirroring `analyzers/finding.py:138` (derives from `MergeEvidencePacket.model_json_schema()`),
  - un-xfail `test_packet_schema.py` and `test_packet_round_trip.py` and `test_packet_sections.py` (W1.6).
- **W2:** Add `decide_approval(packet, *, run_succeeded, tier)` in `src/mergecraft/agents/gates.py` (or consume the function the security plan's Batch D lands — D5) and the `self_assessment: SelfAssessment | None` field on the packet. Un-xfail `test_self_assessment.py` (W2.6).
- **Style mirrors the analyzer test suite:** lazy `import_module` (so collection succeeds before `src/mergecraft/evidence/` exists), `from __future__ import annotations` everywhere, `dict[str, object]`-typed fixtures, no in-line `decide_approval` mock — the outcome is pinned and the impl may freely adjust the signature.

## Deferred to W1 / W2 (not in WA-T scope)

- `blast_radius`, `trajectory`, `evals` payload shapes (Batches B / C / E)
- `mergecraft eval add/list/replay` (Batch E)
- LLM judge logging contract (Batch E, W13)
- Shadow-mode disagreement report (Batch D, W10)
- `blast_radius` classifier unit tests (Batch B, WB-T)
- Trajectory auditor unit tests (Batch C, WC-T)
- `decide_approval` signature lockdown — the WA-T.5 / WA-T.6 tests assert the **outcome** (not `auto_merge` for self-assessment-only); W2 may adjust the parameter list as long as the outcome holds.
