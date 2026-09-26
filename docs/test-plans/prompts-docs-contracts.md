# Prompts and docs contracts — test plan (PD1)

Scope: the RED suite for the prompts/docs-contracts wave plan, authored in the
`mc-docs` worktree on branch `wave/prompts-docs-contracts`. Owner of `tests/`
and this file: `test-creator`. Implementation waves PD2–PD4 turn the suite
green; PD5 Final verifies. Trace run.id:
`5a943cac-1d5e-4ec1-afa3-b679c291e9d8`.

Wave plan: `.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`.
Recon: `.ignorelocal/waves/44-pd0-recon.md`.

**Authoring contract.** Tests pin the *invariant*, not the prose (the plan's
thesis): every tool name a prompt uses is registered, every finding field it
requests exists, no budget number is baked in, docs name the code's real keys,
links resolve on the renderer that matters. Assertions are plain — **no
non-strict `xfail` markers** are used (repo precedent:
`tests/analyzers/test_bandit_parse_467.py`). `xfail_strict = true` in
`pyproject.toml` would turn a marker into `XPASS(strict)` failure once PD2–PD4
land, and the task requires RED assertions, not xfail records. The suite
collects, lints and typechecks clean; the assertions fail until the behaviour
exists.

## Contract matrix

| Contract | Decision | Layer | Test node(s) | Status |
| --- | --- | --- | --- | --- |
| Every `${t("x")}` in a production template names a registered tool | PD-D3 | Unit | `tests/prompts/test_prompt_tool_names.py::test_source_tool_refs_are_registered[Review\|IncrementalReview\|Plan]` | ✅ pass |
| No registered tool name appears bare-backticked in a rendered production prompt | C16 / PD-D3 | Unit | `…::test_no_registered_tool_name_is_bare_backticked[Review\|IncrementalReview]` | ✅ pass |
| `PR_SUMMARY_FORMAT` carries no bare registered tool name | C16 / PD-D3 | Unit | `…::test_pr_summary_format_has_no_bare_registered_tool_names` | ✅ pass |
| `classify_change` / `route_lenses` / `selected_lens_ids` / `load_lens_catalog` absent from every rendered production prompt | C2 / PD-D1 | Unit | `…::test_forbidden_names_absent_from_rendered_prompt[Review]` (others green) | ✅ pass |
| No prompt asks for a `collateral` field or list | C3 / PD-D2 | Unit | `tests/prompts/test_prompt_finding_schema.py::test_no_prompt_asks_for_a_collateral_field_or_list` | ✅ pass |
| The body-only **Also update:** instruction remains | C3 / PD-D2 | Unit | `…::test_also_update_body_instruction_remains` | ✅ pass |
| `AgentFinding` still rejects a `collateral` key (read-only pin on plan 39) | PD-D2 | Unit | `…::test_agent_finding_still_forbids_a_collateral_key` | ✅ pass |
| No digit follows "budget cap" in any production prompt | N14 / PD-D4 | Unit | `tests/prompts/test_prompt_budget_text.py::test_no_digit_follows_the_budget_cap_phrase` | ✅ pass |
| `inline_budget=5` renders `5`; the value is the only render delta | N14 / PD-D4 | Unit | `…::test_inline_budget_value_is_interpolated` | ✅ pass |
| `inline_budget=None` renders `analyzers.inlineBudget`, no number, no `${` | PD-D4 | Unit | `…::test_none_renders_the_key_name_and_no_marker_or_number` | ✅ pass |
| No rendered prompt leaves a `${...}` marker (mirrors `tests/test_modes.py`) | PD-D4 | Unit | `…::test_default_render_has_no_leftover_marker` | ✅ pass |
| The verifier-cap sentence names `review.verificationBudget` and `review.roundBudgets` | C8 / PD-D5 | Unit | `…::test_verifier_cap_names_the_config_keys` | ✅ pass |
| No prompt mentions a diff-coverage nudge | C8 / PD-D6 | Unit | `…::test_no_prompt_mentions_a_diff_coverage_nudge` | ✅ pass |
| No prompt mentions a Fix button | D8 / PD-D11 | Unit | `…::test_no_prompt_mentions_a_fix_button` | ✅ pass |
| A run's recorded prompt version names the prompt it actually rendered | #899 | Unit | `tests/prompts/test_prompt_budget_text.py::test_distinct_configured_budgets_produce_distinct_versions`, `…::test_version_hashes_the_rendered_prompt_body`, `…::test_default_render_version_matches_prompt_version_for_baseline` | ✅ pass |
| `inlineBudget: 0` resolves to `0`, not the default | #899 | Unit | `tests/analyzers/test_budget.py::test_resolve_inline_budget_honours_an_explicit_zero` | ✅ pass |
| Pre-pass and tool analyzer-run keys match at `inlineBudget: 0` | #899 | Unit | `tests/review/test_analyzer_prepass_reuse.py::test_prepass_and_tool_keys_agree_at_zero_inline_budget` | ✅ pass |
| `inlineBudget: 0` puts every finding in overflow | #899 | Unit | `tests/analyzers/test_budget.py::test_zero_budget_places_every_finding_in_overflow` | ✅ pass |
| The rendered `Review` prompt shows `0` at `inlineBudget: 0` | #899 | Unit | `tests/prompts/test_prompt_budget_text.py::test_zero_inline_budget_renders_the_zero_slot` | ✅ pass |
| Doctrine names the real verifier-budget keys | N20 / C8 / PD-D5 | Functional (doc) | `tests/docs/test_review_doctrine_contracts.py::test_verification_section_names_the_real_budget_keys` | ✅ pass |
| Doctrine forbids the inline-budget claim; naming the key is allowed only if its sentence decouples it | N20 / PD-D5 | Functional (doc) | `…::test_verification_section_does_not_claim_the_inline_budget_caps_it` | ✅ pass |
| Doctrine Python floor agrees with `pyproject.toml` `requires-python` | C13 / PD3.2 | Functional (doc) | `…::test_python_floor_agrees_with_pyproject` | ✅ pass |
| `action.yml` `push` description states review-only refusal | C7 / PD-D7 | Functional (doc) | `tests/docs/test_review_only_docs.py::test_action_yml_push_description_states_review_only_refusal` | ❌ RED |
| Generated `docs/action-reference.md` `push` row states review-only refusal | C7 / PD-D7 | Functional (doc) | `…::test_action_reference_push_row_states_review_only_refusal` | ❌ RED |
| `REVIEW-CHECKS.md` §9 does not present address-reviews as production | C7 / PD-D7 | Functional (doc) | `…::test_review_checks_section_9_does_not_present_address_reviews_as_production` | ❌ RED |
| GitHub slug rules (no space collapsing; `{#id}` is not an anchor) | C15 / PD-D9 | Unit | `tests/docs/test_markdown_links.py::test_slug_rules_match_github`, `…::test_explicit_anchors_are_honoured_and_brace_ids_are_not` | ✅ pass |
| Every in-scope markdown link resolves (code-aware) | C15 / C20 / PD-D9 | Functional (repo) | `…::test_no_broken_markdown_links_in_scope` (26 breaks) | ❌ RED |
| No in-scope link enters the gitignored `.ignorelocal/` tree | C15 / PD-D9 | Functional (repo) | `…::test_no_in_scope_link_enters_the_gitignored_wave_directory` | ✅ pass |
| Named green anchors stay green | C15 | Functional (repo) | `…::test_named_green_links_resolve[…]` ×6 | ✅ pass |
| PD4 post-fix targets resolve | C15 / C20 | Functional (repo) | `…::test_pd4_fix_targets_resolve[…]` ×11 (9 green; 2 glossary anchors RED until PD4.3) | ❌ RED |
| Operator/document split partitions every `src/` name | C14 / PD-D8 | Unit | `tests/docs/test_operator_env_vars.py::test_document_and_never_document_partition_src_names` | ✅ pass |
| `docs/cli.md` gains an `## Environment variables` section | C14 / PD-D8 | Functional (doc) | `…::test_cli_docs_gain_an_environment_variables_section` | ❌ RED |
| Every document-list knob appears in that section | C14 / PD-D8 | Functional (doc) | `…::test_environment_section_documents_every_operator_knob` | ❌ RED |
| No never-document name appears in that section | C14 / PD-D8 | Functional (doc) | `…::test_environment_section_lists_no_internal_or_control_name` | ❌ RED |

