# Test plan — triage `lite` tier and the `commentOnly` recognizer

The deterministic pre-dispatch triage (`review.fastPath`) had two tiers: `skip` (no
LLM review) and `full` (today's review). This suite pins a third tier, `lite`: one
capped HTTP call to an operator-registered OpenAI-compatible provider, with the diff
inlined in the prompt and no checkout, MCP server, CLI harness, specialists or
verifier. It also pins a `commentOnly` recognizer for a closed list of `//`-comment
languages.

The rules under test:

- `lite` is chosen in exactly two cases, and only when `review.fastPath.lite.enabled`
  is set in the operator's base-side config: a recognizer matched the whole diff but is
  not in `skipLlm`, or a pin bump matched but its verifying checks have not passed from
  a trusted App. Everything else is `full`. With `lite` disabled both cases stay `full`
  with today's reason.
- The token cap is enforced **before** the call. If the upper-bound estimate
  (`ceil(prompt_bytes / 3)` plus `maxOutputTokens`) exceeds `tokenCap`, the run is
  downgraded to a full review and the network is never touched. A diff is never
  truncated to fit.
- `lite` never grants `mergecraft-approval`. A `lite` run with a `success` decision is
  refused. The `mergecraft` check is `neutral`, or `failure` when the call raised a
  Critical or Major finding. Usage over the cap, or a malformed answer, is
  `inconclusive`. A malformed answer never quietly becomes a full review and is never
  read as a success.
- `commentOnly` refuses whenever it is unsure. A `#`-comment language is never
  recognised.

## Test strategy

Pure functions (`triage_diff`, `recognize_comment_only`, the settings model) get unit
tests with small diffs built inline. The I/O shell (`decide_fast_path`) is driven
through the in-memory `FakeScm` that the existing fast-path gate suite uses. The
single-call driver is driven through an injected `httpx.AsyncClient` on an
`httpx.MockTransport`, so no request leaves the process. A transport that fails the
test if it is reached proves that the cap and credential checks run before the call.
The verdict rules are checked at three levels: the packet builder
(`build_run_packet`), the check-summary and review-record renderers, and a whole
`main()` run through `tests/support/run_main_harness.py` with the driver substituted.
No test calls a live provider.

Until the implementation lands, these tests are expected to fail (they collect
cleanly). New names are imported inside each test, so a missing symbol fails that one
test and does not break collection.

## Seams the implementation must provide

| Seam | Contract the tests rely on |
| --- | --- |
| `mergecraft.config.settings.FastPathLiteSettings` | `enabled: bool = False`, `provider: str`, `model: str`, `token_cap: int = 50_000` (alias `tokenCap`, `ge=4_000`, `le=200_000`), `max_output_tokens: int = 4_000` (alias `maxOutputTokens`); `extra="forbid"` like the rest of `fastPath`. Reached as `FastPathSettings.lite`. |
| `FastPathRecognizer` | Gains `"commentOnly"`. |
| `mergecraft.classify.triage.Tier` | `Literal["skip", "lite", "full"]`. |
| `TriageDecision.token_cap` | `int \| None = None`; set to the configured cap on every `lite` decision, `None` otherwise. `recognizer` names the matched recognizer on a `lite` decision. |
| `TriageDecision.record_line()` | For `lite`: `Tier: lite — single-call review, cap N tokens`, where `N` is the plain integer with no thousands separator. `skip` and `full` lines are unchanged. |
| `triage_diff` | Signature unchanged (`diff_text, config, head_files, passed_checks`). A `lite` reason names the recognizer; an unverified pin bump's reason names the missing check. |
| `recognize_comment_only(diff_text, *, head_files)` | Exported in `triage.__all__`; returns `bool`. |
| `fast_path.load_triage_inputs` | Reads head-side text for comment-only-language files as well as prose files, so `commentOnly` can be proven. |
| `mergecraft.agents.lite.run_lite_review` | Awaitable, called **with keyword arguments only**: `decision=`, `diff_text=`, `settings=` (a `RepoSettings`; the driver reads `review.fast_path.lite` and the `providers` registry), `http_client_factory=`. Any run-context parameter must be optional. `http_client_factory` is a callable returning an `httpx.AsyncClient`. It may be called with keyword arguments such as `timeout`, which test factories ignore. The driver must send its single request through that client. |
| `mergecraft.agents.lite.LiteOutcome` | Constructible with keywords `status`, `reason`, `tokens_used`, `usage_estimated`, `cap_hit`, `findings`, `summary`, `prompt_version`. |
| `mergecraft.agents.lite.LITE_PROMPT_VERSION` | Non-empty `str`; copied to `LiteOutcome.prompt_version`. |
| Provider resolution | `lite.provider` is a registry label. The endpoint is resolved through `resolve_registry_gateway_endpoint(f"{provider}/{model}", settings=...)` (label `cheapo`, `envIndex: 7`, key in `LLM_PROVIDER_7_API_KEY`). The request goes to `{url.rstrip('/')}/chat/completions` with `Authorization: Bearer <key>`. |
| `main.run_lite_review` | `main` calls the driver through its own module attribute, as it does with `load_triage_inputs`, so a test can substitute it with `monkeypatch.setattr(main_mod, "run_lite_review", ...)`. |
| `main._triage_gate` | Reads the pull request once through `main.load_triage_inputs`. For a `lite` decision it calls the driver with that decision and the same diff text, then returns `main.LiteAgentReview(decision, outcome)`, a dataclass whose fields are exactly `decision` and `outcome`, in that order. It records `tool_state.triage` and never calls the driver for `skip` or `full`. |
| Downgrade | A `downgraded` outcome turns the run into the normal full review: the agent runs, and `packet.triage.tier == "full"` with the downgrade reason. |
| Findings | `lite` findings land on `tool_state.reviewer_dispatch_runs` as one `ReviewerRun` with `agent_id="lite"`. |
| `TriageSection` | `tier: Literal["skip", "lite", "full"]`, plus `token_cap`, `tokens_used`, `usage_estimated`, `cap_hit` and `prompt_version` (defaults `None`/`False`). `_triage_section` copies `token_cap` from the decision and the usage fields from the lite outcome. |
| `PACKET_SCHEMA_VERSION` | Strictly above `1.17.0`, and equal to the version in the `docs/evidence-packet.md` "The current version is" line. The test does not pin the exact number. |
| `utils.status_checks._triage_lines` / `findings.ledger.render_deterministic_review_block` | Render the `lite` line, plus "Approval is left to a human." in the check summary. Neither says "no LLM review ran" for `lite`. |

## Coverage map

| Contract | Unit | Integration | End to end |
| --- | --- | --- | --- |
| Lite settings: defaults, aliases, cap bounds, unknown keys | `tests/classify/test_triage_lite.py` (settings section) | — | — |
| `commentOnly` is a valid `skipLlm` name | `test_triage_lite.py::test_comment_only_is_a_recognizer_name_skip_llm_accepts` | — | — |
| Tier vocabulary, `token_cap`, record lines | `test_triage_lite.py` (tier vocabulary section) | — | — |
| Case (a): matched but not opted in → `lite`; `full` when lite is off | `test_triage_lite.py` (parametrized over all five recognizers) | `tests/review/test_fast_path_lite_gate.py::test_an_unopted_recognizer_match_is_lite_from_the_operators_config` | `test_fast_path_lite_gate.py::test_a_lite_run_never_starts_the_agent_and_never_approves` |
| Case (b): unverified pin bump → `lite` | `test_triage_lite.py::test_an_opted_in_pin_bump_whose_checks_have_not_passed_is_lite` | `test_fast_path_lite_gate.py::test_an_unverified_pin_bump_is_lite_through_the_gate` | — |
| `lite` never takes a diff away from `skip` | `test_triage_lite.py::test_an_opted_in_recognizer_still_skips_when_lite_is_enabled`, `test_a_verified_pin_bump_still_skips_when_lite_is_enabled` | `test_fast_path_lite_gate.py::test_the_gate_never_calls_the_driver_for_a_skip` | — |
| Everything else is `full` (mixed, code, empty, fast path off) | `test_triage_lite.py` (everything-else section) | — | — |
| Base-side only; a read failure is `full` | — | `test_fast_path_lite_gate.py::test_lite_is_never_chosen_from_config_that_is_not_the_operators`, `test_a_read_failure_is_full_not_lite` | `test_fast_path_lite_gate.py::test_head_side_config_cannot_select_the_lite_tier` |
| `commentOnly` positives (every listed suffix, indentation, additions, later hunks) | `tests/classify/test_comment_only.py` (recognised section) | — | — |
| Lexer: escapes, char literals, `/*` inside a string, closed blocks | `test_comment_only.py` (recognised section) | — | — |
| Lexer refusals: string continuation, inside a block, unclosed block | `test_comment_only.py` (refused section) | — | — |
| Backtick / `r#"` / `R"` / `@"` file refusal | `test_comment_only.py::test_a_file_with_a_backtick_or_raw_string_marker_is_refused` | — | — |
| Code beside a comment, trailing comments, comment to code, missing or disagreeing head text | `test_comment_only.py` (refused section) | — | — |
| Languages off the list (Python, YAML, Markdown, shell, Makefile, TOML, INI, CSS, PHP), both `//` and `#` | `test_comment_only.py::test_a_language_off_the_list_is_never_comment_only` | — | — |
| Mixed diffs | `test_comment_only.py` (mixed-diff tests) | — | — |
| `commentOnly` wired into `triage_diff` and the head-text read | `test_comment_only.py` (wiring section) | `test_fast_path_lite_gate.py::test_a_comment_only_edit_reads_the_head_text_and_skips_when_opted_in` | — |
| Driver: one POST, URL, auth header, `max_tokens`, no stream, no tools, system message | `tests/agents/test_lite_review.py` (happy-path section) | — | — |
| Driver: the whole diff is inlined, untruncated | `test_lite_review.py::test_the_whole_diff_is_inlined_in_the_prompt_untruncated` | — | — |
| Cap before the call: downgrade, reason text, bytes not chars, output reservation | `test_lite_review.py` (cap section; the transport fails the test if it is reached) | — | `test_fast_path_lite_gate.py::test_a_diff_over_the_cap_is_downgraded_to_the_full_review` |
| Missing credential / unregistered provider → downgrade before any call | `test_lite_review.py` (credentials section) | — | — |
| The credential never appears in the outcome | `test_lite_review.py::test_the_credential_never_appears_in_the_outcome` | — | — |
| Usage: `usage.total_tokens`, estimate flagged, `cap_hit` boundary | `test_lite_review.py` (usage section) | — | `test_fast_path_lite_gate.py::test_a_lite_cap_hit_is_inconclusive` |
| Malformed output, more than 50 findings, unknown severity, HTTP errors, transport errors → `failed` | `test_lite_review.py` (malformed-output section) | — | `test_fast_path_lite_gate.py::test_a_failed_lite_call_is_inconclusive_never_a_silent_full_review` |
| No subprocess, no file written | `test_lite_review.py::test_no_subprocess_is_spawned_and_no_file_is_written` | — | `test_a_lite_run_never_starts_the_agent_and_never_approves` |
| `_triage_gate` returns `LiteAgentReview`, hands over the triaged diff | — | `test_fast_path_lite_gate.py` (`main._triage_gate` section) | — |
| Lite never approves; a failure is never softened | — | `test_fast_path_lite_gate.py::test_a_lite_run_with_a_success_decision_is_refused`, `test_a_lite_run_with_a_blocking_finding_still_fails` | `test_a_lite_run_never_starts_the_agent_and_never_approves` |
| Blocking finding → `failure` through the roster path | — | — | `test_fast_path_lite_gate.py::test_a_blocking_lite_finding_fails_the_check_through_the_roster_path` |
| Packet: `TriageSection` fields, cap and usage recorded, schema version, doc rows | `test_fast_path_lite_gate.py` (packet section) | `test_the_packet_carries_the_cap_from_the_lite_decision` | `test_a_lite_run_records_the_cap_and_the_usage_on_the_packet` |
| Check summary and review record render the lite line | `test_fast_path_lite_gate.py` (check-summary and review-record section) | — | `test_a_lite_run_never_starts_the_agent_and_never_approves` |

## Live gate

None. The driver is exercised only through `httpx.MockTransport`; a run against a real
provider is an operator step, not part of `make test`.

## Amendments

None yet.
