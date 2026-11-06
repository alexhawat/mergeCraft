# November audit remediation

Original audit: [2026-11-05 report](audit-2026-11-05.md), at source commit `55cf88e33c318a8b03a251fb0f8b6dad9d999141`. Implementation started November 5 and continued November 6, 2026.

The complete actionable scope is organized into **five PRs**, all targeting **`codex/audit-remediation`**. The integration branch starts from main at `42285b46`, plus CI trigger setup. All five PRs have now merged into the integration branch. The next PR targets main; the audit fixes are not yet merged into main.

| Group | PR | Findings |
|---|---|---|
| Security and revision identity | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | R1, R2, R7–R9, N3, N8 |
| CLI and workspaces | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | N4–N7, R6, R10–R15, DOC3 |
| Findings and triage | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | R3–R5, N1, N2 |
| Testing and CI | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | T1–T4, N9, DOC4 |
| Documentation and audit record | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | DOC1, DOC2, DOC5 |

R7–R15 name the originally unnumbered residual findings. R3 covers both merging stages in its original finding. DOC1–DOC5 track the report's documentation and CI-assurance recommendations. Individual finding commits remain available within the grouped PRs. Superseded per-finding PRs #1171–#1195 and the temporary combined PR #1196 are closed.

| ID | Scope | Group | Status | PR | Verification |
|---|---|---|---|---|---|
| N1 | Whitespace semantics and executable metadata | findings | VERIFIED LOCALLY | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 1,058 classification/fast-path tests; Ruff/mypy |
| N2 | Deleted front matter | findings | VERIFIED LOCALLY | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 1,085 combined triage tests; Ruff/mypy |
| N3 | Space-containing no-hunk paths | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 127 focused tests; Ruff/mypy |
| N4 | Ignored files in clean trees | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 33 focused tests; Ruff/mypy |
| N5 | Unstaged omission metadata | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 21 focused tests; Ruff/mypy |
| N6 | Verification target workspace | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 31 focused tests; Ruff/mypy |
| N7 | Consumer coverage toolchain | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 35 passed, 1 optional-tool skip; Ruff/mypy |
| N8 | GHES GraphQL URL | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 95 GitHub/SCM tests; Ruff/mypy |
| N9 | Per-architecture lint tool digests | ci | VERIFIED LOCALLY | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 10 passed, 1 platform skip; Ruff/bash |
| R1 | Approval revision binding | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 42 focused tests; Ruff/mypy |
| R2 | Pinned operator budgets | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 8 focused tests; Ruff/mypy |
| R3 | Monotone clustering and scope union | findings | VERIFIED LOCALLY | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 761 focused tests; Ruff/mypy |
| R4 | Impact-aware severity | findings | VERIFIED LOCALLY | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 282 focused tests; Ruff/mypy |
| R5 | Finding occurrence identity | findings | VERIFIED LOCALLY | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 435 focused tests; Ruff/mypy |
| R6 | Contributing config validation | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 33 focused tests; Ruff/mypy |
| R7 | Checkout revision race and retry scope | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | Real-Git push/fetch and failed-checkout/retry regressions; 119 focused tests plus expanded proof/integrity cases; Ruff/mypy |
| R8 | Git show cache identity | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 301 focused Git tests; Ruff/mypy |
| R9 | Same-repository fork trust | security | VERIFIED LOCALLY | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 236 core +132 broader tests; 1 optional-tool skip; Ruff/mypy |
| R10 | Review cache source context | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 44 focused cache tests; Ruff/mypy |
| R11 | Explicit revision source checkout | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | Local revision mismatch/dirty-tree Git regressions; Ruff/mypy |
| R12 | Resolved repository persistence | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 24 provenance/persistence tests; preflight regression |
| R13 | Target workspace env loading | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 44 startup/environment tests; Ruff/mypy |
| R14 | Anonymous fallback without gh | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 4 focused auth/clone tests; Ruff/mypy |
| R15 | Output usage exit status | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 17 output tests; Ruff/mypy |
| T1 | Mutation error classification/baseline | ci | VERIFIED LOCALLY | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 20 tests; Ruff/mypy |
| T2 | Semantic Action E2E receipts/protocol | ci | VERIFIED IN HOSTED IMAGE | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 29 protocol/assertion tests; real host GHA approval/refusal; Ruff/mypy/bash |
| T3 | Clean installed-wheel CLI acceptance | ci | VERIFIED LOCALLY | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | Clean wheel acceptance; 6 packaging tests; Ruff/mypy |
| T4 | Locked CI bootstrap | ci | VERIFIED LOCALLY | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | real stale-lock bootstrap regression; Ruff |
| DOC1 | Released pinned onboarding | docs | VERIFIED LOCALLY | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | 26 docs tests; generated packages; Ruff |
| DOC2 | Supported/tested/published matrix | docs | VERIFIED LOCALLY | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | 9 docs tests; generator drift; Ruff |
| DOC3 | CLI workspace behavior documentation | cli | VERIFIED LOCALLY | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | Documented workspace and output contracts |
| DOC4 | Enforce reliable deterministic checks | ci | VERIFIED LOCALLY AND FAILURE PROPAGATION IN CI | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 78 guard/workflow tests; permissions; Ruff |
| DOC5 | Dated audit/history and complete remediation index | docs | VERIFIED LOCALLY | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | Dated report, probes, open-work snapshot and full finding index |