## PD2 reconciliation (2026-09-26)

PD2.1–PD2.6a turned the prompt-half contracts green; PD2.7 refreshed the three
snapshot fixtures and cleared the one out-of-scope failure PD2 surfaced. The
PD2 rows in the matrix above are now ✅ pass (C2, C3, C16, N14, C8 prompt half,
D8 prompt text); the PD3/PD4 doc rows stay RED by design.

- **Scoped run:** `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/prompts
  tests/modes tests/test_modes.py tests/tracing/test_mode_prompt_attrs.py
  tests/review -q` → **336 passed**; `uv run ruff check tests/` and
  `uv run ruff format --check tests/` clean.

### Snapshot refresh (PD-D12)

Regenerated from the live source of truth, not hand-edited bytes:

- `tests/prompts/fixtures/review_template_vp4_1.txt` ← `Review.TEMPLATE`
- `tests/prompts/fixtures/incremental_review_template_vp4_1.txt` ←
  `IncrementalReview.TEMPLATE`
- `tests/_fixtures/pre_split_prompts.json` ← `compute_modes("opencode")` renders,
  encoded the existing way (`json.dumps(..., indent=2, ensure_ascii=False) + "\n"`).

**Hunk attribution.** Every hunk in the two raw-template fixture diffs maps to a
PD2.1–PD2.6a edit:

