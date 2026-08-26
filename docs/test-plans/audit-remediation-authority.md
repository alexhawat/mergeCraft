# Audit remediation lane C — authority & gates — test plan (AG1)

Wave plan: `.ignorelocal/waves/10-audit-remediation-c-authority-gates-wave-plan.md`
Worktree: `../mc-ag-authority-gates` on `wave/audit-remediation-c-authority-gates`
Authoring wave: **AG1** (`test-creator`). Implementation: **AG2–AG9**.
xfail-reconciliation: per impl wave (`strict=False` until green).

## AG0 decisions (operator)

| Gate | Decision |
| --- | --- |
| G3 | **(a)** `required` consults `policy/evidence.py`; clears only with declared evidence |
| G4 | **(a)** only explicit `passed` satisfies required static checks; `not_applicable` separate |

## Contract → tests

| Contract | Finding | Greening wave | Test file |
| --- | --- | --- | --- |
| PR/commit binding before SCM | MCB-05 | AG2 | `tests/mcp/test_review_scope_binding.py` |
| Settings snapshot at publish | MCB-19 | AG2 | `tests/mcp/test_review_settings_snapshot.py` |
| `resolve_confined_path` | MCB-20 | AG2 | `tests/agents/test_verifier_path_confinement.py` |
| Fail-closed auto-merge matrix | MCB-15 | AG3 | `tests/agents/test_gate_fail_closed_matrix.py` |
| Decision before `decide_action` | MCB-15 | AG3 | `tests/evidence/test_run_packet_order.py` |
| Trusted packet decisions | LR-1 | AG3 | `tests/agents/test_packet_decision_trust.py` |
| Gate mode from repo settings | MCB-17 | AG4 | `tests/evidence/test_gate_mode_resolution.py` |
| Required static check matrix | MCB-16 | AG4 | `tests/agents/test_required_static_checks.py` |
| Enforcement mode truth table | MCB-12 | AG5 | `tests/policy/test_enforcement_matrix.py` |
| Shipped `required` packs gate | MCB-12 | AG5 | `tests/policy/test_shipped_packs.py` |
| Predicate blocklist removed | MCB-29 | AG6 | `tests/orchestrator/test_predicate_validation.py` |
| Severity taxonomy complete | MCB-34 | AG6 | `tests/orchestrator/test_severity_order.py` |
| Executor honesty | MCB-37 | AG6 | `tests/orchestrator/test_executor_honesty.py` |
| Engine timeout callback reset | MCB-36 | AG7 | `tests/review/test_engine_reuse.py` |
| `--no-sync` on subprocess `uv run` | MCB-23 | AG8 | `tests/ci/test_no_env_mutation.py`, `tests/ci/test_tracing_extra_collect.py`, `tests/ci/test_ruff_advisory_families.py` |
| Venv inode session guard | MCB-23 | AG8 | `tests/conftest.py` (`_venv_inode_guard`) |
| `UV_PROJECT_ENVIRONMENT` export | MCB-23 | AG8 | `tests/ci/test_no_env_mutation.py` |
| Gateway settings snapshot | #496 | AG9 | `tests/agents/test_gateway_settings_reuse.py` |

## Deliverable symbols

| Symbol | Test anchor |
| --- | --- |
| `resolve_confined_path` | `tests/agents/test_verifier_path_confinement.py` |
| `has_failed_required_static_check` | `tests/agents/test_required_static_checks.py` |
| `evaluate_enforcement` | `tests/policy/test_enforcement_matrix.py` |
| `_resolve_gate_mode` | `tests/evidence/test_gate_mode_resolution.py` |
| `_is_low_risk_passing` | `tests/agents/test_gate_fail_closed_matrix.py` |
| `resolve_gateway_endpoint` | `tests/agents/test_gateway_settings_reuse.py` |
| `has_gateway_credentials` | `tests/agents/test_gateway_settings_reuse.py` |
| `validate_predicate` | `tests/orchestrator/test_predicate_validation.py` |
| `ReviewEngine.run` | `tests/review/test_engine_reuse.py` |

## AG6 reconciliation (post-impl test fixes)

| Fix | Rationale |
| --- | --- |
| Pre-AG1.5 orchestrator tests expect `dispatched` for agent/fan_out steps | AG6 executor honesty: non-executing dispatch steps record `dispatched`, not `ran`; decision/terminal steps remain `ran` |

Affected files: `tests/orchestrator/test_pipeline_file.py`, `test_kinds.py`, `test_decision_nodes.py`, `test_pipeline_trust.py`.

## AG3 reconciliation (post-impl test fixes)

| Fix | Rationale |
| --- | --- |
| `evidence_unavailable` deterministic check | `DeterministicCheck` requires `command`; omitting it blocked packet construction before assertions. |
| `trusted_success_no_blockers` → split cases | `_is_low_risk_passing` needs empty findings; Minor findings yield `neutral` (same as matrix `neutral_verdict`), not `auto_merge`. |
| `low_risk_passing` helpers attach decision | AG3 packet-once: `decide_action` predicates consult attached `decision`; empty findings need explicit trusted `success`. |
| `test_gate_rule_selection` self-assessment | Attach `decide_approval` row before `decide_action` per packet-once contract. |
| `TRUSTED_PACKET_DECIDED_BY` anchor | `test_decide_approval_tags_trusted_packet_decided_by` pins the trusted decider constant (D9 / LR-1). |

## Verification

```bash
make lint && make typecheck
uv run pytest --collect-only -q \
  tests/mcp/test_review_scope_binding.py \
  tests/mcp/test_review_settings_snapshot.py \
  tests/agents/test_verifier_path_confinement.py \
  tests/agents/test_gate_fail_closed_matrix.py \
  tests/evidence/test_run_packet_order.py \
  tests/agents/test_packet_decision_trust.py \
  tests/evidence/test_gate_mode_resolution.py \
  tests/agents/test_required_static_checks.py \
  tests/policy/test_enforcement_matrix.py \
  tests/policy/test_shipped_packs.py \
  tests/orchestrator/test_predicate_validation.py \
  tests/orchestrator/test_severity_order.py \
  tests/orchestrator/test_executor_honesty.py \
  tests/review/test_engine_reuse.py \
  tests/agents/test_gateway_settings_reuse.py \
  tests/ci/test_no_env_mutation.py
```
