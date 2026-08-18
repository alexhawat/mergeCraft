# PR DG8 — describe, suggest, TODO, effort band, comment router — test plan (DG8.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG8)
Worktree: `../mergecraft-dg8-pr-utilities` @ `wave/dg8-pr-utilities`
Authoring wave: **DG8.1** (tests-first). Implementation: **DG8.2**.

Locked decisions: **convention 3** (review-only — no writes to the reviewed tree),
**D11** (suggestions are output-only forever).

## xfail schedule

| Test file | Tests | Marker | Status |
|-----------|-------|--------|--------|
| `tests/modes/test_describe.py` | 2 | `green after DG8.2` | RED |
| `tests/pr/test_suggestions.py` | 2 | `green after DG8.2` | RED |
| `tests/pr/test_todo_detection.py` | 1 | `green after DG8.2` | RED |
| `tests/pr/test_effort_band.py` | 1 | `green after DG8.2` | RED |
| `tests/pr/test_label_suggestions.py` | 1 | `green after DG8.2` | RED |
| `tests/mcp/test_comment_router.py` | 4 | `green after DG8.2` | RED |

**Acceptance (DG8.1):** 11 collected; 0 pass; 11 xfail. `make lint` + `make typecheck` clean.

## Target API DG8.2 must satisfy

### `src/mergecraft/pr/describe.py` (new)

| Symbol | Contract |
|--------|----------|
| `DescribeOutput` | `title`, `body`, `walkthrough`, `risk_summary`, `test_summary` — all non-empty strings |
| `build_describe_output(diff, pr_metadata, *, repo_root=None)` | Standalone describe prose; never writes under `repo_root` |

### `src/mergecraft/pr/suggestions.py` (new)

| Symbol | Contract |
|--------|----------|
| `generate_pr_suggestions(diff, pr_metadata, kinds, *, repo_root=None)` | Returns text for `changelog` / `docs` / `tests`; `applied=False`; `written_paths=()` |
| D11 | Test suggestions are prose only — no `.py` files created under the repo |

### `src/mergecraft/pr/todo_detection.py` (new)

| Symbol | Contract |
|--------|----------|
| `scan_todo_additions(diff)` | List of findings with `path`, `line`, `text`, `risk_level` for added TODO/FIXME/HACK lines |

### `src/mergecraft/pr/effort_band.py` (new)

| Symbol | Contract |
|--------|----------|
| `classify_effort_band(diff, pr_metadata, change_signals)` | Returns `band` in `{xs,s,m,l,xl}`; no `minutes` / `estimated_minutes`; rationale has no minute/hour guesses |

### `src/mergecraft/pr/label_suggestions.py` (new)

| Symbol | Contract |
|--------|----------|
| `suggest_labels(..., github=...)` | Async; returns `suggested: list[str]`, `applied=False`; never calls `add_labels` / `create_label` |

### `src/mergecraft/mcp/comment_router.py` (new)

| Symbol | Contract |
|--------|----------|
| `route_comment(body, author_association, allowlist, repo_settings, payload_permissions)` | Maps `/mergecraft review|ask|explain|verify|describe` → modes; refuses untrusted authors; `effective_permissions` cannot widen payload |
| `route_finding_challenge(...)` | Routes fingerprint challenges to verifier (`target="verifier"`), not mutating modes |

## Contract → coverage matrix

| # | Test | Layer | Contract |
|---|------|-------|----------|
| 1 | `test_emits_title_body_walkthrough_risk_and_test_summary` | unit | Describe output sections |
| 2 | `test_describe_never_writes_to_the_repo` | functional | convention 3 |
| 3 | `test_changelog_docs_and_test_suggestions_are_text_only` | unit | D11 text-only |
| 4 | `test_test_suggestions_are_not_written_to_disk` | functional | D11 no test files |
| 5 | `test_risky_todo_additions_are_flagged` | unit | TODO scan |
| 6 | `test_emits_a_band_not_a_fake_minute_estimate` | unit | Effort band, not minutes |
| 7 | `test_labels_are_suggested_not_applied` | integration | Advisory labels |
| 8 | `test_slash_commands_route_to_the_right_mode` | unit | Slash routing |
| 9 | `test_commenter_permissions_gate_the_capability` | unit | Author association gate |
| 10 | `test_chat_cannot_widen_push_or_shell_permission` | unit | Permission escalation guard |
| 11 | `test_finding_challenge_routes_to_the_verifier` | integration | Verifier routing (DG7 pair) |

Shared fixtures: `tests/pr/conftest.py` (`sample_diff`, `sample_pr_metadata`).