| Fixture | Hunk group | PD2 item |
| --- | --- | --- |
| Review | `when \`checkout_pr\` returns` → `${t("checkout_pr")}` (shared splice) | PD2.3 / C16 |
| Review | `analyzer_findings` → `${t("analyzer_findings")}`; `budget cap (8)` → `budget cap — ${INLINE_BUDGET}` | PD2.3 / C16, PD2.4 / N14 |
| Review | flaky sentence → `failure` / `unattributed` wording; `${t("list_check_runs")}` | PD2.6a, PD2.3 / C16 |
| Review | `Consult … (mergecraft lens list / load_lens_catalog)` → `The registry-backed **lens catalog** is the menu rendered below` | PD2.1 / C2 |
| Review | classifier-routing paragraph deleted | PD2.1 / C2 |
| Review | finding's `collateral` list → `as an **Also update:** bullet list` | PD2.2 / C3 |
| Review | verifier cap → `review.verificationBudget` … `review.roundBudgets` | PD2.5 / C8 |
| Review | `report_progress` / `create_issue_comment` → `${t(...)}` | PD2.3 / C16 |
| Review | Fix-button rationale → `verdict` lever | PD2.6 / D8 |
| IncrementalReview | `checkout_pr` / `analyzer_findings` / `list_check_runs` interpolation + flaky wording | PD2.3 / C16, PD2.6a |
| IncrementalReview | finding's `collateral` list → `Also update:` | PD2.2 / C3 |
| IncrementalReview | `create_issue_comment` → `${t(...)}` | PD2.3 / C16 |
| IncrementalReview | Fix-button rationale → `verdict` lever | PD2.6 / D8 |
| IncrementalReview | diff-coverage-nudge line deleted | PD2.5 / C8 |

**`pre_split_prompts.json` — one reported coalescence.** The file stores
*rendered* prompts, so its `Review.prompt` and `IncrementalReview.prompt` lines
carry all of the rendered PD2 changes above **and** the terminal-window rewrite
from PR #619 (`96cb4042`: the `approved` / `comments` → `verdict` / `summary` /
`findings` submit step and callout tiers). The JSON was last refreshed at
`813352a9` (2026-08-29); `96cb4042` refreshed the two raw fixtures but **not**
the JSON, and the `_outside_terminal` carve-out in
`test_mode_prompt_text_is_byte_identical_after_split` hid that staleness. A live
refresh therefore pulls the pre-existing #619 delta in alongside the PD2 edits.
It is a latency correction, **not** drift introduced by PD2, and it lies wholly
inside that test's terminal-window carve-out. Only the `Review` and
`IncrementalReview` `prompt` fields differ; both `description` fields and the
entire `Plan` entry are byte-identical.