## Verification and execution contract

Each fix includes a focused regression suite, lint/format checks and appropriate typing checks. The regression cases exercise observable behavior, including real Git histories and consumer environments. Counts above overlap and must not be added as unique tests. Combined static/build, unit, coverage and deterministic integration results are recorded below. Platform-specific and installed-image evidence remains separate from local Python evidence.

The original audit probes reproduce defects against the audit source commit; they are historical evidence, not the repaired behavior's acceptance suite. Source-level regression tests accompany the fixes. No paid model calls or private provider credentials are required.

## Reconciliation and boundaries

- Previously open work remains excluded. Main now includes declared-scope PR #1160, incident/eval/outcome PR #1167, Agents SDK PR #1161 and private-export cleanup PR #1079. Their merged behavior is included in the integration baseline.
- PR #1170 covers fail-then-pass receipts separately. The [original open-work snapshot](audit-2026-11-05-open-work.json) preserves the audit's exclusions.
- Local roster workflow-wiring enforcement was already fixed and is not presented as a new defect.
- Independent human-label/calibration campaigns require real external evidence. The report's comparative assessment does not become an accuracy claim merely because these fixes pass.
- This work creates reviewable changes. It does not alter external branch-protection settings, merge changes, release packages or publish images.

## Combined verification

At the initial combined validation, the five branches merged without conflicts and exactly matched the tested tree. The input revisions below identify that run; later follow-up repairs and their separate validation are recorded in the next section. The shared target is `3de00fc1`: main at `42285b46` plus integration-branch CI triggers and their test assertions. No product remediation has been merged into that target or main.

Tested group inputs: security `68de6470`, CLI `610aa32b`, findings `b27933d6`, testing/CI `ab64e450`, and documentation `a5a653b6`. The final documentation commit adds this verification record only.

- Full `make ci` on Python 3.14.6: **passed**. All four complete coverage shards passed: **15,199 passed, 67 skipped, 1 expected failure**. Statement coverage is **87.79%**, branch coverage **77.55%**, and combined coverage **85.19%**. The coverage ratchet, global floor and every critical-path floor passed. Static/build/generated-reference/type checks and dependency/security audits also passed.
- Deterministic integration: **23 passed, 13 skipped**. The execution-count guard passed. Skips cover optional Agents SDK/Harbor packages, the absent `meat` executable, and disposable Linux isolation.
- Python 3.11: **34 passed** in the final checkout/retry/evidence/Action-protocol suite. The broader CLI/triage/protocol selection first produced 187 passes and one consumer-venv fixture failure; after correcting POSIX interpreter symlinks, both consumer-environment cases passed. That full selection was not rerun as a single batch.
- Final installed wheel: clean runtime-only installation, isolated Python/cwd/home, corpus replay, console help, configuration, version and JSON capabilities all passed. The tested wheel identifies source `38522f2`.
- Structural eval gate and adversarial corpus checks passed. These are deterministic replay checks, not a live detection-accuracy benchmark.

