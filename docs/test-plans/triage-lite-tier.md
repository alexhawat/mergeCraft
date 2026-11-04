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
  recognised. `.js`, `.jsx` and `.tsx` are off the list (JSX, which plain `.js` files
  may hold, renders a `//` text child as page text), Rust is off the list (a
  lifetime's lone quote makes the quote check unsound), Go test files (`*_test.go`)
  are refused because an example's `// Output:` body is a test input, a Go file
  whose diff or head text says `DO NOT EDIT` (any case) is refused as generated, and
  `Package.swift` is refused by name. The recognised list is exactly `.ts .go .java
  .kt .c .h .cc .cpp .hpp .cs .swift`. Comment-only recognition proves no runtime
  change for these languages; comments can still carry tool directives, which the
  directive word list refuses on a best-effort basis (it now also holds `code`,
  `istanbul`, `nolintnextline`, `nolintbegin`, `nolintend`, `iwyu`, `jshint`, `noqa`
  and `coverage`, matched in any case). A Java file whose diff or head text holds
  a backslash followed by `u` (a unicode escape, translated before lexing) is refused,
  and so is a C-family file (`.c .h .cc .cpp .hpp`) holding `??` anywhere (a trigraph
  can splice the next line into a comment). A file is refused when it contains a backtick, a
  raw-string marker, a `/*` anywhere, a quote left open at the end of a line, `import
  "C"` in Go, or any character outside printable ASCII plus tab and newline (so
  `U+2028`, `U+2029`, a lone CR and NEL cannot end a line for the language but not for
  the lexer). Lines are split on `\n` only. A changed line must be `//`, one space and
  a purely alphabetic first word that is not a directive word (`fallthrough`, `Output`,
  `Unordered`, `NOSONAR`, `nolint`, `revive`, `golangci`, `pragma`, `build`, and the
  existing lint and type-checker words). A removal-only diff is refused because a
  removed line cannot be checked against the head text.
- A `lite` run publishes the deterministic run record as a `COMMENT` review that
  carries the call's summary and each finding's path, line and message. The record names
  the lite provider/model slug (for example `cheapo/tiny-1`), not the agent's provider. A failed
  completion check never says the run finished successfully. A blocker keeps the
  `mergecraft` check at `failure` even when the call also overran its cap (the run is
  still `inconclusive`).
- Head-side text for code files is read only when something can use it: `commentOnly`
  is in `skipLlm`, or `lite` is enabled.

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
| `main.publish_deterministic_record` | Called exactly once on a `lite` run, through the real publish phase. With no existing review it creates one `COMMENT` review through `GitHubScmAdapter.create_review`; the body contains the lite summary and, for each finding, its path, its line within a few characters after the path, and its message. |
| `fast_path.load_triage_inputs` (head text) | Code-suffix head files are fetched only when `commentOnly` is in `skipLlm` or `lite.enabled`; prose head files are fetched as before. Tested through `decide_fast_path`, so no new keyword is pinned. |
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
| Blocking finding → `failure` through the packet findings; roster record kept | — | — | `test_fast_path_lite_gate.py::test_a_blocking_lite_finding_fails_the_check_through_the_packet_findings`, `test_lite_findings_are_recorded_on_the_roster_under_agent_lite` |
| Packet: `TriageSection` fields, cap and usage recorded, schema version, doc rows | `test_fast_path_lite_gate.py` (packet section) | `test_the_packet_carries_the_cap_from_the_lite_decision` | `test_a_lite_run_records_the_cap_and_the_usage_on_the_packet` |
| Check summary and review record render the lite line | `test_fast_path_lite_gate.py` (check-summary and review-record section) | — | `test_a_lite_run_never_starts_the_agent_and_never_approves` |

### Hardening coverage

| Contract | Tests |
| --- | --- |
| Every probe attack refused (seven verified false positives plus the earlier refusals), verbatim fixtures | `tests/classify/test_comment_only.py::test_every_probe_attack_is_refused` |
| The probe's true positives still recognised | `test_comment_only.py::test_the_probe_true_positives_are_still_recognised`, `test_a_tab_indented_comment_is_still_recognised` |
| Removal-only diffs refused | `test_comment_only.py::test_a_removal_only_comment_diff_is_refused` |
| `\n`-only splitting and the printable-ASCII rule (U+2028, U+2029, lone CR, NEL, CRLF, non-ASCII comment or head text) | `test_comment_only.py` (`test_a_line_terminator_other_than_newline_*`, `test_the_unicode_line_separator_attack_file_is_refused`, `test_a_non_ascii_comment_is_refused`, `test_non_ascii_anywhere_in_the_head_text_refuses_the_file`, `test_a_crlf_file_is_refused`) |
| JSX/TSX off the list; `Package.swift` refused | `test_a_language_off_the_list_is_never_comment_only[*App.jsx/App.tsx]`, `test_package_swift_is_refused_by_name` |
| Any `/*` refuses; an open quote at end of line refuses; cgo refuses | `test_a_block_comment_opener_inside_a_string_still_refuses_the_file`, `test_a_closed_block_comment_anywhere_in_the_file_refuses_it`, `test_a_quote_left_open_at_the_end_of_a_line_refuses_the_file`, `test_a_cgo_file_is_refused` |
| Shape rule (prefix class) and directive word list (word class) | `test_a_comment_whose_first_token_is_not_a_plain_word_is_refused`, `test_a_comment_whose_first_word_is_a_directive_word_is_refused` |
| Unverifiable pin bump (no `requireChecks`, no trusted App, only `github-actions`) is `lite` | `tests/classify/test_triage_lite.py::test_an_unverifiable_opted_in_pin_bump_is_lite_when_enabled` |
| Java unicode escapes (`\u`, `\uu`) on any side, Rust off the list, C-family `??` refused; re-gate attacks verbatim | `test_comment_only.py::test_every_regate_attack_is_refused`, `test_a_java_unicode_escape_*`, `test_the_compiled_java_unicode_escape_fixture_is_refused`, `test_rust_is_not_on_the_recognised_suffix_list`, `test_a_c_family_file_containing_a_trigraph_marker_is_refused`, `test_the_compiled_trigraph_fixture_is_refused`, `test_a_trigraph_marker_only_on_the_removed_side_refuses_the_edit` |
| The trigraph rule is scoped to the C family (`??` in JavaScript still recognised) | `test_comment_only.py::test_nullish_coalescing_does_not_refuse_a_javascript_file` |
| The re-gate true positives stay recognised | `test_comment_only.py::test_the_regate_true_positives_are_still_recognised` |
| Diff-side ASCII check on a paired edit (removed line hides code behind U+2028, U+2029, lone CR or NEL) | `test_comment_only.py::test_a_paired_edit_whose_removed_line_hides_code_is_refused` |
| The suffix constant is exactly the closed list; REVIEW-CHECKS.md lists it exactly | `test_comment_only.py::test_the_recognised_suffix_list_is_exactly_the_closed_list`, `test_fast_path_lite_gate.py::test_review_checks_lists_exactly_the_recognised_comment_only_suffixes` |
| CHANGELOG `### Changed` mentions the record's `path:line` finding format | `test_fast_path_lite_gate.py::test_the_changelog_records_the_finding_line_format_under_changed` |
| The lite record names the provider/model slug | `test_fast_path_lite_gate.py::test_a_clean_lite_run_publishes_its_summary_as_a_comment_review` |
| Third-gate attacks refused verbatim (JSX in `.js`, Go example output, Go `DO NOT EDIT`, C# verbatim and Swift raw strings, JS HTML-like comment, `istanbul` / `NOLINTNEXTLINE` / `IWYU` pragmas, Java escaped backslash) | `test_comment_only.py::test_every_third_gate_attack_is_refused`, `test_the_compiled_jsx_fixture_in_a_js_file_is_refused`, `test_the_compiled_go_example_fixture_is_refused`, `test_the_compiled_go_generated_header_fixture_is_refused` |
| Third-gate true positives (Kotlin, Swift and C# interpolation, C digraphs, C macro continuation, Go embed, Kotlin `\u000a`) | `test_comment_only.py::test_the_third_gate_true_positives_are_still_recognised` |
| `.js` off the list, `.ts` on it | `test_a_plain_js_comment_edit_is_refused_while_ts_is_recognised`, `test_js_is_not_on_the_recognised_suffix_list` |
| `*_test.go` refused by name; `DO NOT EDIT` in Go head text or diff refused (any case) | `test_a_go_test_file_is_refused_by_name`, `test_a_go_file_whose_head_text_says_do_not_edit_is_refused`, `test_a_go_diff_whose_removed_line_says_do_not_edit_is_refused` |
| New directive words refused in lower, upper and title case | `test_the_new_directive_words_are_refused_in_any_case` |
| Each `.js` attack also runs as `.ts`, so its own rule (not the suffix) refuses it | `_with_ts_twins` rows (`*-as-ts`) in `test_every_probe_attack_is_refused` and `test_every_regate_attack_is_refused` |
| REVIEW-CHECKS.md names the excluded languages and why, and says comments can still carry tool directives | `test_fast_path_lite_gate.py::test_review_checks_names_the_excluded_languages_and_why`, `test_review_checks_says_comments_can_still_carry_tool_directives` |
| The API key never appears in a loguru line (success, HTTP 401, connect error) | `tests/agents/test_lite_review.py::test_the_api_key_never_appears_in_a_log_line` |
| Lite record published as a `COMMENT` review with summary and finding location/message | `tests/review/test_fast_path_lite_gate.py::test_a_clean_lite_run_publishes_its_summary_as_a_comment_review`, `test_a_blocking_lite_run_publishes_each_finding_location_and_message` |
| A failed completion check never says "finished successfully" | `test_fast_path_lite_gate.py::test_a_failed_completion_check_never_says_the_run_finished_successfully` |
| The check fails through the packet findings; the roster record is kept separately | `test_a_blocking_lite_finding_fails_the_check_through_the_packet_findings`, `test_lite_findings_are_recorded_on_the_roster_under_agent_lite` |
| Never-soften with compact and full finding rows | `test_a_lite_run_with_a_blocking_finding_still_fails[compact-lite-row/full-finding-row]` |
| Trusted tier (`trust.selfReview: full`) plus a Minor finding never approves | `test_a_trusted_lite_run_with_a_minor_finding_never_approves` |
| A blocker plus a cap overrun is `failure`, run `inconclusive` | `test_a_blocker_is_never_softened_by_a_cap_hit` |
| Code head text read only when `commentOnly` or `lite` can use it | `test_code_head_text_is_not_read_when_neither_comment_only_nor_lite_is_on`, `test_code_head_text_is_read_when_lite_is_enabled`, `test_code_head_text_is_read_when_comment_only_is_opted_in_without_lite`, `test_prose_head_text_is_still_read_without_comment_only_or_lite` |

## Live gate

None. The driver is exercised only through `httpx.MockTransport`; a run against a real
provider is an operator step, not part of `make test`.

## Amendments

- Verification found seven comment-only false positives (a legacy `// +build`
  constraint, the Swift tools-version line, a JSX text child, a regex literal hiding a
  block opener, a Go example `// Output:`, a GCC fallthrough marker, and a U+2028 line
  terminator). The recognizer contract was tightened to refuse on shape rather than
  enumerate directives. Three earlier positives now refuse by design: `/*` inside a
  string, a closed block comment elsewhere in the file, and the `.jsx` / `.tsx` suffixes.
  The removal-only comment edit, which an earlier probe counted as a positive, is now
  refused.
- The blocking-finding packet test now covers both the compact lite row and a full
  finding row, so the never-soften rule does not depend on the compact-row expansion.
- A second verification round found three more comment-only bypasses: Java unicode
  escapes (`// note \u000a doEvil();` compiles to a call), a Rust lifetime that
  mis-pairs the quote check, and a C trigraph `??/` that splices the next code line.
  Rust left the recognised list, so the earlier Rust char-literal positive is now a
  refusal and the Rust raw-string row was dropped from the marker table.
- A third verification round found JSX text in plain `.js` files, multi-line Go
  example `// Output:` bodies, Go generated-file headers and three more pragma words.
  `.js` left the recognised list, so tests that used a `.js` fixture as a true
  positive now use `.ts`. They are: `_comment_edit("src/app.js")` and every
  `src/app.js` / `src/other.js` positive and control in `test_comment_only.py`, the
  probe positive (now `plain-edit-now-in-ts`), the shape-rule controls, the
  line-terminator and paired-edit paths, the nullish-coalescing guard, the lite tier's
  comment fixture in `test_triage_lite.py`, and the comment-only gate fixtures in
  `test_fast_path_lite_gate.py`. Attack rows on `.js` stay verbatim and gain `.ts`
  twins.