### Offline-chain assertion correction

`tests/review/test_offline_model_chain.py::test_offline_real_resolver_cross_harness_and_credential_status`
compared against `compute_modes("claude"|"codex", signed_commits=False)` while
`review/offline_agent.py` now renders
`inline_budget=settings.analyzers.inline_budget` (PD2.4 / PD-D4), so the
expected render no longer matched. The assertions now build both expectations
from `dispatch["settings"].analyzers.inline_budget` — the same settings object
the production path loads — and still assert full mode-list equality per
harness, not a name-only comparison. Rationale also recorded in the pushback
table below.

### Version attribution pin (#899)

`Mode.version` originally hashed the `inline_budget=None` baseline rather than
the rendered body, so two runs configured with different inline budgets recorded
the *same* version while the reviewer received different prompt text — breaking a
verdict's attribution to the prompt that produced it in the evidence packet and
tracing. The fix (`version=compute_prompt_version(prompt)`) is pinned by three
tests in `tests/prompts/test_prompt_budget_text.py`:

- `test_distinct_configured_budgets_produce_distinct_versions` — derives the
  marker-bearing modes by scanning each mode `TEMPLATE` for `${INLINE_BUDGET}`
  (`Review` bears it; `IncrementalReview` and `Plan` do not), asserts a
  marker-bearing mode's version is distinct across the default / `5` / `7`, and
  that a marker-free mode's version is unchanged.
- `test_version_hashes_the_rendered_prompt_body` — per `compute_prompt_version`'s
  docstring, pins `mode.version == compute_prompt_version(mode.prompt)` so the
  version is a function of the body, not a separately tracked field.
- `test_default_render_version_matches_prompt_version_for_baseline` — the
  no-budget render still equals `prompt_version_for(name)` for every built-in, so
  the fix does not move the default version a caller records.