The first complete coverage attempt exposed two old workflow branch-list expectations and a remote-source fixture that returned an empty directory. The assertions now include the integration target, and the fixture clones a real local repository and verifies URL/SHA provenance. The affected suites passed **15** and **18** tests respectively before the complete rerun. These corrections removed no tests and lowered no coverage thresholds.

The local Docker daemon was unavailable. The subsequent [hosted Action-image job](https://github.com/alexhawat/mergeCraft/actions/runs/42173188346/job/127745549026) at testing/CI head `59623c04` passed both PR fixtures (approval and external-fork refusal) and the in-image adversarial suite. This is image evidence for PR #1200, separate from the combined local source validation above. Native ARM execution and paid-provider/human-label campaigns were not performed. Current hosted results are attached to each PR; a passing local or image check does not imply that every other hosted job is green.

## Hosted-check follow-up

The follow-up found no merge conflicts or submitted review findings on the five PRs. Hosted failures exposed three environment-dependent test defects, now repaired on their existing branches:

- Security `5713180f`: the SCM snapshot client explicitly selects its mock API base, preventing ambient `GITHUB_GRAPHQL_URL` from changing its recorded endpoint form. Tests exercise absent and conflicting environment settings; 32 focused Python 3.14 tests and 66 Python 3.11 SCM/endpoint tests passed.
- CLI `202be2b3`: the layered-config regression verifies the full diagnostic path across Rich line wrapping at widths 40 and 80. An isolated console prevents the narrow-width test from leaking its setting into later tracing tests. The combined, ordered config/tracing selection reproduced five failures before that isolation repair and passed all 21 tests afterward on Python 3.11 and 3.14. Runtime validation policy is unchanged.
- Testing/CI `59623c04`: fixture preparation runs inside the Action image as the controller user, preserving production Git ownership checks while making the local origin usable. Diagnostic report steps also require successful bootstrap, avoiding missing-tool errors after the required prerequisite guard rejects a failed dependency. The guard correctly rejected the earlier failed image job. Locally, 69 protocol/workflow tests passed with one Linux-only skip; actionlint, zizmor and shell syntax checks passed. The real container job linked above subsequently passed.

The findings and documentation PRs had no failed functional checks; their cancelled changelog previews were rerun successfully. All five branches still merge cleanly in the local integration check. The shared target and main remain unmerged; these follow-up commits do not change the five-PR integration structure.

## Integration with current main

The five reviewed heads (security `cca1d7f8`, CLI `9f0ac525`, findings `84c9825e`, CI `156a2249`, documentation `4454cf4e`) merged into the integration branch at `7fc926b3`. Its tree exactly matched the local combined tree that passed 460 focused regressions after the review fixes. All ten inline review threads were resolved.

The subsequent integration with main at `46b583b7` retains the repository reorganization from #1202 and the shared artifact-provenance implementation from #1170. Audit documents move to `docs/dev/plans/`; earlier paths and unmerged statements above describe their dated validation snapshots. Both architectures retain checksum verification for downloaded lint tools. Checkout invalidation now clears revision-bound fail-then-pass evidence while retaining the base-owned declaration and run-start PR metadata.

Post-synchronization validation on Python 3.14.6 passed **311** documentation, release, artifact-provenance, checkout and lint-download tests, including the real CLI examples and skills-ref validation. A separate receipt/run-start/fix-label/checkout selection passed **231** tests; selections overlap and are not additive. Ruff, targeted mypy, shell syntax, actionlint, zizmor and generated skill/llms drift checks passed. Full CI for the main-targeted integration PR remains a separate validation step.
