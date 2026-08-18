# PR DG5 — policy-as-code with scoping, enforcement modes and tooling — test plan (DG5.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG5)
Worktree: `../mergecraft-dg5-policy-as-code` @ `wave/dg5-policy-as-code`
Authoring wave: **DG5.1** (tests-first). Implementation: **DG5.2**.
xfail-reconciliation: **post-DG5.2** (complete).

Locked decisions: **D7** (policy `advisory` / `warning` / `required` / `blocking` map onto the
existing gate — blocking rules contribute blocking findings; policy authority stays in
`decide_approval()`), **D8** (a rule with unavailable required evidence yields `inconclusive`,
never a silent pass).

## xfail schedule

| Test file | Tests | Marker | Status at DG5.1 |
|-----------|-------|--------|-----------------|
| `tests/policy/test_schema.py` | 2 | `strict=False`, reason `green after DG5.2` | **RED (xfail)** |
| `tests/policy/test_scoping.py` | 2 | `strict=False`, reason `green after DG5.2` | **RED (xfail)** |
| `tests/policy/test_enforcement.py` | 2 | `strict=False`, reason `green after DG5.2` | **RED (xfail)** |
| `tests/policy/test_evidence_requirements.py` | 1 | `strict=False`, reason `green after DG5.2` | **RED (xfail)** |
| `tests/policy/test_exceptions.py` | 2 | `strict=False`, reason `green after DG5.2` | **RED (xfail)** |
| `tests/cli/test_policy_verbs.py` | 3 | `strict=False`, reason `green after DG5.2` | **RED (xfail)** |

**Acceptance (DG5.1):** 12 collected; 0 pass; 12 xfail. `make lint` + `make typecheck` clean.

**Acceptance (post-DG5.2 reconciliation):** 12 collected; 12 pass; 0 xfail/xpass.

## Target API DG5.2 must satisfy

### `src/mergecraft/policy/schema.py` (new)

| Symbol | Contract |
|--------|----------|
| `PolicyRule` | Pydantic model: `id`, `owner`, `version`, `rationale`, `severity`; `extra="forbid"` |
| `parse_rule(text)` | Parse one YAML rule document |
| `PolicyConfigError` | Config errors for missing required fields and unknown keys |

### `src/mergecraft/policy/scoping.py` (new)

| Symbol | Contract |
|--------|----------|
| `ScopeContext` | `org`, `repo`, `branch`, `path`, `language` |
| `resolve_effective_rules(rules, *, context)` | Deterministic scope filtering; entries expose `rule`, `source_layer` |

Inheritance order: org → repo → path (deeper scopes override shallower ones for the same id).

### `src/mergecraft/policy/enforcement.py` (new)

| Symbol | Contract |
|--------|----------|
| `EnforcementMode` | `advisory` \| `warning` \| `required` \| `blocking` |
| `evaluate_enforcement(mode, *, violation)` | Returns outcome with `contributes_blocker`, optional `finding` |
| blocking mode | `finding.severity in BLOCKING_SEVERITIES`; feeds `decide_approval()` (D7) |

No parallel approval path on the enforcement module.

### `src/mergecraft/policy/evidence.py` (new)

| Symbol | Contract |
|--------|----------|
| `evaluate_rule_evidence(rule, *, available_evidence)` | Missing required evidence → `status="inconclusive"`, `run_outcome=RunOutcome.inconclusive` (D8) |

### `src/mergecraft/policy/exceptions.py` (new)

| Symbol | Contract |
|--------|----------|
| `parse_exception(text)` | Strict parse; `PolicyConfigError` on missing fields |
| `exception_applies(exc, *, context, now)` | False after expiry |

Required fields: `reason`, `approver`, `scope`, `expires_at`.

### `src/mergecraft/cli/policy_cmd.py` (new)

| Command | Contract |
|---------|----------|
| `policy lint` | Reject malformed rule YAML (non-zero exit) |
| `policy test --fixtures <dir>` | Run should-trigger / should-not fixtures |
| `policy explain` | Name effective rules and their source layer |

Registered on `mergecraft.cli.app` as `policy`.

## Contract → coverage matrix

| Contract | Unit | Integration | Functional |
|----------|------|-------------|------------|
| Required rule fields + strict schema | `test_schema.py` | — | — |
| Scope resolution + inheritance | `test_scoping.py` | `test_scoping.py` (layered rules) | — |
| Enforcement modes (D7) | `test_enforcement.py` | `test_enforcement.py` + `decide_approval` | — |
| Evidence inconclusive (D8) | `test_evidence_requirements.py` | — | — |
| Bounded exceptions | `test_exceptions.py` | `test_exceptions.py` (expiry) | — |
| lint / test / explain verbs | — | — | `test_policy_verbs.py` |