Falsified by temporarily reverting the argument to `base_prompt`: the first two
fail (a marker-bearing mode's versions collapse to one), the baseline test stays
green. Restored byte-identical; this test owns no `src/` change.

### Zero-budget pins (#899)

`analyzers.inlineBudget: 0` is a supported zero-slot cap: every finding goes to an
overflow lane and none renders inline. It was resolved falsily to the default `8`
by the offline analyzer pre-pass (`0 or default`), so at `0` the pre-pass recorded
`state.key` with budget `8` while `mcp/analyzers.py` built the tool's
`request_key` with `0`; `prior_key.matches(request_key)` was then False and the
pre-pass was silently thrown away. The shared `resolve_inline_budget(settings)`
now honours an explicit `0`, so the prompt, the pre-pass and the tool describe one
placement contract. Pinned by four tests:

- `test_resolve_inline_budget_honours_an_explicit_zero`
  (`tests/analyzers/test_budget.py`) — `inlineBudget=0` → `0`, default/unset →
  `default_inline_budget()`, and the falsey `0 or default` result differs from the
  resolver's.
- `test_prepass_and_tool_keys_agree_at_zero_inline_budget`
  (`tests/review/test_analyzer_prepass_reuse.py`) — builds one `analyzer_run_key`
  input set both ways (`resolve_inline_budget(settings)` for the pre-pass vs
  `settings.inline_budget` for the tool), asserts `prepass_key.matches(request_key)`
  at `0`, and asserts the falsey `0 or default` key would **not** match.
- `test_zero_budget_places_every_finding_in_overflow`
  (`tests/analyzers/test_budget.py`) — `place_findings(..., inline_budget=0)`
  leaves `placement.inline` empty; every analyzer finding is mechanical, every
  agent finding is deferred, and the short-id map covers only overflow rows.
- `test_zero_inline_budget_renders_the_zero_slot`
  (`tests/prompts/test_prompt_budget_text.py`) — the rendered `Review` prompt shows
  `budget cap — 0`; the `None` render (key name, no number) stays pinned by
  `test_none_renders_the_key_name_and_no_marker_or_number`.

Falsified by temporarily reverting `resolve_inline_budget` to
`settings.inline_budget or default_inline_budget()`: the resolver test and the
key-match test fail (`assert 8 == 0`); restored byte-identical.

## C15 / C20 — renderer-aware link check (PD-D9)

`tests/docs/test_markdown_links.py` implements GitHub's heading slug rules:
lowercase; keep only word characters, underscores, hyphens and spaces; each
space becomes a hyphen **without collapsing** (so `Example 1 — auto review every
PR` → `example-1--auto-review-every-pr`). Explicit `<span id>`, `<a id>` and
`<a name>` are anchors; `{#id}` is **not** (a `### Trust tier {#trust-tier}`
heading slugs to `trust-tier-trust-tier`). Scope is `docs/**/*.md`, `README.md`,
`REVIEW-CHECKS.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`;
`CHANGELOG.md` and generated `docs/action-reference.md` are excluded. Relative
targets resolve against the containing file's directory; a directory target is
valid.

**Renderer-faithful extraction (PD4 escalation, 2026-09-26).** The scan blanks
fenced code blocks (``` / `~~~`) and inline code spans before extracting links and
explicit anchors, because GitHub renders neither as a link or an anchor. Heading
slugs keep their inline-code *content* (``## The `push` input`` → `the-push-input`)
but a `#` line inside a fence is not a heading. This removed the four false
positives below; `test_slug_rules_match_github` and
`test_explicit_anchors_are_honoured_and_brace_ids_are_not` stay green.

- **Comprehensive red:** `test_no_broken_markdown_links_in_scope` reports **26**
  breaks (corrected, code-aware): **17** glossary `{#id}` misses
  (`docs/trust-policy.md:276`; `README.md` ×16), **5** `../../` links,
  **1** archive link, and **3** remainder. The PD-D9 narrowing fork did **not**
  trigger (26 ≪ ~40).
- **PD4 post-fix fix list (11):** the five `../../` targets now `../…`
  (`docs/trust-policy.md` ×4: `trust_policy.py`, `trust.py`, the approve
  workflow, `.mergecraft/config.yaml`; `docs/workflows.md` ×1);
  `docs/dev/changelog-archive.md` → `../findings-carryover.md`; two glossary
  `#trust-tier` anchors (`README.md`, `docs/trust-policy.md`); the two
  `config-failure-policy.md#mcp-git-tool--reviewer-surface-enforcement-257`
  anchors; and `docs/agent-roster.md` →
  `authentication.md#quick-start--init--auth--review`. Nine resolve now; the two
  glossary anchors stay RED until PD4.3. PD4.1–PD4.4 green them.
- **The two originally-named red cases dropped as false positives:**
  `docs/test-plans/open-issues-sweep-2026-08-22b-gd.md`'s
  `[Agent skill](skills/mergecraft/SKILL.md)` is quoted **in inline code**, so
  GitHub renders no link; and `docs/test-plans/audit-r2-p1-review-integrity.md`'s
  `.ignorelocal/…` link is de-linked (plain code span) — it never resolved in CI.
  They are replaced by the `.ignorelocal/` guard test, which is the real
  invariant.
- **Named green cases (6):** `#how-it-works`, `#for-agents`, `#security-model`,
  `SECURITY.md#agent-credential-broker-codex-553`,
  `docs/trust-policy.md#agent-credential-broker-553`,
  `README.md#example-1--auto-review-every-pr`.

### PD4 escalation — the self-contradictory red list (2026-09-26)

**Defect.** Six of the thirteen original `_RED_LINKS` entries asserted that a
*pre-fix broken* target resolves, which no doc edit can satisfy: the four
`../../src/…` / `../../.github/…` / `../../.mergecraft/…` strings (PD4 rewrites
the **doc** to `../…`, so the post-fix string is `../…`, never `../../…`), the
`docs/dev/changelog-archive.md` → `docs/findings-carryover.md` string (PD4 writes
`../findings-carryover.md`), and two anchor strings whose slugs cannot exist
(`…-257--d7`; `#quick-start-init--auth--review`). Three further entries were
false positives from matching links inside inline code, and one targeted a
gitignored path.

**Fixes.** (1) Renderer-faithful extraction (above). (2) `_RED_LINKS` replaced by
`_PD4_FIX_LINKS` / `test_pd4_fix_targets_resolve` — the **post-fix** target list,
so each case proves the fix resolves. (3) The `.ignorelocal/` de-link in
`docs/test-plans/audit-r2-p1-review-integrity.md` plus the new
`test_no_in_scope_link_enters_the_gitignored_wave_directory` guard.

**Deviation from the escalation's fix list (recorded).** The escalation gave the
`docs/agent-roster.md` post-fix anchor as `authentication.md#quick-start-init-auth-review`.
That slug does not exist: the heading `## Quick start — init → auth → review`
strips **both** the em dash and the arrow, leaving the double hyphen. Verified
against `github-slugger@2.0.0`:

```text
"Quick start — init → auth → review"              => "quick-start--init--auth--review"
"MCP git tool — reviewer-surface enforcement (#257)" => "mcp-git-tool--reviewer-surface-enforcement-257"
"Example 1 — auto-review every PR"                => "example-1--auto-review-every-pr"
```

The test therefore pins the true slug `authentication.md#quick-start--init--auth--review`
(same no-collapse rule as the green `example-1--auto-review-every-pr` case).
Encoding the escalation's string would have recreated the exact defect.


## C14 / PD-D8 — the two lists

The two lists are the contract, encoded as `DOCUMENT` and `NEVER_DOCUMENT` in
`tests/docs/test_operator_env_vars.py`. They partition the **103** distinct
`MERGECRAFT_*` names `src/` reads (PD0 recon), asserted by
`test_document_and_never_document_partition_src_names`.
`DISABLE_SECURITY_INSTRUCTIONS` is gone from `src/` and is in neither list.

### Document (31) — added to `docs/cli.md` §Environment variables

Agent/model selection: `MERGECRAFT_AGENT`, `MERGECRAFT_MODEL`.
Timeouts: `MERGECRAFT_AGENT_TIMEOUT`, `MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S`,
`MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S`, `MERGECRAFT_RUN_TIMEOUT_S`.
Budgets: `MERGECRAFT_COST_BUDGET_USD`, `MERGECRAFT_LATENCY_BUDGET_MS`,
`MERGECRAFT_TOKEN_BUDGET`, `MERGECRAFT_TOOL_CALL_BUDGET`, `MERGECRAFT_CACHE_MAX_BYTES`,
`MERGECRAFT_MAX_DIFF_LINES`.
Dirs/toggles: `MERGECRAFT_CACHE_DIR`, `MERGECRAFT_TRACE_DIR`,
`MERGECRAFT_TEMP_DIR`, `MERGECRAFT_TEMP_PARENT`, `MERGECRAFT_EVIDENCE_DIR`,
`MERGECRAFT_KEEP_TMP`, `MERGECRAFT_CONFIG`, `MERGECRAFT_ENV`.
Logging: `MERGECRAFT_LOG_LEVEL`, `MERGECRAFT_LOG_FORMAT`.
Tracing targets: `MERGECRAFT_TRACING`, `MERGECRAFT_TRACING_TO`,
`MERGECRAFT_TRACING_PROJECT`, `MERGECRAFT_TRACING_REGION`,
`MERGECRAFT_TRACING_CONTENT`, `MERGECRAFT_OTEL_ENDPOINT`.
Networking/local: `MERGECRAFT_EGRESS_DNS_RESOLVERS`, `MERGECRAFT_NONINTERACTIVE`,
`MERGECRAFT_CDP_URL`.

`CDP_URL`, `CONFIG`, `ENV` and `EVIDENCE_DIR` are the judgment calls: each is a
URL/dir/path an operator legitimately sets for a local run. Everything genuinely
ambiguous was pushed to never-document instead.

### Never-document (72) — categories and reasons

- **Secrets:** `MERGECRAFT_MCP_TOKEN`, `MERGECRAFT_WEBHOOK_SECRET`,
  `MERGECRAFT_LOGFIRE_TOKEN`, `MERGECRAFT_CODEX_BROKER_TOKEN`,
  `MERGECRAFT_APP_PRIVATE_KEY`, `MERGECRAFT_APP_ID`, `MERGECRAFT_MCP_BEARER`,
  `MERGECRAFT_CUSTOM_PROVIDER_API_KEY*`, `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL*`,
  `MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS*`, `MERGECRAFT_CUSTOM_PROVIDER_`.
- **Internal IPC / wiring:** `MERGECRAFT_EGRESS_BRIDGE_IN_NS`,
  `MERGECRAFT_AGENT_PROTOCOL`, `MERGECRAFT_AGENT_ID`, `MERGECRAFT_PAYLOAD_ENV_FD`,
  `MERGECRAFT_BOOTSTRAP_*`, `MERGECRAFT_MCP_NAME`, `MERGECRAFT_MCP_PORT`,
  `MERGECRAFT_VERIFIER_MCP_NAME`, `MERGECRAFT_API_URL`,
  `MERGECRAFT_CODEX_HOME_PARENT`, `MERGECRAFT_ANALYZERS`,
  `MERGECRAFT_AUDIT_ROOT`, `MERGECRAFT_AUDIT_ROOT_ENV` (`AUDIT_ROOT_ENV` is a
  Python constant, not an env-var name), `MERGECRAFT_PROFILE`.
- **Test seams:** `MERGECRAFT_PROBE_TEST_DOUBLE`, `MERGECRAFT_PROBE_ALLOW_SUDO`,
  `MERGECRAFT_LIVE_E2E`, `MERGECRAFT_LIVE_PROVIDER`, `MERGECRAFT_EXAMPLE_*`,
  `MERGECRAFT_FORCE_INTERACTIVE`, `MERGECRAFT_PERMANENT_CURRENT_DECISION`,
  `MERGECRAFT_PROVIDER_EXTRA_OPTIONS`.
- **Generated values:** `MERGECRAFT_RUN_ID`, `MERGECRAFT_BUILD_COMMIT`,
  `MERGECRAFT_ACTION_SHA`, `MERGECRAFT_TRACE_ID`,
  `MERGECRAFT_TRACE_SESSION_ID`, `MERGECRAFT_REVIEW_ID`,
  `MERGECRAFT_REVIEW_CORRELATION_KEY`, `MERGECRAFT_INSTALL_REF`,
  `MERGECRAFT_UV_INSTALL_PACKAGE`, `MERGECRAFT_GIT_ORIGIN`,
  `MERGECRAFT_GIT_URL`, `MERGECRAFT_CI_WAIT_STATE`,
  `MERGECRAFT_CI_FAILED_COUNT`, `MERGECRAFT_BOT_NAME`, `MERGECRAFT_BOT_EMAIL`,
  `MERGECRAFT_MARKER`, `MERGECRAFT_REVIEW_MARKERS`, `MERGECRAFT_REVIEW_`.
- **Control-weakening:** `MERGECRAFT_ALLOW_ROOT`,
  `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL`, `MERGECRAFT_DISPOSABLE_LINUX`,
  `MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME`,
  `MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT`, `MERGECRAFT_CODEX_SANDBOX`.
- **Ambiguous, pushed to never-document (prefer-never rule):**
  `MERGECRAFT_AGENT_USER` (sandbox UID),
  `MERGECRAFT_AUTHORIZED_LINKED_REPOS` (xrepo authorization set by the
  harness/manifest), `MERGECRAFT_TRUST_TIER` (security tier override),
  `MERGECRAFT_REVIEWER_BOT_LOGIN` (derived identity). The executor may push back
  on any of these; the test owner amends the list.

### Deviation from the literal "any public doc" scope

The task asked that **no** never-document name appear in **any** public doc. That
is unsatisfiable without unauthorised deletions: PD-D7/PD-D8 remove no existing
text, and never-document names are already referenced legitimately elsewhere —
secrets in `docs/authentication.md` (`MERGECRAFT_LOGFIRE_TOKEN`,
`MERGECRAFT_CUSTOM_PROVIDER_API_KEY`, `MERGECRAFT_APP_PRIVATE_KEY`), the
control-weakening switches in `AGENTS.md`, the generated `MERGECRAFT_ACTION_SHA`
in `docs/workflows.md`, etc. The rule is therefore enforced where "public knobs"
are actually enumerated: the new `docs/cli.md` `## Environment variables`
section. `docs/cli.md`'s pre-existing line 50 (an `auth` command that stores a
key) is not a knob enumeration and is untouched. This is a deliberate, reported
narrowing — not a weakening of the C14/PD-D8 contract.

## PD-D8 pushback channels

If PD2–PD4 finds a test wrong (not the code), it reports to `test-creator`; no
other agent edits `tests/`. Any pushback is appended here with a one-line
rationale.

| Date | Test | Rationale |
| --- | --- | --- |
| 2026-09-26 | `tests/review/test_offline_model_chain.py::test_offline_real_resolver_cross_harness_and_credential_status` | `review/offline_agent.py` now renders `inline_budget=settings.analyzers.inline_budget` (PD2.4 / PD-D4); the expected modes are built with that same budget instead of relying on the omitted default. |
| 2026-09-26 | `tests/docs/test_review_doctrine_contracts.py::test_verification_section_does_not_claim_the_inline_budget_caps_it` | The PD1 guard banned the literal token `analyzers.inlineBudget`, which PD-D5/P-8 require the doctrine to **name**. The guard now forbids the *claim* and requires any sentence naming the key to decouple it (see "PD3 test refinement" below). |
| 2026-09-26 | `tests/docs/test_markdown_links.py` (`_PD4_FIX_LINKS` / code-aware scan / `.ignorelocal` guard) | PD4 escalation: 6 of 13 `_RED_LINKS` asserted pre-fix broken strings resolve (unsatisfiable); 3 were inline-code false positives; 1 targeted a gitignored path. Red list is now the post-fix target list, the scan is renderer-faithful, and the escalation's `quick-start-init-auth-review` slug is corrected to `quick-start--init--auth--review` (github-slugger 2.0.0). See "PD4 escalation" above. |

## PD3 test refinement — inline-budget guard (2026-09-26)

**What changed, and why.** The PD1 assertion `assert "analyzers.inlinebudget" not in
lowered` was over-broad. Locked decision **PD-D5** and plan item **PD3.1** require the
doctrine § *Verification covers every source* to state both that the verifier cap is
`review.verificationBudget` **and** that it is *independent of* `analyzers.inlineBudget` —
which means the section must be **able to name the inline-budget key** to say it governs
only inline placement. Banning the literal made the contract unsatisfiable as written; the
executor satisfied it by splitting the key across two code spans (`` `analyzers` ``
/ `` `inlineBudget` ``) merely to avoid the token — test-gaming, and worse prose (the plan's
**P-8**: name the real key, one shape one rule).

**The refined invariant.** The section may name the key; it must not present it as *the*
verification cap. The test now:

1. still asserts the legacy claim is absent — `"the cap is the inline budget"`;
2. still relies on the sibling test
   `test_verification_section_names_the_real_budget_keys` (names `review.verificationBudget`
   and `roundBudgets`);
3. for **every sentence** that names the key — matched case-insensitively in any markdown
   shape (`analyzers.inlineBudget`, `analyzers inlineBudget`, or the split
   `` `analyzers` `inlineBudget` ``) — requires that sentence to also contain one of
   `independent`, `placement`, or `governs only`.

The Python-floor test (`test_python_floor_agrees_with_pyproject`) is untouched, and no
`xfail` was added.

**Behaviour check (guard fires, not a hole).** A throwaway harness fed the helper five
sentences: the real split-token sentence and a restored-natural-key decoupled sentence did
**not** fire; `"The cap is the inline budget, i.e. `analyzers.inlineBudget`."`,
`"The `analyzers.inlineBudget` value is 8."`, and `"analyzers inlineBudget defaults to 8."`
all fired. The doctrine still carries the split-token workaround (the executor restores the
natural key afterwards), so the refined test passes against it.

- **Verification:** `MERGECRAFT_PYTEST_JOBS=0 uv run pytest
  tests/docs/test_review_doctrine_contracts.py -q` → **3 passed**;
  `uv run ruff check tests/docs/test_review_doctrine_contracts.py` → **All checks passed!**
