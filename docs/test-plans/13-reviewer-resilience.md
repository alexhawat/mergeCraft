# Reviewer resilience — test plan (W1 RED)

Wave plan: `.ignorelocal/waves/13-reviewer-resilience-wave-plan.md`
Worktree: `../mergecraft-resilience` on `wave/reviewer-resilience`
Authoring wave: **W1** (`test-creator`). Implementation: **W2–W9**.
xfail-reconciliation: per impl wave (`strict=False` until green).

## W3 reconciliation (post-`d625ff4a`)

| Fix | Rationale |
| --- | --- |
| Removed `@pytest.mark.xfail` from 9 ergonomics tests | W3 git verb/config allowlist landed; tests pass without xfail |
| `test_checkout_pr_parameter_aliases_resolve_to_pull_number` | Already green; no xfail was present |

## W4 reconciliation (post-`d625ff4a`)

| Fix | Rationale |
| --- | --- |
| Removed `@pytest.mark.xfail` from 12 degraded-scope tests | W4 degraded checkout, `establish_review_scope`, and scope registration landed |
| `test_auth_head_fetch_yields_api_only_scope` | Assert `reviewPhase` on checkout payload and `ctx.tool_state` (was reading a fresh `_ctx`) |
| `test_get_commit_info_does_not_register_scope_for_other_sha` | `RepoToolState.diff_path` defaults to `None`, not `""` |
| `test_read_only_roles_exclude_mutating_tools_except_checkout_pr` | Admit `establish_review_scope` on primary reviewer (`PRIMARY_MUTATING_ALLOWLIST`) |

## W0 reconciliation

| Fix | Rationale |
| --- | --- |
| `test_gh_secret_receives_the_uncompacted_payload` expects compact JSON on both paths | W0 landing strip applies `_single_line_credential()` to `gh secret set` (ledger B2) |
| `test_checkout_pr_parameter_aliases_resolve_to_pull_number` | Stub `GitHubClient` via `git_ctx(github=)` — classmethod patch omitted `self` through `ctx.scm` |

## Contract → tests

| Contract | Greening wave | Test file |
| --- | --- | --- |
| Refuse `--no-index` for all allowlisted subcommands | W2 | `tests/mcp/test_reviewer_resilience_containment.py` |
| Confine positional paths inside workspace | W2 | `tests/mcp/test_reviewer_resilience_containment.py` |
| Deny `.git/config`, `.git/credentials`, askpass paths | W2 | `tests/mcp/test_reviewer_resilience_containment.py` |
| Redact token-shaped strings in git failure text | W2 | `tests/mcp/test_reviewer_resilience_containment.py` |
| Reproduce run 33126460925 refusal | W2 | `tests/mcp/test_reviewer_resilience_containment.py` |
| Legitimate readonly invocations still pass | W2 | `tests/mcp/test_reviewer_resilience_containment.py` |
| Allow `show-ref`, `for-each-ref`, `ls-remote` | W3 | `tests/mcp/test_reviewer_resilience_ergonomics.py` |
| `config --get remote.origin.url`; refuse credential keys | W3 | `tests/mcp/test_reviewer_resilience_ergonomics.py` |
| Refuse `config --unset` / set forms | W3 | `tests/mcp/test_reviewer_resilience_ergonomics.py` |
| `checkout_pr` aliases `pr_number` / `issue_number` | W3 | `tests/mcp/test_reviewer_resilience_ergonomics.py` |
| Unknown alias → schema error (green today) | W3 | `tests/mcp/test_reviewer_resilience_ergonomics.py` |
| Auth head fetch → `scope: api-only` + diff + `ESTABLISH_SCOPE` | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| `checkout_sha` from API `head.sha` | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| Degraded run may approve (D2) | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| Degradation named in payload | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| Transient fetch retries once; auth-class does not | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| `establish_review_scope` validates diff evidence (D4) | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| `get_commit_info` registers scope at PR head | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| Memoize `git show <rev>:<path>` with `cached: true` | W4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| Record `ToolState.last_terminal_rejection` | W5 | `tests/agents/test_reviewer_resilience_retry.py` |
| Zero resumes for scope rejection | W5 | `tests/agents/test_reviewer_resilience_retry.py` |
| One resume when no terminal call (green today) | W5 | `tests/agents/test_reviewer_resilience_retry.py` |
| `dirty_tree` / `stop_hook` retryable once (green today) | W5 | `tests/agents/test_reviewer_resilience_retry.py` |
| `verdict_diagnostic=scope_unavailable` + deterministic publish stub | W5 | `tests/agents/test_reviewer_resilience_retry.py` |
| Loguru `enqueue=True` + drain | W6 | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| Concurrent writes — line integrity | W6 | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| `consume_stream` → `mark_activity()`; echo removed | W7 | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| Rendered tool call/result/failure lines | W7 | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| `ACTIONS_STEP_DEBUG` retains raw NDJSON pre-D8 | W7 | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| `mcp/shared.py::execute` single error line | W7 | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| Bubblewrap hint once + `::warning::` on exit 0 | W8 | `tests/analyzers/test_reviewer_resilience_environment.py` |
| `checkov` / `yamllint` catalog unavailability on linux-amd64 | W8 | `tests/analyzers/test_reviewer_resilience_environment.py` |
| `make catalog-check` passes with corrected rows | W8 | `tests/analyzers/test_reviewer_resilience_environment.py` |
| Default policy `off`; `derive_trust_tier` unchanged (partial green) | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| Trust level execution/authority pairs | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| Fork PR unaffected | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| `analyzers` runs trusted tools; cannot APPROVE | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| `full` warns at CLI/run start | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| D15 — PR-head edit cannot change effective policy | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| Config hash mismatch fails closed | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |
| `mergecraft trust show` | W9 | `tests/config/test_reviewer_resilience_trust_policy.py` |

