# Execute and verify the issue-remediation plan

This is the delivery contract for the fifteen numbered plans. A plan being ready means its investigation and implementation instructions are ready; no fix or dataset is implied to exist. All product work remains TODO at this planning PR.

## Start from the actual integration baseline

1. Read `AGENTS.md`, `CONTRIBUTING.md`, and the numbered plan in full. Read `docs/REVIEW-DOCTRINE.md` before changing review behavior.
2. Fetch current main and inspect PR #817. The audit baseline is `be9993367386b03f982c795ceb1d80e4a0bfcf1d`; the audited #817 head is `d72b4e77dd47d7937527837b3f653a858804cf4e`. Refresh any changed source assumptions before implementation. Do not merge #817 automatically or use its combined percentages as true line coverage.
3. Create a `codex/` implementation branch and isolated worktree. Preserve unrelated local changes. Include these committed plans in the executor context; each executor must be able to read its full plan.
4. Use separate worktrees for parallel source changes. Each executor owns only its assigned paths, writes focused regressions, runs the plan's relevant Make targets, and reports actual commands/results. Never share a mutable development environment while dependency installation is running.
5. Inspect actual diffs and test assertions before integrating an executor's changes. Report skipped or unavailable checks explicitly. Never infer success from an agent's completion message alone.

## Allocate three implementation lanes

These lanes limit file conflicts while allowing independent progress. Effort labels in individual plans are sizing estimates, not elapsed-time promises.

| Lane | Ordered work | Integration boundaries |
|---|---|---|
| Runtime and evidence | 001 redaction → 005 read attribution; 002 normalized verdict → 004 publication recovery | 001/005 share trajectory files; 002/004 share verdict/publication state. Keep each pair under one owner and verify the combined behavior. |
| Permissions, tracing, and delivery tooling | 003 App token permissions → 009 lifecycle tracing; then 006 coverage metrics → 008 coverage sharding | 003/009 both touch orchestration. Measure and freeze final coverage only after all production changes are integrated. |
| Evaluation and setup | 007 adjudication round-trip → 011 evidence-packet preparation; 012 scorer; 013 calibration-report preparation; 010 setup instructions | 007/012/013 share eval CLI/schema files. Develop 012 before production trace fixes if useful, but freeze its production baseline only after 001/005. |

The initial priority remains 001, 002, 003, 006 and 007. If the permissions lane is long, move 006/008 to a free executor rather than leaving a verification defect until the end. Serialize edits to `Makefile`, shared CLI modules and generated documentation at integration. Implement 014 campaign preparation after its evaluation contracts are settled; 015 starts from the final selected fixes and their actual CI results.

Do not make human availability a prerequisite for unrelated coding: scorer implementation, honest eligibility reporting, protocol validation and evidence preparation can proceed while labels are pending. Conversely, do not label a dataset, threshold or benchmark validated merely because the supporting code exists.

## Verify in increasing scope

| Stage | Required evidence |
|---|---|
| Each behavioral fix | A regression exercising the real production boundary, failing for the original bug and passing after the fix; selected neighboring tests. No import/fixture failure counts as reproduction. |
| Each implementation lane | Relevant Make checks, strict typing for Python changes, generated-artifact checks when applicable, and a clean scoped diff. Review the complete test assertions. |
| Combined source | `make ci` on the final integration tree, or successful authoritative GitHub CI for that exact head. Preserve failures and resolve them; avoid repeatedly running an unchanged full suite after it has passed. |
| Coverage metric change | One full, attributable measurement on the combined tree using actual statement and branch fractions. Preserve global combined coverage `fail_under=82`; explain every floor change from measured data. |
| Coverage sharding | Complete compatible raw-data manifests; bounded fixture parity and whole-suite parity; missing/duplicate/incompatible groups rejected before gating. |
| Evaluation | Structural keyless replay remains distinct from independently labelled quality measurement and live provider detection. Installed-wheel corpus loading is verified for adjudication changes. |
| Release | Candidate-specific verification, source/image/signature/pin identity, required soak, and separate publication approval. A merged code PR is not deployed evidence. |

Run commands from the numbered plan rather than inventing one-off project workflows. New commands explicitly marked as deliverables cannot be treated as pre-existing successful checks. No blanket `make ci` claim is permitted when only focused tests ran.

## Work that cannot be completed by an agent declaration

| Plan / issue | Missing input or event | Deliverable possible before it |
|---|---|---|
| 011 / #780 | Inspectable source/patch evidence and Alex's actual adjudication; incomplete historical cases may need explicit replacement decisions | Evidence inventory and review packet, with missing evidence marked and no invented provenance |
| 012 / #735 | Independently labelled real trajectories covering the eight checks; approved baseline/tolerance | Deterministic scorer, strict corpus/report schema, agent-seeded development fixtures |
| 013 / #736 | Frozen human reference decisions, disjoint held-out sample and predeclared acceptance contract | Eligibility wording correction, saved-decision scoring, split/pin validation, provisional report |
| 014 / #140 | Separately adjudicated patch-bearing detection labels, the 013 receipt, two selected provider/model identities, approved budget/limits, credentials and actual results | Concrete campaign manifest and report template; no scores or README quality claims |
| 015 / #783 | Final merged candidate, green required jobs, image/pin evidence, soak and explicit publish approval | Candidate inventory and verification checklist; no accepted label, retagging or package publication |

## Close issues only against completed acceptance criteria

- #790 and #796 already have implemented fixes and passing targeted regressions on main via #806. They need evidence-based issue housekeeping, not replacement implementations.
- #771 is the sole automatic closing reference in #817. #797 additionally needs the final numeric contract verified after #817 and plan 006; it has no automatic closing reference in #817.
- #792 can close after plan 010 and generated-doc checks. Plans 001–009 each name their own regression and completion criteria; link the corresponding implementation PR only when those criteria actually pass.
- Keep #780, #735, #736, #140 and #783 open if only preparation is complete. Record the completed portion and the precise remaining input rather than overclaiming closure.
- #723 remains a tracker. Refresh its child map and completion evidence after implementation; avoid creating a duplicate umbrella project.
- This planning PR intentionally has no issue-closing keywords. It changes the handoff, not the product behaviors described in the issues.

Maintain status in `plans/README.md` after independent verification. Use TODO, IN PROGRESS, DONE, or BLOCKED with a concrete reason; for mixed code/human work record both portions. Keep the original audit receipts separate from implementation receipts.
