# November audit remediation

Original audit: [2026-11-05 report](audit-2026-11-05.md), at source commit `55cf88e33c318a8b03a251fb0f8b6dad9d999141`. Implementation started November 5 and continued November 6, 2026.

The complete actionable scope is organized into **five PRs**, all targeting **`codex/audit-remediation`**. The integration branch starts from main at `42285b46`, plus CI trigger setup. A PR from the integration branch to main is deliberately deferred; no audit fix has been merged to main.

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
| N1 | Whitespace semantics and executable metadata | findings | IMPLEMENTED / VALIDATING | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 1,058 classification/fast-path tests; Ruff/mypy |
| N2 | Deleted front matter | findings | IMPLEMENTED / VALIDATING | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 1,085 combined triage tests; Ruff/mypy |
| N3 | Space-containing no-hunk paths | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 127 focused tests; Ruff/mypy |
| N4 | Ignored files in clean trees | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 33 focused tests; Ruff/mypy |
| N5 | Unstaged omission metadata | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 21 focused tests; Ruff/mypy |
| N6 | Verification target workspace | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 31 focused tests; Ruff/mypy |
| N7 | Consumer coverage toolchain | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 35 passed, 1 optional-tool skip; Ruff/mypy |
| N8 | GHES GraphQL URL | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 95 GitHub/SCM tests; Ruff/mypy |
| N9 | Per-architecture lint tool digests | ci | IMPLEMENTED / VALIDATING | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 10 passed, 1 platform skip; Ruff/bash |
| R1 | Approval revision binding | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 42 focused tests; Ruff/mypy |
| R2 | Pinned operator budgets | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 8 focused tests; Ruff/mypy |
| R3 | Monotone clustering and scope union | findings | IMPLEMENTED / VALIDATING | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 761 focused tests; Ruff/mypy |
| R4 | Impact-aware severity | findings | IMPLEMENTED / VALIDATING | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 282 focused tests; Ruff/mypy |
| R5 | Finding occurrence identity | findings | IMPLEMENTED / VALIDATING | [#1199](https://github.com/alexhawat/mergeCraft/pull/1199) | 435 focused tests; Ruff/mypy |
| R6 | Contributing config validation | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 33 focused tests; Ruff/mypy |
| R7 | Checkout revision race | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 20 real-Git/fallback tests; Ruff/mypy |
| R8 | Git show cache identity | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 301 focused Git tests; Ruff/mypy |
| R9 | Same-repository fork trust | security | IMPLEMENTED / VALIDATING | [#1197](https://github.com/alexhawat/mergeCraft/pull/1197) | 236 core +132 broader tests; 1 optional-tool skip; Ruff/mypy |
| R10 | Review cache source context | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 44 focused cache tests; Ruff/mypy |
| R11 | Explicit revision source checkout | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | Local revision mismatch/dirty-tree Git regressions; Ruff/mypy |
| R12 | Resolved repository persistence | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 24 provenance/persistence tests; preflight regression |
| R13 | Target workspace env loading | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 44 startup/environment tests; Ruff/mypy |
| R14 | Anonymous fallback without gh | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 4 focused auth/clone tests; Ruff/mypy |
| R15 | Output usage exit status | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | 17 output tests; Ruff/mypy |
| T1 | Mutation error classification/baseline | ci | IMPLEMENTED / VALIDATING | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 20 tests; Ruff/mypy |
| T2 | Semantic Action E2E receipts/protocol | ci | IMPLEMENTED / IMAGE CI PENDING | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 29 protocol/assertion tests; real host GHA approval/refusal; Ruff/mypy/bash |
| T3 | Clean installed-wheel CLI acceptance | ci | IMPLEMENTED / VALIDATING | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | Clean wheel acceptance; 6 packaging tests; Ruff/mypy |
| T4 | Locked CI bootstrap | ci | IMPLEMENTED / VALIDATING | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | real stale-lock bootstrap regression; Ruff |
| DOC1 | Released pinned onboarding | docs | IMPLEMENTED / VALIDATING | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | 26 docs tests; generated packages; Ruff |
| DOC2 | Supported/tested/published matrix | docs | IMPLEMENTED / VALIDATING | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | 9 docs tests; generator drift; Ruff |
| DOC3 | CLI workspace behavior documentation | cli | IMPLEMENTED / VALIDATING | [#1198](https://github.com/alexhawat/mergeCraft/pull/1198) | Documented workspace and output contracts |
| DOC4 | Enforce reliable deterministic checks | ci | IMPLEMENTED / IMAGE CI PENDING | [#1200](https://github.com/alexhawat/mergeCraft/pull/1200) | 78 guard/workflow tests; permissions; Ruff |
| DOC5 | Dated audit/history and complete remediation index | docs | IMPLEMENTED / VALIDATING | [#1201](https://github.com/alexhawat/mergeCraft/pull/1201) | Dated report, probes, open-work snapshot and full finding index |

## Verification and execution contract

Each fix includes a focused regression suite, lint/format checks and appropriate typing checks. The regression cases exercise observable behavior, including real Git histories and consumer environments. Counts above overlap and must not be added as unique tests. Combined static/build, unit, coverage and deterministic integration validation is recorded below when complete. Platform-specific and installed-image evidence remains separate from local Python evidence.

The original audit probes reproduce defects against the audit source commit; they are historical evidence, not the repaired behavior's acceptance suite. Source-level regression tests accompany the fixes. No paid model calls or private provider credentials are required.

## Reconciliation and boundaries

- Previously open work remains excluded. Main now includes declared-scope PR #1160, incident/eval/outcome PR #1167, Agents SDK PR #1161 and private-export cleanup PR #1079. Their merged behavior is included in the integration baseline.
- PR #1170 covers fail-then-pass receipts separately. The [original open-work snapshot](audit-2026-11-05-open-work.json) preserves the audit's exclusions.
- Local roster workflow-wiring enforcement was already fixed and is not presented as a new defect.
- Independent human-label/calibration campaigns require real external evidence. The report's comparative assessment does not become an accuracy claim merely because these fixes pass.
- This work creates reviewable changes. It does not alter external branch-protection settings, merge changes, release packages or publish images.

## Combined verification

Validation is in progress. Individual test evidence is listed above. The documentation/index will be updated with the final combined results and any remaining platform limits before the grouped PRs leave draft.
