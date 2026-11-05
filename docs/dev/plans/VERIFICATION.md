# Audit verification record

Date: 2026-09-22. Source: immutable main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`. PR #817 head: `d72b4e77dd47d7937527837b3f653a858804cf4e`.

## Read-only audit method

Read repository guidance, architecture/review doctrine, contribution and release rules, package/Make/CI configuration, all 14 open issues and comments, PR #817 metadata/diff and the current PR queue. Main was independently checked against GitHub. Inspection used `git show` and a temporary archive so the older local pre-0.0.1 checkout and existing config modification were preserved.

Three bounded read-only audit passes covered evaluation/trajectory, runtime/auth/tracing, and tooling/release/docs. Each finding retained here was reread in source by the primary auditor. Searches across open and closed issues were used to reject duplicate reports. Six issues were created with the authenticated GitHub CLI after the connector lacked write permission; no other GitHub mutation was performed.

## Test receipts

Tests ran against the immutable-main temporary archive using the existing development interpreter, through temporary Make targets. No packages were installed and no live provider or external review API was invoked.

| Selection | Result | What it establishes |
|---|---|---|
| Mocked publication retry and internally minted App token permission probes | **3 passed** | Both defects reproduce through real tool/token flows. These tests assert current faulty behavior. |
| tests/tracing/instrumentation; tests/tracing/exporters/test_otlp_sink_parent_context.py; tests/tracing/test_trace_id_bridge.py; tests/utils/test_token.py | **51 passed, 2 skipped** | Existing tracing/token behavior and test coverage; two skips require unavailable optional OTel dependencies. |
| tests/ci/test_checkout_credential_persistence.py; tests/evidence/test_trajectory_read_coverage.py; tests/skills/test_no_comment_trigger_claim.py | **31 passed** | #790 and #796's implemented fixes and corrected trigger wording are protected. This does not prove the residual AGENTS file-list correction complete. |

Total: **85 passed, 2 skipped** across these selected tests/probes. This is not the full product suite or a new coverage baseline.

## Deterministic reproduction results

### #819: trajectory redaction

A fabricated token was inserted into a shell grep command. Only boolean membership results were printed; no real credential was read.

```text
synthetic_retained_in_command=False
synthetic_retained_in_paths=True
synthetic_retained_in_serialized_trajectory=True
```

Real functions: record_tool_call → build_trajectory_record. Source inspection confirms trajectory serialization is embedded in run_packet and written verbatim by emit.write_packet.

### #820: severity normalization and terminal verdict

Production ordering was exercised with requested approve and `{"path":"README.md","body":"README spelling typo","severity":"Major","line":1}`.

```text
raw_severity=Major
requested=approve
normalized_severity=Trivial
recorded_verdict=request_changes
validate_submission.accepted=True
```

Real functions: prepare_terminal_submission → normalize_agent_findings_via_pipeline → validate_submission. Source inspection confirms GitHub publication derives REQUEST_CHANGES from this stored verdict.

### #821: internally minted App permissions

Real resolve_tokens and acquire_installation_token with httpx.MockTransport, synthetic App inputs, GH_TOKEN absent:

```text
push=disabled:   permissions={'contents': 'read'}
push=restricted: permissions={'contents': 'write', 'workflows': 'write'}
both: returned installation token becomes mcp_token
```

GitHub's explicit permissions parameter restricts installation grants. Review creation requires pull_requests write; the current requested set does not include it.

### #822: publication recovery

The actual create_pull_request_review tool was called twice with mocked API behavior: first transient exception, then valid review receipt.

```text
successful_review_id=77
terminal_publication_failed=True
outcome=inconclusive
reason=terminal review verdict was recorded but never published to GitHub
```

No real review was created.

### #823: observed shell read

Real record/build/auditor flow with successful shell `cat src/app.py` and authoritative changed path src/app.py:

```text
files_read=['cat src/app.py']
changed-unread-file paths=['src/app.py']
```

This is a new read-attribution bug, distinct from #796's now-fixed modified-path pollution.

### #824: module coverage false pass

The unchanged script received a complete synthetic report, with all other required modules and prefixes at 100%. git_setup had 90/100 covered statements and 100/100 branches. Coverage.py combined percent is 95.

```text
actual line percentage=90
current declared line floor=91.5
combined percentage=95
exit_code=0
coverage floor check OK
```

PR #817's 92.0 threshold also remains below the incorrectly used combined 95%, so the same false pass survives it. Installed coverage reporter/Numbers.pc_covered semantics were inspected.

### #779: real golden-case writer

A copied golden Django JSON object was adjudicated in a temporary directory using default policy, then reloaded:

```text
writer reports success
top-level shape=list
CorpusCase validation: model_type error
unwrapped object validation: provenance and adjudication extra_forbidden
```

No tracked corpus file was modified.

## Plan PR verification

The plan publication uses a new `codex/issue-remediation-20260922` branch and isolated worktree based on the audited main SHA. The original checkout and its existing configuration change were preserved. Three fresh-context `gpt-5.6-sol` subagents reviewed runtime, evaluation and tooling/release instructions against this source; the primary reviewer checked their corrections before integration.

- `make docs-check` passed using this worktree's source on `PYTHONPATH` and the existing development interpreter. Using the old checkout's editable package without that source override initially produced unrelated CLI drift; the corrected source selection passed without changing generated files.
- `make tracked-markdown-check` passed with the plan documents staged.
- All 24 plan Markdown files have resolving local links; the index covers all 20 currently open issues, including the six newly filed bugs.
- Existing Make targets and the syntax of drift-check commands were checked separately from proposed targets. New targets are explicitly described as implementation deliverables.
- Product source is unchanged. No full CI run, new coverage measurement or implementation-success claim is added by these documentation checks.

## Scope boundaries

Examined the paths relevant to every open issue and correctness/security hotspots around terminal review, findings normalization, publication, credentials, trajectory/evidence serialization, eval datasets/scoring, tracing ownership, coverage gates, generated setup guidance and release provenance.

Not exhaustively audited: every analyzer adapter and vendor stream driver, all browser/Harbor integrations, infrastructure/firewall behavior under privileged Linux, all third-party dependencies, or live model quality. No new make ci run, whole-suite coverage measurement, Docker build/scan, privileged sandbox probe, collector deployment, paid benchmark or release occurred.

The verified bugs are a grounded set, not a claim that no other defects exist. Existing PR checks remain separate evidence from this local audit.
