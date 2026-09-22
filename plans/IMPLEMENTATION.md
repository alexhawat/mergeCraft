# Implementation record

Implementation is in progress on `codex/implement-issue-remediation-20260922`, in `/private/tmp/mergecraft-implementation-20260922`. The original checkout and its existing configuration edit are preserved. Three faster `gpt-5.6-sol` executors use separate worktrees; the coordinator reviews and integrates their commits.

## Baseline and scope

- Original audit: main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`.
- Implementation started from main `d77511cb93438c064c83d50ffdb9228136e8996b` (merged #818), then integrated main `41cf53b3` (merged #817).
- The first source scopes (001/002/004/005/007) did not drift. #818 changed strict analyzer test handling, which is accounted for in new plan 016. #817 changed coverage floors; plan 006 must use the merged baseline and a new attributable final measurement.
- Human labels, chosen live models/budgets, candidate-specific release verification and publication remain separate completion criteria. Synthetic tests do not satisfy them.

## Release inventory (plan 015)

Read-only GitHub inventory on 2026-09-22 found:

- #783 remains open with no accepted label and all six publication targets unchecked.
- `release/0.1.0a2` still names `f98db2a522015b065c50bb451719052387a8a061`.
- No `v0.1.0a2` tag and no GitHub releases were returned.
- [Candidate run 35489981575](https://github.com/alexhawat/mergeCraft/actions/runs/35489981575) failed Full verify; Python distribution, Action E2E, image build, scan, signing, provenance verification and promotion jobs were skipped.
- GHCR package-version inventory returned HTTP 403 because the available GitHub credential lacks `read:packages`. Image/version collision state is therefore **unknown**, not clear. No credential changes were requested for this pending release step.
- No fresh release candidate has been selected: the implementation is still underway and unmerged. No prepare, publish, tag, accepted-label or live-provider action has run.

Before publication, the operator must select a fresh source/version and supply successful candidate-specific CI/image/signature, scheduled integration/security and adoption receipts. The verified source → digest → manifest → consumer pin chain remains required. The old failed request cannot approve a new source.

## Verification

The 85 audit/probe tests in VERIFICATION.md describe the original bugs and are not verification of these fixes. The coordinator independently inspected the integrated diffs and ran the following focused checks with the fresh isolated development/tracing environment (seed 424242):

| Plans | Integrated commits | Independent result |
|---|---|---|
| 002 finalized verdict | `a648bef2` | 77 passed across terminal submission, verdict policy/harness and publication body tests |
| 003 reviewer/Git tokens and revocation | `a51188bd`, `9e8b327e` | 56 passed across token, Action phase and trust ordering tests |
| 004 publication retry | `10130b5e` | 32 passed across outcome, anchor recovery and real MCP review tests |
| 001 persistence redaction, 017 ordinary filenames | `9c101677`, `9afaacec` | 248 passed across trajectory/read coverage/packet and five analyzer-redaction test files |

| 007 adjudication round-trip and corpus synchronization | `e1bb753f` | 117 passed; eval corpus sync check, structural/adversarial gate and installed-wheel convergence passed |

These are focused checks, not a completed full CI gate. The initial redaction-check command named a nonexistent test file and ran no tests; the corrected exact-file invocation above completed successfully. The baseline generated-documentation check also passed.

Issue #827 was filed during implementation after a deterministic reproduction showed that the shared redactor masked the shipped doctrine filename. The central correction preserves bounded ordinary uppercase identifier components while existing high-entropy and credential-prefix tests remain green; trajectory persistence never restores redactor-removed values.

Issue #828 was filed for installation-token revocation reporting success without checking the HTTP response. The fix checks the status, keeps cleanup best effort across all owned tokens, and tests rejected revocations without leaking credentials.
