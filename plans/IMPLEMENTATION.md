# Implementation record

Implementation is in progress on `codex/implement-issue-remediation-20260922`, in `/private/tmp/mergecraft-implementation-20260922`, at `157f57a3`. The original checkout and its existing configuration edit are preserved. The initial wave used three faster `gpt-5.6-sol` executors; subsequent work is assigned to the available `gpt-5.6-luna` model. The coordinator reviews and integrates their commits.

## Baseline and scope

- Original audit: main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`.
- Implementation started from main `d77511cb93438c064c83d50ffdb9228136e8996b` (merged #818), then integrated main `41cf53b3` (merged #817).
- Integrated main `e79217be` after plan PR #826 merged. Its plan contents exactly matched the originally cherry-picked plans; the merge retains subsequent implementation refinements and adds no source drift.
- The first source scopes (001/002/004/005/007) did not drift. #818 changed strict analyzer test handling, which is accounted for in new plan 016. #817 changed coverage floors; plan 006 must use the merged baseline and a new attributable final measurement.
- Human labels, chosen live models/budgets, candidate-specific release verification and publication remain separate completion criteria. Synthetic tests do not satisfy them.

## Current verification state

- The latest integrated change is `157f57a3` (`fix(ci): reject coverage metadata drift`). It adds combine-time source/runtime identity checks and has 38 focused agent tests recorded across the integrated remediation work. A full serial coverage measurement is still running; the initial report, final floors, final CI gate and fresh shard/parity comparison are pending.
- The first whole-shard attempt is not a passing result: group 1 reported **1 failed, 5,011 passed, 9 skipped and 3 xfailed**; group 2 was interrupted after **3 failed, 1,037 passed and 3 skipped**. The failure analysis found nested fixture runs inheriting the outer shard variables. Test-only cleanup commit `aa6bcac7` is pending and is recorded as unintegrated until the coordinator reviews it.
- Queued test-only Loguru capture lifetime fixes are `9829600d` and `960366d9`; they remain pending. These test cleanups do not prove the full gate.
- Final validation remains open: whole-tree coverage floors, full `make ci`, fresh shard/parity evidence, and the initial implementation report have not been completed. Keep plan status and issue closure language conditional until those artifacts exist.

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

The 85 audit/probe tests in VERIFICATION.md describe the original bugs and are not verification of these fixes. The coordinator independently inspected the integrated diffs and ran the following focused checks with the fresh isolated development/tracing environment (seed 424242 unless stated):

| Plans | Integrated commits | Independent result |
|---|---|---|
| 002 finalized verdict | `a648bef2` | 77 passed across terminal submission, verdict policy/harness and publication body tests |
| 003 reviewer/Git tokens and revocation | `a51188bd`, `9e8b327e` | 56 passed across token, Action phase and trust ordering tests |
| 004 publication retry | `10130b5e` | 32 passed across outcome, anchor recovery and real MCP review tests |
| 001 persistence redaction, 017 ordinary filenames | `9c101677`, `9afaacec` | 248 passed across trajectory/read coverage/packet and five analyzer-redaction test files |
| 005 exact successful-read attribution | `a0af80d9`, `6e2e09ed` | 292 passed across the same eight evidence/redaction files, including literal colon Git pathspec regression |
| 006 true line and branch coverage | `0b804ab8` | 47 passed across seven coverage CI files; numeric floors unchanged; final full measurement pending |
| 007 adjudication round-trip and corpus synchronization | `e1bb753f` | 117 passed; eval corpus sync check, structural/adversarial gate and installed-wheel convergence passed |
| 008 isolated coverage shards | `b2a899ee` | 33 passed, including real xdist/split fixture parity, manifest tampering/incompleteness, source drift and failure propagation; final whole-tree parity pending |
| 009 complete lifecycle tracing | `327a6d2c` | 410 tracing tests passed, plus 12 HTTP tracing tests with loopback access; real Docker OTLP collector passed 7 pre-seed and 2 post-seed tests (wrapper seeds 3886865826 and 3250636949) |
| 012 offline trajectory scorer | `7d384ac9` | 80 passed across scorer, trajectory and run-packet tests; development fixtures remain advisory, with human protocol/enforcement pending |
| 013 offline judge calibration | `ddd442d3` | 102 protocol, scoring, provenance/seal and CLI tests passed; actual independent human labels and held-out validation remain pending |
| 011 human review preparation | `ec2481f6` | 14 strict manifest/evidence tests passed; rendered [nine-case review sheet](HUMAN-REVIEW.md), all evidence missing and decisions unanswered |
| 010 complete setup artifact instructions | `3ffdd697` | 42 existing setup/documentation tests passed |
| 016 visible provisioning failure causes | `0edae3fb` | 68 adapter, contract, supply-chain, provisioning and sandbox tests passed |
| 014 offline benchmark publication | `e79fdeec` | 66 publication, receipt, live-boundary and calibration tests passed; one expected xfail for still-unpublished live metrics |

These are focused checks, not a completed full CI gate. The initial redaction-check command named a nonexistent test file and ran no tests; the corrected exact-file invocation above completed successfully. The baseline generated-documentation check also passed.

Issue #827 was filed during implementation after a deterministic reproduction showed that the shared redactor masked the shipped doctrine filename. The central correction preserves bounded ordinary uppercase identifier components while existing high-entropy and credential-prefix tests remain green; trajectory persistence never restores redactor-removed values.

Issue #828 was filed for installation-token revocation reporting success without checking the HTTP response. The fix checks the status, keeps cleanup best effort across all owned tokens, and tests rejected revocations without leaking credentials.

The first tracing run could not bind its local HTTP server under the sandbox; the affected 12-test file was rerun with loopback access and passed. The supported Docker collector target completed successfully and cleaned up its test container. These checks establish trace transport and parenting, not a live provider evaluation.

An intermediate integrated `make ci-static` passed lock/lint, both type checkers, catalog and agent checks, package build, examples and CLI examples. It stopped at the expected generated CLI reference drift for the newly added calibration command; final generation is deferred until all new commands are integrated. The intermediate `make security` passed (no medium/high Bandit findings and no known dependency vulnerabilities). These results do not substitute for the final combined-tree gate.

A final independent review reproduced source drift during combine-time test collection in plan 008. The existing shard-time checks did not cover this boundary. The plan is refined to recheck the validated source/runtime identity after collection and around combination/reporting/gating, with mutation regressions before the complete measurement.