## Deliverable symbols

| Symbol | Test anchor |
| --- | --- |
| `_reject_no_index` (W2) | `tests/mcp/test_reviewer_resilience_containment.py` |
| `establish_review_scope_tool` | `tests/mcp/test_reviewer_resilience_degraded_scope.py` |
| `ToolState.last_terminal_rejection` | `tests/agents/test_reviewer_resilience_retry.py` |
| `publish_scope_unavailable_review` (plan 12 seam) | `tests/agents/test_reviewer_resilience_retry.py` |
| `drain_loguru_queue` | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| `render_stream_event` | `tests/agents/test_reviewer_resilience_stream_logging.py` |
| `resolve_trust_policy` | `tests/config/test_reviewer_resilience_trust_policy.py` |
| `mergecraft trust show` / `set-self-review` | `tests/config/test_reviewer_resilience_trust_policy.py` |

## Contract ambiguities

| Topic | Resolution in tests |
| --- | --- |
| Plan 12 deterministic publish signature not landed | Stub `mergecraft.review.deterministic_publish.publish_scope_unavailable_review` via `monkeypatch(..., raising=False)` until plan 12 W5 defines the owned entry point |
| Checkout alias success payload keys | Accept `pullNumber` or `pull_number` until W3 normalises response shape |
| `catalog-check` vs manifest-only assertion | W8 includes both manifest `declared_unavailable` pins and a full `make catalog-check` gate |

## Verification

```bash
cd ../mergecraft-resilience
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"
env -u VIRTUAL_ENV make lint
env -u VIRTUAL_ENV make typecheck
env -u VIRTUAL_ENV uv run pytest --collect-only -q \
  tests/mcp/test_reviewer_resilience_containment.py \
  tests/mcp/test_reviewer_resilience_ergonomics.py \
  tests/mcp/test_reviewer_resilience_degraded_scope.py \
  tests/agents/test_reviewer_resilience_retry.py \
  tests/agents/test_reviewer_resilience_stream_logging.py \
  tests/analyzers/test_reviewer_resilience_environment.py \
  tests/config/test_reviewer_resilience_trust_policy.py \
  tests/cli/test_auth_scope_cmd.py::test_gh_secret_receives_the_uncompacted_payload
```
