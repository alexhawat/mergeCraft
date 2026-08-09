# Issue #72 — invocation authorization — test plan (W1 RED)

Wave plan: `.ignorelocal/waves/issues-security-trust-boundary-wave-plan.md`
Worktree: `mergecraft-sec-a-invocation-gate` @ `wave/sec-a-invocation-gate`
Issue: [#72 — comment-trigger authorization](https://github.com/alexhawat/mergeCraft/issues/72)

## Scope

`resolve_native_event()` (`src/mergecraft/utils/payload.py:190-258`) currently builds
the `issue_comment` / `pull_request_review_comment` event dicts from `comment.body`
and `issue.number` **without ever reading `comment.author_association`** — the field
is present in every GitHub comment webhook payload and is simply dropped. W2 adds the
author-association gate and the `pull_request_target` opt-in. W1 only writes the
RED suite that proves the gate and the opt-in are missing today.

The test surface is the boundary `resolve_native_event()` (and the dispatch layer
above it, `resolve_payload()`), not the trust primitives. `is_collaborator(event)`
and `COLLABORATOR_PERMISSIONS = frozenset({"admin","maintain","write"})` at
`payload.py:26,145-147` are read-only inputs that already exist; they cover the
`author_permission` axis. W2 adds a parallel frozenset for `author_association`
in the same module.

## xfail schedule

All cross-wave markers use `strict=False` (per `pyproject.toml`'s
`xfail_strict = true`, an XPASS is treated as `xfail(strict=False)` would
report it — not as a hard failure — so the regression guard in W1.6 stays
green today and after W2 without erroring).

| Wave | Test | Marker reason |
|------|------|---------------|
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_from_non_collaborator_does_not_dispatch[NONE]` | `green after W2: author-association gate (#72, D5)` |
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_from_non_collaborator_does_not_dispatch[CONTRIBUTOR]` | same |
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_from_non_collaborator_does_not_dispatch[FIRST_TIME_CONTRIBUTOR]` | same |
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_from_collaborator_dispatches[OWNER]` | `green after W2: collaborator allowlist (#72, D5)` |
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_from_collaborator_dispatches[MEMBER]` | same |
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_from_collaborator_dispatches[COLLABORATOR]` | same |
| **W2** | `tests/utils/test_payload.py::test_comment_trigger_missing_author_association_does_not_dispatch` | `green after W2: fail-closed on missing field (#72, D5)` |
| **W2** | `tests/utils/test_payload.py::test_author_association_is_read_from_payload_not_body` | `green after W2: payload-not-body injection resistance (#72)` |
| **W2** | `tests/utils/test_payload.py::test_pull_request_target_comment_trigger_refused_without_optin` | `green after W2: pull_request_target comment refusal (#72, D6)` |
| **W2** | `tests/utils/test_payload.py::test_pull_request_target_comment_trigger_dispatches_with_optin` | `green after W2: opt-in input (#72, D6)` |
| **W2** | `tests/utils/test_payload.py::test_pull_request_synchronize_under_target_still_dispatches` | `green after W2: synchronize regression guard (#72)` |
| **W2** | `tests/utils/test_payload.py::test_pull_request_review_comment_from_non_collaborator_does_not_dispatch[NONE]` | `green after W2: review-comment path covered (#72, D5)` |

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#72** | D5 — `author_association` gate | Unit | Happy path: `OWNER`/`MEMBER`/`COLLABORATOR` still dispatches | `test_comment_trigger_from_collaborator_dispatches[OWNER/MEMBER/COLLABORATOR]` |
| **#72** | D5 | Unit | Edge: `NONE` / `CONTRIBUTOR` / `FIRST_TIME_CONTRIBUTOR` → no dispatch | `test_comment_trigger_from_non_collaborator_does_not_dispatch[*]` |
| **#72** | D5 | Unit | Edge: `author_association` absent → no dispatch (fail closed, convention 5) | `test_comment_trigger_missing_author_association_does_not_dispatch` |
| **#72** | D5 | Unit | Injection: body claims `author_association: OWNER` but payload field is `NONE` → no dispatch | `test_author_association_is_read_from_payload_not_body` |
| **#72** | D6 — `pull_request_target` comment refusal by default | Unit | Edge: `pull_request_target` + `issue_comment` from `COLLABORATOR` → no dispatch without opt-in | `test_pull_request_target_comment_trigger_refused_without_optin` |
| **#72** | D6 | Unit | Functional: opt-in input set → dispatches | `test_pull_request_target_comment_trigger_dispatches_with_optin` |
| **#72** | regression guard | Unit | Edge: `pull_request` synchronize still dispatches | `test_pull_request_synchronize_under_target_still_dispatches` |
| **#72** | D5 — same gate covers `pull_request_review_comment` | Unit | Edge: `pull_request_review_comment` from `NONE` → no dispatch | `test_pull_request_review_comment_from_non_collaborator_does_not_dispatch[NONE]` |

## Decisions baked in (carried from the wave plan)

- **D5:** the gate reads `payload["comment"]["author_association"]` from
  `GITHUB_EVENT_PATH` — never a value inferred from the comment text. Allowed
  set: `{"OWNER","MEMBER","COLLABORATOR"}`. Anything else → `None` from
  `resolve_native_event()`. Missing field → `None` (fail closed).
- **D6:** under `GITHUB_EVENT_NAME == "pull_request_target"`, comment-driven
  invocation is refused by default and requires an explicit opt-in input. W2
  will add the opt-in input (e.g. `INPUT_ALLOW_PR_TARGET_COMMENTS`); W1 sets
  the env var directly in the test, since the input is the implementation's
  choice.
- **W2.2 (wave plan):** reuse `COLLABORATOR_PERMISSIONS` vocabulary; the new
  `author_association` frozenset lives next to it in the same module. W1 does
  not assert the location — only the observable boundary.

## Implementation notes for impl waves

- **W2:** un-xfail every case in `tests/utils/test_payload.py` listed above
  in one PR. The xfail markers all share the same `green after W2:` prefix,
  so they can be found with a single grep.
- **W2.4 / W2.5:** the new opt-in input lands in `action.yml`; the env var
  the tests set is `INPUT_ALLOW_PR_TARGET_COMMENTS`. Reading via
  `get_action_input` (or `os.environ.get("INPUT_ALLOW_PR_TARGET_COMMENTS")`)
  is fine; the test contract is the env var name only, not the access
  helper.
- **W2.7 / W2.8:** un-xfail is mechanical; no logic change in the tests is
  expected.

## Out of scope for W1

- The actual `author_association` frozenset definition in `payload.py` (W2.2).
- The new action.yml input (W2.4, W2.7).
- The example workflow re-render (W2.6) — does not touch tests.
- A test for `pull_request_target` + `pull_request_review_comment` —
  W1.5 covers the `issue_comment` half; the `pull_request_review_comment`
  half is the same code path and is asserted once (W1.1x). If W2's review
  PR diverges, add a parametrized case then.
