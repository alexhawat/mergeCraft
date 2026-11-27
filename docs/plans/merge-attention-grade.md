# Merge-attention grade (issues #1609–#1612)

## Goal

Surface a compact **low / medium / high** merge-attention grade on each review: one overall level plus a one-line verdict per axis (alignment, impact, verification, rollback cost, error detection). The grade is a human-attention heuristic only; it must never change approval, merge checks, exit codes, or gating.

## Design

1. **Compose after gating** — `compose_merge_attention` runs only after `decide_approval` / `_finalize_packet_with_gate`. The grade is attached with `model_copy` and is not an input to `decide_approval`, `select_rule_id`, or status checks.
2. **Deterministic first** — Each axis is scored from run evidence: blast-radius lane, policy evidence (`rollback_plan`, `health_check`), analyzer/CI/static-check signals, blocking findings, scope/fix proof codes, verifier fingerprints, and end-to-end proof detection (#1611).
3. **Model-labelled gaps** — When alignment cannot be resolved from evidence, the axis verdict cites the agent terminal verdict / self-assessment and marks `source: model`.
4. **No numeric confidence** — Per REVIEW-DOCTRINE C12/C22, axis verdicts are categorical only; any internal weighting stays in code and is not published on findings or inline comments.
5. **Display** — `review.mergeAttention.enabled` (default on) controls packet population and rendering. When off, behaviour matches pre-feature runs.

## Deliverables

| Issue | Work |
| --- | --- |
| #1609 | Grade in run record, step summary, published review summary; docs + non-gating tests |
| #1610 | `mergecraft.merge_attention.compose` + unit fixtures |
| #1611 | Configurable user-facing globs; verification gaps for missing UI/perf proof |
| #1612 | `skills/merge-attention/SKILL.md` + `docs/merge-attention.md` |

## Packet

Additive `merge_attention` section on `MergeEvidencePacket`; bump `PACKET_SCHEMA_VERSION` to `1.23.0`.

## Test plan

- `pytest tests/merge_attention/`
- `pytest tests/agents/test_merge_attention_gating.py`
- `pytest tests/evidence/test_packet_schema_version.py`
- `make ci`