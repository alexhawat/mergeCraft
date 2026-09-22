# Plan 003: Separate Git access from reviewer API permissions

- Status: TODO
- Issue: [#821](https://github.com/alexhawat/mergeCraft/issues/821)
- Related lifecycle defect found during implementation: [#828](https://github.com/alexhawat/mergeCraft/issues/828).
- Priority: P1; effort: M; change risk: HIGH; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: None.

## Intent and current state

Internally minted App tokens are limited to contents/workflows but reused as the MCP API credential. A successful mint can prevent PR reviews, comments and checks that the installation is otherwise allowed to create.

`utils/token.py:192–219` requests git_perms then uses the returned token for git_token and mcp_token. `main.py:844–846` binds SCM to mcp_token. MockTransport probes confirmed the actual restricted wire body.

```python
git_perms = (
    {"contents": "read"} if push == "disabled" else {"contents": "write", "workflows": "write"}
)
minted = await acquire_installation_token(repos=write_repos, permissions=git_perms)
# returned as both git_token and mcp_token
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/utils/token.py`
- `src/mergecraft/main.py`
- `tests/utils/test_token.py`
- `tests/test_main_phases.py`
- `tests/security/test_trust_ordering.py`
- `docs/authentication.md`
- `llms-full.txt` (generated from the documentation source)

Match TokenRef.aclose and existing httpx.MockTransport cases in tests/utils/test_token.py. Use GitHub's explicit installation permission contract; do not expand to all installation grants.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/003-app-reviewer-permissions` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/utils/token.py src/mergecraft/main.py tests/utils/test_token.py tests/test_main_phases.py tests/security/test_trust_ordering.py docs/authentication.md llms-full.txt`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "test_token or main_phases or trust_ordering"'` → all selected tests pass. This Make override still collects the suite and selects by name.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Add wire-level failing tests for internally minted App credentials with `GH_TOKEN` absent, push disabled/restricted, reviewer publication enabled, and xrepo scopes. Assert the exact repository list and GitHub installation permission body for each token role. Cover same-repository operation plus primary-repository review with xrepo reads/writes; a cross-repository list must never displace the primary repository from the API token. Replace tests that pin the incomplete permission map.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Derive the permission request at the Action phase-trust boundary: `ctx.settings` has already been trust-filtered before `resolve_tokens` (`main.py:816–842`), and payload `statusChecks` is already resolved. Move/reuse the existing SARIF resolver there so the effective action-input override is known before minting; do not invent new feature flags. Mint separately scoped tokens where repositories or permissions differ. This is the verified runtime matrix:

| Runtime operation and source | GitHub App permission | Token and repositories |
| --- | --- | --- |
| repository/commit/diff reads used by reviewer tools (`mcp/server.py:133–180`) | `contents: read` | reviewer API token, primary repo |
| PR reads, inline comments, and terminal review publication (`mcp/review.py:760–830,1268–1390`) | `pull_requests: write` | reviewer API token, primary repo |
| required `report_progress` create/update path (`mcp/comment.py:181–248`; admitted by `mcp/shared.py:45–62`) | `issues: write` | reviewer API token, primary repo |
| always-exposed check-suite/run and workflow-log diagnostics (`mcp/server.py:151–157`) | `checks: read`, `actions: read` | reviewer API token, primary repo |
| opt-in check-run publication when payload `statusChecks` is true (`utils/status_checks.py:237–309`) | `checks: write` (supersedes `checks: read`) | reviewer API token, primary repo |
| opt-in SARIF upload when the existing resolved setting is true (`utils/code_scanning.py:94–169`) | `security_events: write` | reviewer API token, primary repo |
| Git fetch only | `contents: read` | git token, primary/authorized configured write repos |
| enabled/restricted Git push, including workflow-file changes | `contents: write`, `workflows: write` | git token, primary/authorized configured write repos |
| configured xrepo read checkout | `contents: read` | distinct read token, only configured read repos |

Do not request `statuses`: the enabled status surface posts check runs, and `create_status` has no production caller in this flow. General issue/label/PR mutation tools are filtered out of the primary reviewer role by the class/allowlist contract (`mcp/shared.py:37–62`, `mcp/server.py:200–219`), so do not add grants for unreachable operations. Keep writes absent when their existing capability is disabled. Do not change the unrelated standalone `gha token` command.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Verify the complete contract

Cover acquisition failure, missing installation grants, partial mint cleanup, and revocation of every distinct internally minted token exactly once, including idempotent `TokenRef.aclose`. Preserve existing aliases without double revocation. Cover no-App job-token fallback, caller-owned pre-minted `GH_TOKEN` without revocation, and untrusted runs. If a later mint fails after an earlier one succeeds, revoke the partial result before applying the existing fallback contract. Emit actionable redacted diagnostics; never retry with broader grants. Update the App permission table to match the tested capability matrix, then run `make llms` and require only the expected generated `llms-full.txt` change. Run `make docs-check` and the final gates.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

Implementation review amendment: `revoke_installation_token` currently ignores the DELETE response status and logs success even for 401/403/5xx. Check the HTTP status before logging success, preserve best-effort cleanup of all other owned tokens, and add mocked success/rejection regressions with redacted diagnostics. This is inside the existing token.py/test_token.py scope and must be verified before closing #828.

- [ ] MockTransport requests include the required reviewer permissions and preserve read-only Git when push is disabled.
- [ ] API, git-write, and xrepo-read repository scopes are explicit; the primary repository remains available to the reviewer API token.
- [ ] Every distinct internally acquired token is revoked once, including partial-mint failure; external/job tokens remain caller-owned.
- [ ] `make llms` regenerates `llms-full.txt`, and `make docs-check` passes with no unrelated generated drift.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if the chosen design would broaden untrusted authority, require a real credential, or enable previously forbidden Git writes. Never use live secrets for tests. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Maintain the tested capability-to-permission table when adding SCM operations. Stop and reconcile if the settings required to compute enabled capabilities are unavailable before token resolution; do not guess or request a superset.
