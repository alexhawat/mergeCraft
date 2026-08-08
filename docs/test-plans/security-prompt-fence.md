# Security — per-run prompt fencing (#73) — test plan (W3 RED)

Wave plan: `.ignorelocal/waves/issues-security-trust-boundary-wave-plan.md`
Worktree: `mergecraft-sec-b-prompt-fence` @ `wave/sec-b-prompt-fence`

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W4** | `tests/utils/test_fence.py::test_nonce_is_per_run_and_unpredictable` | `green after W4: fence untrusted PR/comment text with per-run nonce (#73)` |
| **W4** | `tests/utils/test_fence.py::test_forged_close_does_not_escape_fence` | same |
| **W4** | `tests/utils/test_fence.py::test_forged_open_does_not_open_a_second_fence` | same |
| **W4** | `tests/utils/test_fence.py::test_untrusted_text_appears_only_inside_fence` | same |
| **W4** | `tests/utils/test_fence.py::test_fence_carries_author_and_trust_tier` | same |
| **W4** | `tests/utils/test_fence.py::test_maintainer_authored_fields_pass_through_unfenced` | same |
| **W4** | `tests/utils/test_fence.py::test_maintainer_exemption_is_per_field_not_per_thread` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_every_pr_title_in_prompt_is_fenced` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_every_pr_body_in_prompt_is_fenced` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_every_event_instructions_in_prompt_is_fenced` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_every_previous_runs_note_in_prompt_is_fenced` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_offline_diff_review_fences_extra_instructions` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_offline_diff_summary_lists_paths_unfenced` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_injected_pr_body_does_not_change_surrounding_prompt` | same |
| **W4** | `tests/instructions/test_prompt_fencing.py::test_offline_diff_review_fences_commit_messages` | same |
| **W4** | `tests/instructions/test_offline_review_fence.py::test_injected_pr_body_does_not_change_findings` | same |
| **W4** | `tests/instructions/test_offline_review_fence.py::test_offline_diff_review_fences_commit_messages_and_patch_headers` | same |

All cross-wave markers use `strict=False`. The non-xfail
`test_fence_module_is_collectable` collection test stays un-marked and
gates the suite's importability — the fence module is absent before W4
and the test cleanly `pytest.skip`s until then.

## Contract matrix

Per D7, D8, D9 of the wave plan. The test names below map to W3.1–W3.7
in the plan.

| Plan W | Decision | Layer | Scenario | Primary test |
|--------|----------|-------|----------|--------------|
| **W3.1** | D7 — port `envelope.py` contract; per-run nonce; data-not-instructions preamble; unforgeable closing delimiter | Functional (full offline path) | Identity — injected body yields same prompt structure (outside the fence) as benign body | `test_injected_pr_body_does_not_change_findings` |
| **W3.2** | D7 unforgeable closing delimiter | Unit | Forged closer with wrong nonce stays inside the block; the real nonce appears exactly twice (open + close) | `test_forged_close_does_not_escape_fence`, `test_forged_open_does_not_open_a_second_fence` |
| **W3.3** | D7 per-run nonce; D5 unforgeable | Unit | Two `Fence()` calls produce different nonces; nonce is 16 lowercase hex; `Fence()` takes no payload args | `test_nonce_is_per_run_and_unpredictable` |
| **W3.4** | D8 closed-set enumeration | Unit (per-field) | PR title, PR body, review comment body, issue comment body, commit message each appear only inside a fence | `test_untrusted_text_appears_only_inside_fence`, plus per-field `test_every_pr_*_in_prompt_is_fenced` |
| **W3.5** | D7 provenance line; D8 trust-tier weighting | Unit | The fence header names the author login and the trust tier from `derive_trust_tier()` | `test_fence_carries_author_and_trust_tier` |
| **W3.6** | D8 closed-set; #73 proposal item 4 | Functional (offline path) | The `diff-review` path (offline) routes the operator's `prompt_extra` through the fence | `test_offline_diff_review_fences_extra_instructions`, `test_offline_diff_review_fences_commit_messages`, `test_offline_diff_review_fences_commit_messages_and_patch_headers` |
| **W3.7** | D11 maintainer-exempt (per-field, not per-thread) | Unit | `OWNER` / `MEMBER` / `COLLABORATOR` association skips the fence for the one field; sibling attacker comment in the same thread is still fenced | `test_maintainer_authored_fields_pass_through_unfenced`, `test_maintainer_exemption_is_per_field_not_per_thread` |

## Anomaly — fenced assembly invariant for W3.1

`test_injected_pr_body_does_not_change_findings` and
`test_injected_pr_body_does_not_change_surrounding_prompt` are two
expressions of the same property:

- the *full-path stub test* drives `run_offline_diff_review` twice with
  a deterministic agent and asserts structural equality outside the
  fence. This is the W3.1 verbatim acceptance criterion.
- the *prompt-assembly test* does the same comparison directly against
  `resolve_instructions()` for tighter failure isolation.

Both must pass for W3.1 to be considered green. If one passes and the
other fails, the implementation is partial — W4 must fix the failing
half.

## Implementation notes for W4

- **W4.1** Add `src/mergecraft/utils/fence.py` porting the
  `envelope.py` contract: `Fence` dataclass with a 16-hex nonce,
  `render_untrusted(text, *, author, tier, label, nonce)`, and a
  `fence_unless_trusted` (or equivalent) helper that short-circuits on
  `OWNER` / `MEMBER` / `COLLABORATOR` association. The header line
  must include the author login and the trust tier so a reviewer can
  weight it per `docs/REVIEW-DOCTRINE.md`.
- **W4.2** Thread a per-run `Fence` through `resolve_instructions()`.
  Replace `_quote_user()` at every untrusted call site; keep it only
  where the text is maintainer-authored.
- **W4.3** Fence the full D8 set at their assembly points:
  `_build_event_title()` / `_build_event_metadata()` for PR title and
  event body; `eventInstructions` / `previousRunsNote` paths; the
  `agents/reviewer.py` and `agents/shared.py` paths where review
  threads and issue comments enter; `src/mergecraft/offline_review.py`
  and `utils/offline_diff.py` for the operator's `prompt_extra` and
  commit messages / patch headers.
- **W4.7** Un-xfail W3.1–W3.7. All `strict=False` xfails flip to
  green. No marker changes elsewhere in the suite.
