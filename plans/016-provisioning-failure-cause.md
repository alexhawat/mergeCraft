# Plan 016: Preserve managed analyzer provisioning failure causes

- Status: Integrated; independent focused verification passed; final combined-tree CI pending
- Issue: [#825](https://github.com/alexhawat/mergeCraft/issues/825)
- Planned against main `41cf53b3`, 2026-09-22.
- Priority: P2; dependencies: none.

## Verified defect

`analyzers/execution.py::provision_managed_argv` catches `ProvisionError` and returns `None` after its existing retry loop. `analyzers/adapters.py::run_adapter` consequently returns the constant `managed binary provisioning failed`. A caller cannot distinguish a transient GitHub release 502/503/504 from a checksum mismatch, unsafe redirect, or permanent 404. Main's PR #818 correctly removed the broad skip that hid all these failures.

## Scope and contract

Read AGENTS.md, CONTRIBUTING.md, coding standards and REVIEW-DOCTRINE. Preserve the existing trust, sandbox, hash and redirect checks. Work in an isolated branch; use Make for checks, Conventional Commits, and no hook bypass.

Scope: `src/mergecraft/analyzers/{execution,adapters,provision,contracts,supply_chain}.py` only where needed to propagate the cause; analyzer tests for these paths; `tests/analyzers/support.py` and existing live planted-finding tests only for narrowly classified outage handling. Keep the result backward compatible where practical. Root maintains this plan and the index.

1. Add a failing adapter-level regression that drives the real provisioner failure boundary and asserts the specific cause survives in `AdapterRunResult.skip_reason` or an explicit typed field. Cover recognized 502/503/504, 404, checksum mismatch, unsafe redirect, and generic/empty errors. Use mocked transport/provisioning; no live credentials.
2. Preserve the final error through the existing retry behavior. Prefer a typed failure or raised `ProvisionError` caught at the existing caller boundary rather than mutable global state. Update every production caller of the changed helper; adapter and lower-level execution paths must still return their established failure result rather than unexpectedly aborting the review. Retain compatibility for deliberate skip/no-plan cases. Include semgrep provisioning errors in the same visible contract.
3. Redact and bound any retained error text using the existing redactor. A fabricated credential-shaped canary must not survive the returned result. Do not expose raw URLs or secret-bearing exception text without sanitization.
4. Allow only identified GitHub-release 502/503/504 failures in live-network test exceptions. Keep all permanent/unknown failures strict, including failures whose unrelated message happens to contain a number. Never restore a blanket `provisioning failed` skip. Do not weaken product failure classification or security gates.
5. Run focused analyzer tests through Make, lint and typing for touched paths; integrated full CI remains a final integration responsibility. Assert permanent causes fail the helper's skip predicate, transient causes alone qualify, and existing sandbox-skip visibility is unchanged.

## Completion evidence

Record the initial failing regression, final focused results, scope, and commit. Root will independently inspect the full diff and re-run the completion checks. Issue closure requires visible classified cause and strict permanent-failure tests; live outages are not a passing detection result.

Stop and report if carrying a cause requires relaxing sandbox, checksum, redirect or trust enforcement. Routine caller compatibility adjustments inside the listed scope are authorized.
