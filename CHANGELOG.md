# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `scripts/check_type_ignores.py` fails when a `type: ignore` or `cast(` in allowed `src/mergecraft/` lacks a one-line reason (#275); wired into `make lint`
- `scripts/check_xpass.py` fails when unexpected pytest xpasses remain on the allowed test tree (#276)
- xpass ratchet now runs as a `pytest_sessionfinish` conftest hook inside the coverage-gate pytest session — no standalone log file or extra CI step (#276)
- `MERGECRAFT_LIVE=1` opt-in gate for live provider tests (#278): `tests/conftest.py` centralizes skip policy via `pytest_collection_modifyitems`; `make test-integration-live` and the CI `integration-live` job export the flag so the suite stays fail-closed when secrets are absent
- `UnsupportedScmCapability` raised by `GitLabScmAdapter` now reports `"GitLab support is not available in this release"` instead of only the raw capability token; GitLab message is passed explicitly via `message=` so the generic format string stays clean (#279)
- docs: README requirements and `docs/distribution.md` Marketplace copy state that mergeCraft 0.1.0 is GitHub-only; GitLab support is planned via the `ScmProvider` abstraction (#279)
- docs: README SHA-pin advice now links to CONTRIBUTING.md verify one-liners (`cosign verify` / `gh attestation verify`); `docs/distribution.md` Marketplace gate requires image attestations to pass before listing, pointing at the existing `sign-attest` job (#280)
- SCM abstraction: `ScmProvider` protocol with `GitHubScmAdapter` (behaviour-preserving) and demand-gated `GitLabScmAdapter` that declares unsupported capabilities instead of emulating GitHub; core MCP tools and review publication route through `ToolContext.scm`
- Added: a test-only provider-harness fixture schema and strict matcher
  (`tests/support/provider_harness`) so deterministic review tests can name
  the exact provider interaction they expect. Not used in production.
- Added: provider-harness recording workflow and operator docs
  (`docs/dev/provider-harness.md`); opt-in sanitized capture under
  `.ignorelocal/provider-harness/records/`.
- Cross-repository intelligence indexes linked repos at pinned commits, contract surfaces (OpenAPI, GraphQL, protobuf, exports), cross-repo blast radius, reproducible citations, and ticket acceptance-criteria mapping under `mergecraft.xrepo` and `mergecraft.requirements`
- Repository context engine indexes repo maps, per-file symbol indexes (tree-sitter with generic fallback), provenance citations, and trust-gated instruction/skill discovery under `mergecraft.context`
- Call graph, change graph (changed symbol → dependents → tests → contracts), budget-aware dynamic expansion, targeted git blame, and `mergecraft context inspect` for provenance-backed context retrieval
- Feedback capture for findings (accepted / dismissed / disputed) keyed by fingerprint, with bounded negative-memory suppression, TTL/recency weighting, contradiction detection, and `mergecraft memory list|show|forget|export|import|feedback` lifecycle verbs (DG7)
- Policy-as-code package (`mergecraft.policy`) with schema-validated YAML rules, deterministic org/repo/path scoping, enforcement modes mapped onto the existing approval gate (D7), required-evidence inconclusive handling (D8), and bounded exceptions with expiry
- `mergecraft policy lint|test|explain` — validate policy rules, run should-trigger/should-not fixtures, and list effective rules with source layers
- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews
- Large-PR review engine (DG2): cluster changed paths by dependency and intent, build hierarchical diff context (map → summaries → raw hunks) with token-budget scope reduction that reserves verbatim hunks for high-risk regions, record disputed/waived/stale finding lifecycle states, and emit advisory-only PR split recommendations from independent change groups
- Finding precision pipeline (DG1): deduplicate agent/analyzer findings before publication, apply a code-defined severity rubric at the verifier seam, require structured causality on blocking findings, suppress pre-existing analyzer hits via baseline comparison, and classify generated/minified/vendored paths for review policy
- DG1 precision corpus gate (`evaluate_dg1_precision_corpus`) proving recall holds while corpus-confirmed precision improves over the pre-DG1 baseline
- PR utilities (DG8): standalone describe output (`mergecraft.pr.describe`), text-only changelog/docs/test suggestions (D11), deterministic TODO scan, classifier-derived effort bands, advisory label suggestions, and `/mergecraft review` comment routing with author-association and permission gating (`mergecraft.mcp.comment_router`)
- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy (D13)
- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win
- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache
- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets
- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default (D11)
- `mergecraft plan` previews model chain, toolset, analyzer detection, and token estimate without provider calls
- Run manifest fingerprints (model/CLI versions plus prompt, config, and policy hashes) for reproducible offline reviews
- `mergecraft review` machine contract: distinct process exit codes per `RunOutcome`, `--format text|json|jsonl|sarif`, and `--agent` JSONL streaming with an explicit `protocol_version`
- Added review-wide trace correlation: a `review.id` on every span across every process and agent of one logical review, plus a deterministic `review.correlation_key` (`sha256(repo|pr|head_sha)`) that groups re-reviews of the same commit; `trace_id` remains per agent run
- Added tracer baseline attributes (`mergecraft.run_id`, `mergecraft.version`, `mergecraft.trust_tier`, VCS and CI fields) merged into spans at close time, with explicit attributes taking precedence
- Added review-context env propagation into spawned agent CLI subprocesses, so subagent runs join the parent review's trace identity
- Added a content-capture policy for model payloads (`tracing.content`: `off` / `metadata` / `redacted` / `full`, default `redacted`; env `MERGECRAFT_TRACING_CONTENT`) gating whether LLM bodies may be emitted onto spans, with per-payload size counts and a sha256 of the original at every level above `off`
- Security: spans from untrusted sources are hard-capped at `metadata` content capture — prompt/completion bodies can never be shipped to a sink for an untrusted review, and the cap cannot be overridden by config or env
- Added model-parameter and payload capture on LLM spans (`gen_ai.request.*` / `gen_ai.response.*` / `gen_ai.usage.*`), recording both the requested and executed model so fallbacks are visible, with extended-thinking capture gated by the content policy and per-harness coverage documented (CLI harnesses have no payload visibility; the OpenCode HTTP path and stream consumer do)
- Added richer tool-call tracing: `gen_ai.tool.call.id` correlating request and response, per-call duration, and an MCP-vs-native origin distinction
- Added outcome spans: review-phase spans, per-agent run spans with MCP-stamped attribution (`MERGECRAFT_AGENT_ID`) so tool calls chain under their agent, fingerprint-keyed finding lifecycle spans, a verdict span with a derived disagreement flag, and eval-score spans that inherit the active `review.id`
- Added benchmark quality metrics: blocker precision scored separately from overall precision, semantic duplicate rate, unique accepted findings per lens, judge value (noise removed and recall lost), p50/p95 cost-latency summaries, and orchestrator kind as a scored dimension
- Added an adversarial eval corpus (`evals/cases/adversarial/`) proving the prompt-injection fence holds against hostile PR bodies, review comments, and commit messages, and that poisoned context can neither suppress real findings nor manufacture approvals
- Added `mergecraft eval gate` — a release regression gate comparing a candidate result set against baseline with a declared tolerance band, wired as a blocking job in the release workflow
- Added agent registry binding model, prompt, toolset and budget per role with `mergecraft agents list|show|set` and `make agents-check`
- Added registry-driven harness render for Claude, OpenCode, Codex, Gemini, and Cursor with per-agent models and declared Codex degradation in run metadata
- Added typed specialist handoff, model-diversity policy for verification, and ensemble or shadow dispatch modes on agent bindings
- Added change classifier and risk-based lens routing with recorded per-lens reasons in Review mode
- Promoted 20 themed review lenses from Review prose into registry entries with `mergecraft lens list|show|test`
- Added pluggable orchestrator with declarative pipeline file, trust gate for untrusted sources, and `mergecraft pipeline lint|show|explain`
- Added declared decision nodes for hybrid orchestration — typed triviality, lens selection, and finding disposition seams with pipeline-owned control flow
- Added: optional `harness` setting (`opencode` / `codex` / `claude` / `gemini` / `cursor`) to select the agent runtime independently of provider/model. Existing configs with the key unset keep today's inference
- Added: terminal-verdict protocol shadow mode (`gates.terminal_verdict`, default `shadow`) with a closed `VerdictDiagnostic` vocabulary; enforce still applies the fail-closed missing-verdict branch
- Added: server-side semantic validation of the terminal verdict — `request_changes` with no findings, `approve` over a verifier-confirmed blocker, and `approve` with a failing required deterministic check are all rejected and fail closed
- Added: `submit_review_verdict` — a typed MCP operation that records a review's terminal verdict
  (`approve` / `request_changes`), summary and structured findings. Unknown fields and invalid
  verdict values are rejected; an identical re-submission is idempotent, a conflicting one is an
  error. Not yet enforced — the run outcome is unchanged in this release
- `mergecraft tracing logfire wire-workflow` / `unwire-workflow` — surgical
  YAML mutation of `.github/workflows/*.yml` to wire (or strip) the four
  Logfire keys (`tracing: "true"`, `tracing-to: logfire`,
  `logfire-token: ${{ secrets.LOGFIRE_TOKEN }}`,
  `MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}`) on selected
  steps. Comment-preserving line-based mutator; refuses forks with
  similarly-named action names; supports both the multi-line
  (`- name: ...` / `  uses: alexhawat/mergeCraft@X`) and the inline
  (`- uses: alexhawat/mergeCraft@X`) step forms; creates a `with:` block
  when absent (README Example 1 has no `with:`); public API under
  `mergecraft.cli.tracing_logfire_wf_yaml.apply_logfire_wiring` /
  `remove_logfire_wiring` / `render_workflow_diff`
- `scripts/gen_reference_docs.py` regenerates README's `action.yml` input/output
  tables and CLI command table from the live sources (never a subprocess — it
  walks the live Typer `app` object) and splices them between HTML sentinel
  comments; `make reference-docs-check` (wired into `make ci-static`) fails the
  build on drift. Closes the audit in the issues-showcase-readiness wave plan
  (PR G2): the README table documented 9 of 24 real `action.yml` inputs and
  neither declared output anywhere

### Fixed

- `cli/auth`: authenticating a provider left the contributor unable to run the CLI locally — `mergecraft auth codex|claude|gemini|cursor|nous|tokenhub|minimax` persisted the captured credential only through `gh secret set`, so it landed in GitHub Actions secrets and nowhere the local runtime reads. All seven now take `--scope local|github|both` (default `github`, so a CI-only setup keeps today's behaviour exactly, including the hard failure when the secret write fails), and `--scope local` needs no `gh` auth and no network. `auth codex` captures `auth.json` before its isolated `CODEX_HOME` tempdir is deleted, and the pretty-printed multi-line payload `codex login` writes is compacted to one line and quoted, so the `.env` entry round-trips through both `dotenv` and `source .env` (#221)
- `cli/auth`: running `mergecraft auth … --scope local` from a subdirectory reported success while writing a nested `.env` that nothing reads — the local path fell back to `.env` in the current working directory; it is now anchored at the git repository root, and a run with no repository to anchor to fails with a pointer to `MERGECRAFT_ENV` instead of writing somewhere useless. `$MERGECRAFT_ENV` still wins when set (#221)
- `agents/codex`: every Codex review failed to start whenever a custom OpenAI-compatible provider was configured (`MERGECRAFT_CUSTOM_PROVIDER_*`) — the generated `config.toml` emitted the `default_permissions` profile name *after* the `[model_providers.*]` tables, so TOML scoped it into a provider block and Codex never saw the read-only review permission profile; the generated file now always emits every root scalar ahead of the first table header, whatever order the writer populated them in, so the same ordering also covers `sandbox_mode` on the non-profile path (#222)
- `agents/structured_handoff`: a specialist handoff whose `---typed-findings---` marker differed in casing from the documented lowercase spelling lost every finding it reported — the marker was detected case-insensitively but the text was then split on the exact-case literal, so the payload came back empty and `parse_specialist_handoff` raised `ValueError: … not valid JSON` instead of returning the findings; the split is now a case-insensitive regex search over the original text, which keeps the offsets valid even when the prose half contains non-ASCII characters that `casefold()` would lengthen (#261)
- `agents/ensemble`: when two ensemble models disagreed, `reconcile_ensemble` returned only the primary model's findings, so a real problem that only the secondary reviewer caught — up to and including a Critical the primary missed entirely — was silently discarded and survived nowhere but the judge brief; the disagreement path now merges both models' findings, deduplicated by `_finding_key`, keeping the primary's copy of a corroborated finding and the judge escalation unchanged (#262)
- `agents/ensemble`: the same defect reported at two different call sites in one file collapsed into a single finding when the two ensemble models' results were merged, so the second site never reached the reviewer — the deduplication key was the path and the finding body only; the line is now part of a finding's identity, and a row with no line keys on a value no line number can collide with (#262)
- `agents/_stream_consumer`: streaming runs on OpenAI-shaped providers (Nous, MiniMax, opencode Responses / Chat Completions, Codex) over-reported their prompt size — and therefore the run's token and cost accounting — by the whole cached-prompt count whenever prompt caching was active, because `prompt_tokens_details.cached_tokens` / `input_tokens_details.cached_tokens` are already *inside* the reported `input_tokens` but were added to it a second time; `to_usage()` now adds the cached count only when it came from Anthropic's disjoint `cache_read_input_tokens` counter, and still reports it as `cache_read_tokens` in both cases (#273)
- `agents/opencode`: reviews served over the opencode HTTP session path — every Nous and MiniMax run — over-reported their prompt size, and therefore the run's token and cost/budget accounting, by the whole cached-prompt count whenever prompt caching was active; this path re-implemented the cached-token scan inline and kept adding OpenAI-style `prompt_tokens_details.cached_tokens` / `input_tokens_details.cached_tokens` to an `input_tokens` that already contained them, so the fix landed in `_stream_consumer` only covered the streaming CLI drivers. It now shares `_resolve_cache_read`, adding the cached count only when it came from Anthropic's disjoint `cache_read_input_tokens` counter, and still reports it as `cache_read_tokens` in both cases (#273)
- `mcp/verdict`: a pull request carrying an analyzer-reported Critical or Major could be approved as long as the reviewing agent never dispatched a verifier for it — `validate_submission`'s approve branch only walked verifier-confirmed findings, so skipping verification was a route to approval. Approve is now rejected whenever any finding the run knows about is still of blocking severity after the causality policy has run, whether or not a verifier looked at it, and a finding the gate cannot grade blocks rather than being skipped. The reviewing agent reopens the approve path by verifying and then `drop`ping a refuted finding, or by `downgrade` to a non-blocking severity — both are applied before the gate reads the state, and a `drop` recorded in an earlier run counts too. Attribution is deliberately not a second condition: under the default `baseComparison: diff` no base run happens and every diff-scoped finding stays `introduced_by_pr: "unknown"`, so gating on `"true"` exempted ruff, mypy, bandit and semgrep from the gate entirely; where a base run did happen, a pre-existing finding is stamped `"false"` and the causality policy already downgrades it below the blocking threshold (#263)
- `mcp/verification`: a verifier `downgrade` that named no `new_severity` silently rewrote the finding to `Minor`, so a single such verdict retired any Critical the approve gate was holding; a downgrade is now rejected unless it names the severity it downgrades to, that severity must be one of the four in the taxonomy, and a downgrade landing on a still-blocking severity needs the same structured causality a `confirm` does (#263)
- `mcp/check_runs`: the `list_check_runs` tool called GitHub's check-*suites* endpoint and returned a `check_suites` payload, so a reviewing agent that asked which checks ran on a ref got only per-suite rollups — the individual run names, their per-run conclusions, and therefore the logs of the one job that actually failed were unreachable through this tool; it now calls `list_check_runs_for_ref` and returns `check_runs`, and every returned run carries its parent suite's id as a top-level `check_suite_id` beside its own `id`, so the documented `get_check_suite_logs` follow-up can be handed a suite id without the agent having to pick between two nested ids. `GitHubScmAdapter.list_check_runs`, the protocol's MCP-read operation of the same name, forwarded to the suites endpoint too and is corrected with it (#266)
- `mcp/server`: a malformed `tools/call` from the reviewing agent — a missing required argument, an unreadable one, or a property the tool never declared — reached the tool body and failed in whatever ad-hoc way that tool happened to fail, or partially succeeded, instead of being rejected at the protocol boundary; `handle_rpc` now validates `arguments` against the tool's `input_schema` before dispatch and returns JSON-RPC `-32602` with the offending JSON path and the validator's message. A string-encoded scalar sent where the schema declares `integer`, `number` or `boolean` — `"1"`, `"true"` — is read as that type and passed through rather than rejected: roughly 37 tool bodies were written for exactly that tolerance and the packaged workflow itself asks the agent for a bare `check_suite_id`, so rejecting it turned a tolerated shape into a hard error and silently degraded CI-log grounding. A union that already admits `string` is left alone, and a value that cannot be read as its declared type is still reported as the schema violation it is. `inf` / `nan` spellings such as `"1e999"` are refused rather than coerced — they satisfy the schema and then raise inside the tool body — and only `true`/`false`/`1`/`0` read as booleans, since no JSON consumer recognises `yes`/`no`. A tool whose declared schema cannot be compiled fails closed as `-32603` naming that tool, rather than running unvalidated arguments — reachable in production because `set_output` adopts a consumer-supplied `output_schema` verbatim and only its JSON-object-ness was ever checked. A non-dict `arguments` is still coerced to `{}` and is now rejected by any tool that requires a property, where it previously executed with no arguments. A call rejected here is charged no tool-call budget, so a schema mismatch the agent retries cannot burn the run budget with nothing executed, and the rejection is recorded on the trajectory instead of being invisible (#267)
- `mcp/server`: a `tools/call` carrying a very long integer literal where the schema declares `number` — anything past the float range, from 309 digits up — returned HTTP 500 with no JSON-RPC envelope and no request `id`, which is the response shape Codex's MCP client cannot deserialize and answers by killing its transport worker. The non-finite guard added for the `inf`/`nan` spellings asked `math.isfinite()` about a Python `int`, which converts to float first and raises `OverflowError`, and argument coercion runs before the handler's error boundary, so nothing caught it. Only a float can be non-finite, so the guard now says so; a wide integer is passed through typed as any other number is. Reachable on every top-level `number` property, including `shell.timeout`, `git_fetch.depth` and the `check_suite_id` the packaged workflow asks the agent to pass to `get_check_suite_logs` as a bare number (#267)
- `mcp/verdict`: a malformed finding the reviewing agent asserted could silently neutralise a real analyzer blocker that shared its fingerprint — the grader marked the fingerprint as already graded before discovering the row was unreadable, so the analyzer row carrying it was skipped and landed in neither the unverified nor the ungradable population, leaving the approve gate with nothing to block on. A row that cannot be read no longer spends its fingerprint (#263)
- `mcp/shell`: the shell tool's git refusal missed `sudo -u <user> git …` and `doas -g <group> git …` — the target name is neither path-shaped nor numeric, so it read as the command word and ended the scan before the git behind it was inspected, putting the whole git surface (`git clean`, `filter-branch`, `-c alias.…`) back within reach of a `restricted` shell. A wrapper flag's separate name operand is now skipped rather than treated as the command (#257)
- `wait-for-ci` job now declares a job-level `permissions: {contents: read, checks: read}` block so its `gh api …/check-runs` poll is no longer silently 403'd; stderr from the poll is no longer suppressed so permission failures are visible in the job log (#264)
- `action.yml` outputs (`result`, `evidence_packet`, `verdict_diagnostic`) no longer carry `value: steps.run.outputs.*` composite-action wiring — those expressions are inert on a Docker action and prevented consumers from ever reading the outputs; outputs are now written exclusively via `$GITHUB_OUTPUT` (#272)
- `verdict_diagnostic` output is now written to `$GITHUB_OUTPUT` on every run — the declared output was computed but never emitted, leaving the key permanently absent for consumers; an empty string is written when no terminal-verdict policy was evaluated (D10) (#265)
- `docker/e2e/run_in_image_adversarial.sh`: bumped `pytest==9.0.3` → `pytest==9.1.1` to match the `pyproject.toml` dev-dependency pin; one pytest version now spans unit CI and the adversarial image run (#271)
- `mcp/git`: `commit_changes` no longer attempts a doomed Git Data API `PATCH /git/refs/heads/{branch}` after a local commit; every return path now includes `pushed: false` so callers do not need a defensive `.get("pushed")` (#259)
- `analyzers/parsers/osv_json`: escaped the unescaped middle dot in the `_fixed_version` regex (`r"\d+\.\d+.\d+"` → `r"\d+\.\d+\.\d+"`); the bare `.` wildcard let two-component versions with three or more digits after the decimal (e.g. `1.234`) be accepted as `N.N.N` — with the wildcard consuming the adjacent digit — producing a fabricated fix-version string handed verbatim to the reviewer as `Upgrade to 1.234 or later` (#270)
- `analyzers/scope.base_comparison_available`: corrected inverted return — findings on an online `baseComparison: full` run were attributed as if the base comparison had not happened (all `introduced_by_pr` left `"unknown"`), while findings on an offline run were falsely attributed as introduced-by-PR; now returns `not offline` so that attribution is correct in both directions (#269)
- `mcp/git`: corrected `commit_changes` tool description — it performs a local commit only and does not push to the remote or produce a GitHub-verified commit (#259)
- `mcp/git`: `--namespace` is now refused outright rather than forwarded. It was the one extracted global option with no validation, and it cannot be path-confined because it sets `GIT_NAMESPACE`, a ref-namespace prefix rather than a path; no subcommand on the read-only allowlist consumes it (only `upload-pack` / `receive-pack` / `upload-archive` do), so refusal costs the reviewer no capability (#257)
- `mcp/git`: genuinely read-only invocations were refused, because a flat short-flag blocklist cannot express that a letter means different things to different subcommands — `git ls-files -o` / `-c` / `-co`, `git log -c`, `git show -c`, `git branch -av` / `-ar` / `-vvv`, `git branch --list <pattern>`, and `git diff -C`, which was mistaken for git's chdir option and swallowed the following token as its directory. Short flags are now read against the subcommand that defines them, `-C` after a subcommand that owns it is left in place, and a positional argument to `git branch --list` is understood as the glob it is. Every write vector stays refused (#257)
- `analyzers/adapters._run_ruff_format_check`: ruff format findings now cite the actual file that would reformat instead of always citing the first scoped file; with multiple files in a single `ruff format --check` invocation the reviewer was previously pointed at a file that was already correctly formatted (#268)
- `analyzers/adapters._run_ruff_format_check`: corrected the fallback finding message for a ruff invocation failure; when `ruff format --check` exits non-zero with no parseable `Would reformat:` line (a crash, syntax error, or unexpected output), the finding now reports `"ruff format check failed: analyzer produced no parseable output"` instead of falsely claiming the attributed file would be reformatted
- `analyzers/adapters._run_ruff_format_check`: on any repo running ruff 0.16 or newer every formatting finding disappeared and a clean run was mislabelled `"analyzer produced no parseable output"` — 0.16 routes `format --check` through the diagnostic renderer and no longer prints `Would reformat: <path>`; both output spellings are now parsed, ANSI colouring is stripped, and paths are taken only from `unformatted:` headers so an `invalid-syntax:` diagnostic is not read as an unformatted file. A sandbox refusal, or a ruff too old to support `format --check` at all, is now reported as a skipped analyzer rather than as a finding (#268)
- `analyzers/adapters._run_ruff_format_check`: a ruff `unformatted:` header with no location line of its own adopted a *later* diagnostic's location, so a reformat was attributed to a file that did not need one, and a location whose trailing `:line:col` did not parse was taken whole as a path and became a finding against a file that does not exist; a header now claims only the location on the line immediately following it, and an unparseable location yields no path at all (#268)
- Fixed `mergecraft review --format jsonl|sarif` writing empty output files and exiting 0 even with blockers — the CLI now threads a structured-findings sink through to the review so jsonl/sarif writers see real findings (#242 / `mergecraft-finding:v1:3f363546e98dad517048b8b9`)
- Fixed the empty-diff early return in `run_offline_diff_review` silently reporting `RunOutcome.passed` when `apply_diff_line_budget` fully truncated (or untrusted-path filtering emptied) the diff; the run now applies the scope-reduction downgrade and reports `inconclusive` (D12) (#242 / `mergecraft-finding:v1:2e1cb9c2153087658c3481bd`)
- Fixed `mergecraft review` default text mode never producing exit codes 10/11 — the CLI now requests structured findings internally so a CI script running `review` can block on the documented exit-code contract (#242 / `mergecraft-finding:v1:7a3cdf5ef1994610113e8e37`)
- Fixed `mergecraft plan` reporting `diff_path` that pointed at a path inside a torn-down `TemporaryDirectory`; the materialized diff is now persisted to `<repo>/.mergecraft/plan-review.diff` so the report's `diff_path` is reachable after return (#242 / `mergecraft-finding:v1:e8bc195570ae6f1cc8ab5bc6`)
- Fixed tool-call budget exhaustion only surfacing as a JSON-RPC error to the agent — `BudgetTracker` now records the `BudgetExhausted` it raises (`last_exhausted`) and `main._finalize` drains the tracker at finalize time, so a run that exhausts its tool-call budget is tagged `inconclusive` rather than approving on a partial signal (D12) (#242 / `mergecraft-finding:v1:aeb5d964c1d35e5a41784ded`)
- Fixed eval corpus run directories splitting on slashes in model slugs (e.g. `openrouter/openai/gpt-5`) — run ids are sanitized to a single flat component (#219)
- Fixed live corpus reviews running in an empty scratch directory — the case's repo context is materialized before the review (#220)
- Benchmark result sets now record full version pins and a reproducibility digest, so same-commit runs are comparable (#140)
- Two ensemble models that both report no findings no longer escalate to a judge (#238)
- Reviews of Python repositories with `shell: disabled` no longer fail closed after a completed review just because dependency installation was skipped as a security policy
- Fixed: model-chain fallback now advances when the provider succeeds without a terminal verdict; a valid `request_changes` is a usable result and does not trigger fallback
- Fixed: explicit `harness:` now selects the runtime agent, not only span labels
- Fixed: a previously recorded `approve` is re-validated before GitHub publish, so a later confirmed blocker cannot ship an `APPROVE` review
- Fixed: body-only `create_pull_request_review` with `approved: false` no longer posts a GitHub `APPROVE`
- Fixed: `create_pull_request_review` now requires established review scope in Review modes, matching `submit_review_verdict`
- Fixed: terminal-verdict shadow mode now records a predicted outcome beside the legacy result on the live finalize path
- Fixed: a body-only COMMENT is no longer recorded as `request_changes`, and body-only `request_changes` is rejected unless it has real findings
- Fixed: publication must match the recorded terminal verdict and is re-validated before sending `APPROVE`
- Fixed: IncrementalReview `report_progress` no longer advances the model chain
- Fixed: Review completion via `create_pull_request_review` now records a terminal verdict, and IncrementalReview may complete via `report_progress` without mapping to `inconclusive`
- Fixed: verifier confirms persist outside replaceable analyzer run state, including agent-authored findings
- Fixed: a verifier `confirm` now persists the finding fingerprint so `approve` over a confirmed blocker is rejected on the live tool path, not only in unit tests that seed `verified_ids`
- Fixed: a stored `approve` is re-validated at finalize against current evidence, so a later failed required gate or verifier confirm cannot leave the run `passed`
- Fixed: a provider success without a usable terminal verdict now advances the model chain when fallback is allowed, instead of accepting the first process-successful result
- Fixed: a later `run_static_checks` call that matches no gates no longer wipes a prior failed row, so `approve` still fails closed
- Fixed: `approve` is now rejected on the live path when `run_static_checks` recorded a failed required gate; previously the validator only saw those rows in unit tests
- Fixed: a review run that completes without submitting a terminal verdict now reports `inconclusive` (a `neutral` check conclusion) instead of `passed`. Previously a provider that returned successfully without reviewing anything produced a successful run. Prose such as "LGTM" has never been able to approve and still cannot
- `submit_review_verdict` now rejects non-list `findings` and severities outside
  the review taxonomy, hashes the validated payload so omitting `findings` matches
  `findings: []`, keeps a conflict flag sticky for the attempt, and scopes the
  recorded submit to the active model-chain attempt so a fallback cannot inherit
  or conflict-reject the failed attempt's verdict
- `README.md`'s CLI table documented `mergecraft traces <run-id>`, but the real
  registered command is `mergecraft traces show <run-id>` — the stale
  invocation is now generated from the live CLI app instead of hand-maintained
- `tracing_logfire_wf_yaml` `uses_re` regex now matches the inline
  `- uses: alexhawat/mergeCraft@X` step form (used by README Examples 1 and
  6) — previously the regex required leading whitespace before `uses:` and
  silently rejected every workflow the README documents. The `_do` closure
  now also synthesises a `with:` block when absent (symmetric with
  `_create_env_block`) — every `action.yml` input is `required: false`, and
  the comment claiming otherwise was wrong

### Changed

- Dependabot now batches patch and minor bumps into one grouped PR per ecosystem (pip, github-actions, docker, and the `docker/agent-clis` npm lockfile), with security updates in their own group and majors still opened individually; `open-pull-requests-limit: 5` caps each ecosystem
- `mergecraft review` skips PRs authored by `dependabot[bot]`: the gate failed closed on every version bump (the reviewer posted no `mergecraft-approval` check-run, so the enforce step's fail-closed branch blocked the PR). Both jobs are conditionally skipped rather than untriggered, so a rule requiring `mergecraft review` still reports. `changelog-preview` is deliberately left running — it already passes on bot PRs, and skipping a reusable-workflow caller would report under the bare caller job id rather than the two-part `changelog-preview / preview` check name. CI, CodeQL, the security-audit Verify job, and SHA pinning still gate these PRs
- `.github/agents/dependency-pr-manager.md` — dry-run-first sweep agent for the dependency-PR queue: classifies each bot PR into auto / review / blocked / suspicious lanes, diff-audits that a bump touches only its manifest and lockfile, and writes a per-major review brief instead of merging majors blind

- `mergecraft review --help` now states that no flags are required and includes full example commands for local worktrees, GitHub branches, and present or past PRs
- Stale pytest `xfail(strict=False)` markers that were already passing are now real tests; remaining allowed-tree xfails are strict (#276)
- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`
- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

### Security

- docs: `SECURITY.md` secret-stripping claim narrowed to the agent subprocess (`build_agent_env` / `filter_env`) and the sandboxed `shell` tool (`resolve_env`); `_run_git` inherits the process environment and is not covered by the filter (#286)
- Untrusted PR trees no longer receive a `shell` tool when PID-namespace isolation is unavailable (#287)
- Untrusted PR trees no longer run package install lifecycle scripts in the Action process when `shell` is the default `restricted` (#284)
- `mcp/git`: replaced permissive `_SUBCOMMAND_RE` with an explicit read-only allowlist (`status`, `log`, `diff`, `show`, `rev-parse`, `describe`, `ls-files`, `blame`, `cat-file`, `rev-list`, read-only `branch`); `git reset`, `git clean`, `git stash`, and all other mutating subcommands now raise `ValueError` unconditionally (#257)
- `mcp/git`: `-c` / `--config-env` are now rejected unconditionally regardless of `payload.shell`, closing the `git -c alias.x='!cmd'` arbitrary-shell-execution vector that bypassed the former `shell: disabled` guard (#257)
- `mcp/git`: the glued single-token spelling (`-ckey=value`) is refused alongside the spaced and inline forms, so the alias-execution block no longer depends on how the flag was written. The `-c`-shaped token is read against the short flags the subcommand defines before it is judged, which keeps `ls-files -co` and `log -c` working — a glued config payload cannot pass that test, because a key name, a `.` and an `=` are not short-flag letters (#257)
- `mcp/git`: `git branch` write forms reached refs through a tool declared repository-*read* — only `-d` / `-D` / `-m` were blocked, leaving `--delete`, `--move`, `-M`, `--copy` and bare `git branch <name>` creation to succeed. Listing flags are now an allowlist rather than a list of remembered write spellings, bundled and repeated short flags are checked letter by letter so one write letter refuses the whole token, and a rename of the checked-out branch can no longer change what a later `commit_changes` or `push_branch` targets (#257)
- `mcp/git`: `git diff --output=<path>` wrote an arbitrary file through a read-only tool — the subcommand allowlist constrains the verb, not the flags the verb accepts. `--output` and every unambiguous prefix git also honours (`--out`, `--outp`, …) are refused on every allowlisted subcommand, and `-o` is refused on the subcommands that do not define it themselves (#257)
- `mcp/shell`: a `git` invocation on its own line was never inspected, because the guard's separator class omitted the newline while `bash -c` runs every line of its argument — so `git -c alias.z='!sh …'` reached the shell and bypassed the git tool's alias block along with the `clean` and `filter-branch` verbs that tool refuses by name. Every command position in the command string is now scanned, across newlines, command substitution and backticks; git is matched by path basename so `/usr/bin/git` and the alias-suppressing `\git` are seen; and leading environment assignments, a wrapper's own numeric or path argument, and wrapper commands (`env`, `xargs`, `timeout`, `sudo`, `flock`, `script`, nested `sh -c`, and others) are looked past. `grep git README` and `ls .git` still run. This stays defence in depth behind the git tools' own allowlist, not a shell parser — arbitrarily quoted payloads, variable indirection and `printf … | sh` remain out of reach of any token scan (#257)
- `mcp/git`: `-C`, `--git-dir`, and `--work-tree` are now confined to the resolved primary repo root; any path outside raises `ValueError` with the offending path in the message (#257)
- `mcp/upload`: `upload_file` now rejects symlinks and confines the requested path to the primary repo root or the session `tmpdir`; no `file://` URI is emitted for a path that fails confinement (#258)
- `mcp/labels`: label names are now percent-encoded (`urllib.parse.quote(label, safe="")`) before interpolation into the `DELETE /labels/{label}` path segment, preventing `/` or `..` in a label name from shifting the URL path (#260)
- `cli/auth`: credentials written by `mergecraft auth` inherited the umask, so a `.env` started from the documented `cp .env.example .env` stayed readable by every user on the machine while holding Codex OAuth JSON, Claude tokens and up to five provider API keys — the first path writing any of them outside a temporary directory. The file is narrowed to `0600` *before* the credential is written as well as after, so there is no window in which the secret sits in a world-readable file. A `chmod` that fails warns rather than refusing the write (#221)
- Linked-repo reads are grant-gated (D9): a run can only load repos declared in its authorized set; linked-repo and ticket text render through the W4 fence as untrusted data
- Discovered repo instruction and skill files (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `.cursor/rules/*.md`) from an untrusted review source render through the W4 fence as evidence and never enter the instruction bundle
- CLI offline reviews now derive a trust tier from review-source provenance; cloned or out-of-root paths review at untrusted tier unless the operator passes an explicit `--trust` override
- Executable repo config (`setupScript`, `prepushScript`, `stopScript`, `staticChecks[].command`) from an untrusted review source is ignored; declarative config still applies
- Third-party clone acquisition is bounded and credential-safe: HTTPS GitHub URLs only, no redirect following, no submodule recursion by default, size and file-count ceilings, symlink/path containment, tokens never persisted in `.git/config` or process argv
- Added `mergecraft review` to target any local worktree, public GitHub repo, or private repo (with `--token` / `GH_TOKEN` / `gh auth token`), with `--head`, `--base`, `--staged`, `--unstaged`, and `--range` diff selection; `diff-review` remains as a hidden alias
- Reviewer and verifier now hold distinct, class-derived MCP toolsets; the live
  MCP server exposes those surfaces at `/mcp/reviewer` and `/mcp/verifier`,
  mutating tools stay off both except `checkout_pr` on the reviewer, and
  finding-verdict persistence stays orchestrator-only
- `AgentRunContext.mcp_server_url` now carries the role endpoint for the primary reviewer (`/mcp/reviewer`); `write_mcp_config` maps the current agent span to the role URL so the Claude verifier connects to `/mcp/verifier`, not the orchestrator surface (#282)
- `build_mcp_app_for_role` with `role="reviewer"` or `role="verifier"` no longer mounts the orchestrator toolset at `/mcp`; only the role-specific path is active (#282)
- Primary reviewer surface (`/mcp/reviewer`) now includes `create_pull_request_review` (`ToolClass.REVIEW_WRITE`) via `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES` and `PRIMARY_MUTATING_ALLOWLIST`; subagents retain the narrower `REVIEWER_ALLOWED_TOOL_CLASSES` complement so they remain denied review publication (D9, #282)

### Removed

## [0.1.0] — 2026-08-14

Initial public release: mergeCraft is a standalone, BYOK GitHub Action for
AI-powered PR review — no proprietary backend, no account, review runs
against your own Claude/Codex/Gemini subscription or API key.

Full pre-release development history: see
[`docs/dev/changelog-archive.md`](docs/dev/changelog-archive.md).

### Added

- Multi-agent review drivers for Claude Code, Codex, Gemini CLI, Cursor
  Cloud, and OpenCode, each resolving from a subscription login or an API
  key with no proprietary backend in between
- Curated multi-provider catalog (Nous Research/DeepSeek, Tencent TokenHub,
  MiniMax) plus a generic custom OpenAI-compatible gateway, configurable via
  `.mergecraft/config.yaml` or `with:` inputs
- Ordered model chain with automatic fallback: entries missing credentials
  are skipped and retryable provider failures advance to the next entry
- Analyzer catalog covering linters and type-checkers (Ruff, MyPy, Pyright,
  ESLint, Biome, Oxlint), dependency and secret scanning (OSV-Scanner,
  Trivy, TruffleHog), pattern scanning (Semgrep/OpenGrep/ast-grep), contract
  diffing (oasdiff, Squawk, buf), GitHub-native tools (actionlint, zizmor,
  ShellCheck, Hadolint), and a first-party scanner for MCP/skill manifests;
  selection is trust-tier aware (`analyzers: off|auto|full|untrusted-only`)
- Merge Evidence Packet: every run emits a versioned, structured record of
  findings, analyzer checks, the blast-radius lane, and the structural
  decision, exposed as the Action's `evidence_packet` output
- Blast-radius classifier maps changed paths to low/medium/high merge
  lanes, with additive per-category repo overrides
- Structural `mergecraft-approval` status check — a pure function of typed
  findings, run completion, and trust tier, so a crashed or timed-out run
  reports `neutral` rather than silently passing
- Eight trajectory checks read the agent's own mediated tool calls (a file
  edited but never read, a tool error retried with nothing changed, and six
  more) and feed the evidence packet
- File-backed eval bank (`mergecraft eval add|list|replay|promote`) turns
  real review outcomes into regression cases and permanent pytest tests
- Optional tracing: a local JSONL sink plus Logfire/OTLP remote export, a
  full per-run span tree, and a redaction boundary that scrubs secrets
  before any sink sees them (`mergecraft tracing`, `mergecraft auth logfire`)
- `mergecraft findings export|carryover` files GitHub issues for review
  findings a merged PR left unresolved, so they survive past the merge
- Optional GitHub code-scanning upload (SARIF) for analyzer findings
  (`sarif_upload: enabled`)
- Per-run nonce fencing neutralizes prompt-injection attempts in untrusted
  PR titles, bodies, and comments before they reach the reviewing agent
- Comment-triggered runs (`@mergecraft`) are gated on the commenter's GitHub
  author association by default, extendable via `commentInvocationAllowlist`
- CI pipeline intelligence clusters failures, distinguishes flaky and
  pre-existing failures from ones the PR introduced, and blames failures to
  the hunks that caused them
- `mergecraft models|analyzers|eval|tracing|learnings|auth` CLI command
  groups; README's Action-input, Action-output, and CLI reference tables are
  generated from the live sources and CI-gated against drift
- Hardened example workflow
  (`examples/workflows/mergecraft-hardened.yml`) with a same-repo secret
  guard, wait-for-CI, and approval-check enforcement
- Release pipeline builds each image once, attaches SBOM and vulnerability
  scan reports, cosign-signs and attests the digests, then promotes tags by
  digest — no second rebuild between scan and release

### Changed

- Typed `ProviderConfig` for OpenAI-compatible gateways (capabilities declarative; API keys stay in env vars). No wire-format change to generated `opencode.json`
- **BREAKING** — `with: model:` is now the head of the effective model
  chain rather than a replacement for it; set `model_pin: enabled` (or
  `modelPin: true`) to restore the old single-model behavior
- **BREAKING** — comment-driven invocation under `pull_request_target` is
  refused by default; opt in with `allow_pr_target_comments: true`
- **BREAKING** — new learning entries land in a quarantined staging section
  by default instead of taking effect immediately; set
  `autopromoteLearnings: true` to restore auto-promotion
- **BREAKING** — an unrecognized `analyzers:` input value now resolves to
  the strictest tier (`untrusted-only`) instead of the most permissive
  (`auto`)

### Security

- Agent privilege drop fails closed: a run that cannot drop root aborts
  instead of continuing to execute the reviewing agent as root
- Trust tier is derived before any repo-controlled script or git setup
  runs, and an unrecognized event shape fails closed to `untrusted`
- Agent CLI subprocesses receive an explicit credential allowlist — no
  ambient GitHub tokens or inactive provider keys reach the process
- A first-party analyzer (`agentsec`) scans `.mcp.json`, `CLAUDE.md`,
  `AGENTS.md`, and skill files for policy violations, and still runs under
  `shell: disabled`
