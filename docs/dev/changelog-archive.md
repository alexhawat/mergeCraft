# Pre-v0.1.0 development history archive

This is the complete, unedited development history of mergeCraft prior to the
v0.1.0 release. From project inception until the v0.1.0 cut, every change
accumulated under a single `## [Unreleased]` heading in the root
`CHANGELOG.md` — there had never been a prior release to cut a dated section
from. That accumulated history (26 subsections) is preserved here verbatim,
unedited, as the permanent historical record.

The root [`CHANGELOG.md`](../../CHANGELOG.md) carries a curated,
consumer-facing summary of this history under `## [0.1.0]`; this file is the
full record behind that summary.

---

### Added

- `scripts/gen_reference_docs.py` regenerates README's `action.yml` input/output
  tables and CLI command table from the live sources (never a subprocess — it
  walks the live Typer `app` object) and splices them between HTML sentinel
  comments; `make reference-docs-check` (wired into `make ci-static`) fails the
  build on drift. Closes the audit in the issues-showcase-readiness wave plan
  (PR G2): the README table documented 9 of 24 real `action.yml` inputs and
  neither declared output anywhere

### Fixed

- `README.md`'s CLI table documented `mergecraft traces <run-id>`, but the real
  registered command is `mergecraft traces show <run-id>` — the stale
  invocation is now generated from the live CLI app instead of hand-maintained

### Removed

- Dropped `evidence/` from the tree — it held regenerable verifier/tool-run
  output, not project history; `/evidence/` is now gitignored so local runs
  keep writing there without re-entering the index
- `meat_python_plus/`'s prior removal from trunk is now backed by an archive
  branch: all 56 files are preserved at `archive/meat-python-plus`
  (`39db421af2a6afbd8c17bea1533117fb4f3c7f42`) for anyone who needs the
  prototype's history

### Changed

- `docs/test-plans/` moved to `docs/dev/test-plans/`, keeping engineering
  history out of the top-level docs a reader browses

### Changed

- The four silent `except Exception: pass` sites in `main.py`, `mcp/shell.py`
  (x2), and `mcp/server.py` now log the swallowed exception via
  `logger.warning` before continuing; the best-effort swallowing semantics
  are unchanged, but the failure is no longer invisible at the default log
  level
- `main()` is now a thin orchestrator over `RunContext`-carried phase functions
  (`_setup_run`, `_resolve_credentials`, `_execute_agent`, `_finalize`), and the
  five worst analyzer hotspots (`resolve_analyzer`, `_exclusive_group_winner`,
  `run_plan`, `_run_osv_scan`, `detect_enabled`) are split into small named
  helpers. Pure refactor — no user-visible behaviour change; the new `max-
  complexity = 15` `ruff --select C901` gate now passes on the whole tree.
- Eval bank replay harness (`make eval-replay`) writes versioned result sets with
  judge pins, rubric version, and S5 mode prompt versions; seeded corpus expanded
  to ten human-labelled cases across correctness, security, cross-file, and
  adversarial classes ([#140](https://github.com/alexhawat/mergeCraft/issues/140))
- Ruff advisory families are no longer selected and ignored in blocking `make lint`:
  ERA is enforced; noisy families are dropped; BLE, PTH, PERF, and C901 run as a
  non-blocking `lint-ruff-advisory` CI step ([#146](https://github.com/alexhawat/mergeCraft/issues/146))
- Coverage ratchet now runs from `make ci` via `coverage-gate`; measured coverage must
  stay within `fail_under` and a fixed margin or the floor must be bumped deliberately
  in `pyproject.toml` ([#142](https://github.com/alexhawat/mergeCraft/issues/142))
- 0.0.1 distribution checklist: README prototype markers removed, docs badge label
  aligned with GitHub Pages, operator runbook at `docs/distribution.md`, and prototype
  residue (`meat_python_plus/`, `docs/meat-spike.md`) dropped from the tree ([#141](https://github.com/alexhawat/mergeCraft/issues/141))
- CI/CD publish path now gates `build-images` on the Action-image E2E suite for the
  exact release SHA via a reusable `e2e-gate` job (`workflow_call` on `e2e.yml`)
- Image vulnerability scans now block promotion on every publish ref when Trivy reports
  unwaived HIGH/CRITICAL findings; `.trivyignore` waivers require per-entry justification
  and expiry (a CVE cannot inherit a neighbor's metadata)
- `make ci` runs the unit suite once via `coverage-gate`; live integration selection
  lives in `scripts/run_live_integration.py`; eval result sets pin `evals/cases` at
  `HEAD:evals/cases`; OTLP collector image digest is single-sourced in
  `scripts/otel_collector_image.txt`; PR integration excludes live and OTLP-docker tests

### Fixed

- Fixed: `.pre-commit-config.yaml`'s `ruff-pre-commit` hook was pinned three
  minor versions behind `pyproject.toml`'s `ruff==` dev pin (`v0.15.12` vs.
  `0.16.0`), so local hooks and CI could disagree on lint results. Both now
  pin `0.16.2` (landing Dependabot #159), and a new `make hook-pins-check`
  (wired into `make lint`) parses both files and fails the build on future
  drift
- Fixed: the nightly live-provider job now issues a real minimal request per provider
  and asserts a structured completion. Previously it exported four provider keys but ran
  only offline-shaped tests — three of the four keys had no consumer — and exited 0 with
  "skipped" when credentials were absent, so a rotation outage looked like a pass
- Fixed: OTLP tracing export now forwards `gen_ai.*` span attributes to real collectors;
  CI and `make test-otlp-collector` gate merge with a digest-pinned
  `otel/opentelemetry-collector` service ([#143](https://github.com/alexhawat/mergeCraft/issues/143))
- Fixed: nightly GitHub live-integration matrix leg can post status checks (`statuses: write`)
- Fixed: `README.md` no longer references the nonexistent `docs/assets/logo.svg` /
  `docs/assets/demo.gif`; the hero mark now renders from tracked `assets/brand/`
  SVGs via a light/dark `<picture>` element, and `assets/brand/` (13 SVGs, the
  source JPG, and `build_logo.py`) is tracked in git for the first time

### Removed

- Dropped the `docs-mergecraft.dev` badge and every `alexhawat.github.io/mergeCraft`
  link from `README.md` — the GitHub Pages docs site was never published and the
  badge/links 404'd. Docs links now point at the in-repo `docs/` tree

### Security

- Fixed: the agent privilege drop now fails closed. When the action image runs
  as root and `setpriv` or the `mergecraft` user is unavailable, the run
  aborts as `configuration_error` instead of silently executing the agent as
  root — previously that degradation was logged at `debug` and the review
  continued. The image build now asserts both are present.
- Fixed: the privilege drop also rejects the resolved user when its UID/GID is
  0 — the username is not the security boundary, so `MERGECRAFT_AGENT_USER=root`
  (or any user mapped to uid 0) can no longer silently run the agent as root
- Fixed: `prepare_workspace_for_agent` is now guarded at its `main()` call site,
  so a missing/UID-0 agent user surfaces as `RunOutcome.configuration_error`
  instead of escaping as an uncaught traceback
- Trust tier is derived before any repo-controlled git setup or `setupScript`;
  untrusted events skip operator scripts instead of running them first
- Agent CLI subprocesses receive an explicit credential allowlist — no ambient
  `GIT_ASKPASS`, `GITHUB_TOKEN`/`GH_TOKEN`, or non-active provider keys; git
  auth is brokered per MCP invocation
- Containment: `safe.directory` is scoped (no `*`), git hooks stay off unless
  `shell: enabled`, working directories must stay inside registered workspace
  roots, and agent CLIs drop to the unprivileged `mergecraft` user
- Askpass helpers are written then immediately shredded after git setup
  (auth is brokered via MCP `http.extraHeader`, never ambient `GIT_ASKPASS`);
  runner-temp wipe only removes mergeCraft-registered paths
- Fixed: `derive_trust_tier` now returns `untrusted` for unrecognized or
  malformed GitHub event shapes instead of defaulting to `trusted`.
  Previously an unknown event type received the most permissive tier. The
  `pull_request` dict branch is gated on `GITHUB_EVENT_NAME == "pull_request"`
  and only a same-repo shape (`fork is False`) earns the trusted tier; an
  unknown event name with a PR-shaped payload, or a `pull_request` payload
  with missing or wrong-typed nested fields, fails closed to `untrusted`.
  Comment / schedule / `workflow_call` / `workflow_run` / `merge_group` /
  `push` / `release` / empty `GITHUB_EVENT_NAME` all resolve to `untrusted`.
  (#144)

### Added

- Tracer spans are now capped at `MAX_SPANS_PER_RUN` (10,000) per run — once a
  run hits the ceiling, further spans stop reaching the configured sink and a
  single `warning` is logged, instead of the trace tree growing unbounded on a
  runaway (#56)
- Direct unit tests for `Tracer` / `Span` / `NullTracer` and the JSONL,
  redacting, and OTLP sinks (`tests/tracing/test_tracer.py`,
  `tests/tracing/test_exporters.py`), previously only exercised transitively
  through other tracing test modules
- `feat(analyzers): add change-impact extraction (impactPath) for review prompts` — new
  `analyzers.impact` setting (default off) enables declaration-level reference-lead
  extraction from the diff. When enabled and the diff touches files with recognised
  extensions, `checkout_pr` returns an `impactPath` JSON file listing every declaration
  the diff touches, grouped by language, capped at 24 declarations. Defaults to off
  pending eval-bank measurement. (#94)
- `feat(findings): carry unresolved review findings past the merge` — a merged PR
  keeps its inline comments forever but nobody re-opens one, so findings the
  author never fixed or rebutted were lost to attention. `mergecraft findings
  export --pr N` prints them (read-only, JSON or markdown) and `mergecraft
  findings carryover --pr N --apply` files one issue each, labelled
  `mergecraft-carryover`. Only unresolved, mergeCraft-raised, human-unanswered
  threads carry over; `--include-resolved` / `--include-answered` widen that.
  Re-running is a no-op — every filed issue embeds a PR-scoped carryover key and
  each sweep reads those back first, so a finding reintroduced by a later PR
  still files as the regression it is. `.github/workflows/findings-carryover.yml`
  runs it on every merged PR, dry unless the `CARRYOVER_AUTO_APPLY` repository
  variable is set. See [`docs/findings-carryover.md`](../findings-carryover.md).
- `feat(tracing): enrich tool.call attrs to carry invoke + complete + verb sub-event info` —
  every `tool.call` span carries the request/response byte counts, `exit_code`,
  error class/message, and input-key list. Known-verb tools (`browser`,
  `search`, `read_file`, `write_file`, `run_code`, `load_tool`) also emit a
  verb-specific child span (`tool.browse`, `tool.search`, `tool.read`,
  `tool.write`, `tool.run_code`, `tool.load_tool`) for finer-grained Logfire
  grouping. The MCP `tools/call` handler now stamps `tool.arguments` /
  `tool.argument_count` / `tool.argument_bytes` on the open side and
  `tool.exit_code` / `tool.result_kind` / `tool.result_bytes` on close
  (success path); failures additionally carry `tool.error_class` /
  `tool.error_message` (redacted) and keep `gen_ai.tool.output` set so the
  GenAI dashboard sees the row. The three driver event handlers
  (`agents/claude.py` `_claude_stream_event_handler`,
  `agents/codex.py` `_codex_stream_event_handler`,
  `agents/gemini.py` `_gemini_stream_event_handler`) apply the same
  enrichment on the open/close sites they already emit from. New
  `src/mergecraft/agents/_tool_attrs.py` ships `KNOWN_VERB_TOOLS`,
  `enrich_tool_call_attrs`, `emit_verb_subevent`, and `_classify_tool_result`
  so all three drivers + the MCP server share one source of truth. The
  `enrich_tool_call_attrs` helper landed in T1 as a single combined helper;
  W4 split it into the open-side `enrich_tool_request` and close-side
  `enrich_tool_response` (see the W4 `### Changed` entry below). New
  `mergecraft.tracing.redaction.redact_tool_payload(payload)` extends the
  existing D7 redaction boundary: stringifies non-str values via
  `json.dumps(default=str)`, caps at `TRACE_ATTRS_JSON_MAX_BYTES` (returning
  `"<truncated>"` on overflow), and pipes the result through `redact_secrets`
  so embedded tokens (`ghp_…` / `sk-…` / bearer headers) cannot escape onto
  the span. The local `_truncate_tool_payload` copies in `claude.py` /
  `codex.py` / `gemini.py` are folded into the shared helper. The 64 KiB cap
  on `TraceEvent.attrs` still applies — `tool.arguments` is stored as a
  string so a 100 KB value collapses the row to `{"truncated": True}`
  instead of blowing past the JSONL ceiling. `docs/TRACING.md` gains a
  "Tool call attributes" section with the full attribute table, the verb
  sub-event list, and the cap + redaction behaviour. Tests: the 11-case
  RED suite in `tests/tracing/test_tool_call_attrs.py` (10 pass + 1 xfail
  passing through — the formerly xfail `test_known_verb_tool_emits_verb_sub_event`
  now passes deterministically; the `strict=False` xfail marker is removed
  by `xfail-reconciliation` once the next wave lands the xfail cleanup)
- Six-value run outcome taxonomy (`passed` / `failed` / `inconclusive` /
  `infra_error` / `timed_out` / `configuration_error`) drives check conclusions
  and Action `result` JSON, including a stable `error.code` on failure paths
- Action `evidence_packet` output is emitted on the live `mergecraft gha` path
  (packet JSON via the multiline heredoc helper)
- PR CI builds the production Action image and runs it against fixture
  `pull_request` / `pull_request_target` payloads with a fake provider CLI
  shim (no live LLMs); the adversarial `shell × push` suite also runs
  in-image, and `docs/compatibility-matrix.md` defines the supported events ×
  agents × providers × shell × push × arch matrix with a secrets-gated nightly
  job
- Release pipeline builds each image once, attaches SBOM + vulnerability scan
  reports, cosign-signs and attests the digests, then promotes mutable tags to
  those same digests (no second rebuild)
- Operators can refuse model-chain fallback with `allowFallback: false` in
  `.mergecraft/config.yaml`; an unavailable primary fails closed as
  `configuration_error` instead of silently reviewing under a backup
- Every merge evidence packet records requested vs executed model, provider,
  and fallback index/occurrence so operators can prove which reviewer model
  actually ran
- Integration gate in PR CI (`make test-integration`, coverage floors,
  `npm audit` on agent CLIs, actionlint/zizmor) plus a secrets-gated live
  integration job as a release precondition
- `fix(setup): bound `setupScript` execution and fail closed on its failure` (S1) —
  three new action inputs land:
  `setupFailurePolicy` (`inconclusive` (default) | `fail` | `warn`) and
  `setupTimeout` (default `10m`, duration grammar `5m` / `30s` / `1h`). A
  trusted-tier `setupScript` now runs as a session leader with
  `asyncio.wait_for` over its `communicate()`; a timeout TERM → grace → KILLs
  the whole process tree via the existing `utils/process_group.kill_process_group`
  helper (no second kill path). A failed or timed-out setup script maps the
  run to `RunOutcome.inconclusive` (D5) under the default policy, never
  silently `passed`. The trust check at `main.py:368` still precedes every
  subprocess spawn (convention 8); untrusted tiers continue to skip the
  script. Setup-script elapsed time is deducted from the agent deadline
  (F6) so a slow install cannot silently extend the run budget. Setup
  stderr reaching the prompt or `result` output is passed through
  `analyzers.redact.redact_secrets` first (convention 7). `RunOutcome`
  stays at its closed six-value taxonomy (convention 6); S1 adds producers
  of `inconclusive`, never a seventh outcome.

### Changed

- Tracing: W6 — `_open_provider_llm_pair` / `_close_provider_llm_pair` now
  wrap the post-`provider_span.__enter__()` body in a `try/except` so a
  raised inner `start_span` (or `llm_span.__enter__`) closes the provider
  span and pops its active-span frame before the exception propagates.
  The three driver event handlers (`claude` / `codex` / `gemini`) no
  longer re-stamp `model.id` on the inner llm span — the helper is the
  single source of truth and the provider span is the canonical home.
- Tracing: tool-call attribute helpers moved from `agents/_tool_attrs.py` to
  `tracing/_tool_attrs.py` so the MCP package no longer reaches into agents
  (W4 H3); the single `enrich_tool_call_attrs` helper split into the open-
  side `enrich_tool_request` and the close-side `enrich_tool_response`
  (W4 M1 — each call site is now one obvious line and the codex double-set
  bug is fixed).
- Tracing: three different redacted sentinels (`[REDACTED]`, `<redacted>`,
  masked lines) collapsed to the single canonical `REDACTED = "<redacted>"`
  literal in `tracing/redaction.py` (W4 H4).
- Tracing: `tracing/tracer.py` gained `active_span_for` (W4 M4) and the
  `Span.close()` method (W4 M6); new `provider_llm_pair` context manager
  pairs a `provider.call` parent with its `llm.call` child on a shared
  `parent_span_id` (W4 H1) — the three driver event handlers now store one
  `ProviderLLMPair` per attempt instead of two independent span dicts
  (W5 H1, M2).
- Tracing: `tracing/http.py` short-circuits to a true no-op when the caller
  passes `None` or a `NullTracer` (W4 H6).
- Tracing: `agents/opencode.py` no longer constructs a `Tracer` whose result
  was discarded (W4 H7).
- Docker Action images pin base layers, `uv`, Node, `gh`, and agent CLIs by
  digest or lockfile so rebuilds are reproducible and Dependabot can bump
  every pinned artifact
- Security and runtime config models (`RepoSettings`, `GatesSettings`,
  `AnalyzersSettings`, `TracingSettings`) now reject unknown keys
  (`extra="forbid"`) instead of silently ignoring typos
- Unparseable Action `timeout` input fails closed as `configuration_error`
  (keep `--notimeout` to disable); dependency-install failure maps the run to
  `inconclusive` rather than a silent continue
- Changed: unknown keys in optional-feature config blocks (`staticChecks`,
  `ciEvidence`, custom mode definitions, tracing sink entries) are now
  configuration errors instead of being silently ignored — the one-release
  warning shim has ended. Security and runtime blocks were already strict.
  A syntactically broken `.mergecraft/config.yaml` still falls back to
  defaults.
- Tracing `enabled` is tri-state (`true` / `false` / unset); Action
  `tracing` input no longer collapses unset to false, and is wired into the
  live Action path (input > env > YAML > default)
- GitHub REST and Cursor Cloud HTTP clients use bounded exponential backoff
  with jitter for retryable reads (429/5xx/transport); mutations are never
  retried blindly
- Opt-in structured JSON logs (`MERGECRAFT_LOG_FORMAT=json`) bind
  `run_id` / repo / PR / phase for operator debugging alongside opt-in tracing
- Craft reusable workflows are SHA-pinned; release and publish jobs use
  least-privilege `permissions` (no blanket `secrets: inherit`)

### Fixed

- Pydantic config `ValidationError` (unknown keys / bad enums) maps to
  `configuration_error` instead of `infra_error` on the live Action path
- Mid-run `wipe_runner_leak_surface` no longer deletes the active
  `MERGECRAFT_TEMP_DIR`, which previously broke askpass creation inside the
  Docker Action (`setup_git` → missing `credentials/` parent)
- Agent CLI subprocesses now head their own process group
  (`start_new_session=True`); timeout/cancel sends TERM → grace → KILL to the
  whole group so grandchild processes cannot outlive the Action run
- `has_gateway_credentials` no longer false-positives for unrelated gateway
  presets. A Batch C (#34 / PR #126) addition let an indexed custom-provider
  pair (`MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`) or the singleton
  pair make `has_gateway_credentials("minimax")` / `"nous"` / `"tokenhub"` all
  return `True` regardless of whether that preset's own env vars were set,
  partly undercutting the minimax fail-loud guarantee. The `resolve_gateway_endpoints()`
  short-circuit was removed from `has_gateway_credentials` so a named preset
  only reports credentials when its own env vars are set; the singleton is still
  honoured for minimax via `MINIMAX_API_KEY_ENV == CUSTOM_PROVIDER_API_KEY_ENV`,
  and the D4 `NOUS_API_KEY` back-compat alias for nous is preserved. Surfaced by
  the Thermos review (Blocker #1). Regression tests:
  `tests/agents/test_openai_compatible_gateways.py::test_indexed_pair_does_not_grant_minimax_credentials`,
  `::test_singleton_still_grants_minimax_credentials`,
  `::test_nous_back_compat_alias_still_grants_nous_credentials`
- `_validate_logfire_token` now distinguishes Logfire **write tokens** from
  API keys and probes the right endpoint. Write tokens (`pylf_v{N}_{us|eu}_…`
  — the regional, base64-payload credentials the Logfire SDK accepts for
  OTLP ingestion) were being rejected with HTTP 302 because the validator
  only probed the management REST API (`/api/v1/projects`), which redirects
  write tokens to the auth page. The fix: `_resolve_logfire_probe()` routes
  `pylf_v{N}_{us|eu}_` to the regional `/v1/info` host
  (`https://logfire-{us,eu}.pydantic.dev/v1/info`) — the same probe the
  Logfire SDK uses internally. API keys still probe the management endpoint.
  Tests: `test_auth_logfire_validator_probes_eu_write_token`,
  `test_auth_logfire_validator_probes_us_write_token`,
  `test_auth_logfire_validator_rejects_expired_write_token`
- `.env` writes no longer wrap token + project values in single quotes.
  `python-dotenv`'s `quote_mode="always"` produced `MERGECRAFT_LOGFIRE_TOKEN='pylf_v2_eu_…'`,
  which broke grep workflows operators rely on to confirm a fresh save.
  Tokens (`[A-Za-z0-9_-]+`) and project labels (`[A-Za-z0-9_-/]+`) are safe
  unquoted, so `_write_env_value` now calls `set_key(..., quote_mode="never")`.
  Test: `test_auth_logfire_writes_token_unquoted`
- `mergecraft tracing logfire enable` now resolves the token + project via the
  same precedence layer used by every other mergecraft config command:
  **flag > env > prompt**, applied independently per key. With neither flag on
  the CLI, the command reads `MERGECRAFT_LOGFIRE_TOKEN` / `MERGECRAFT_TRACING_PROJECT`
  from `.env` (loaded into `os.environ` by `main()`'s `_load_local_env()`) and
  skips the prompt; a partial `.env` (token present, project absent) prompts
  only for the missing project; an explicit `--token` / `--project` always wins
  over the env value. The token still goes through `_validate_logfire_token`
  regardless of source (re-validating a stale env token is the whole point of
  the probe — the 302/expired cases are caught here). Tests:
  `test_tracing_logfire_enable_reads_token_from_env_when_flag_omitted`,
  `test_tracing_logfire_enable_flag_overrides_env_token`,
  `test_tracing_logfire_enable_prompts_only_missing_project_when_token_in_env`,
  `test_tracing_logfire_enable_validates_env_token_and_rejects_expired`
- `mergecraft config tracing` now reports `enabled: true` immediately after
  `mergecraft auth logfire` (or `tracing logfire enable`) writes to `.env`.
  Root cause: the CLI's `main()` did not load `.env` into `os.environ`, so the
  precedence layer saw an empty environment for `MERGECRAFT_LOGFIRE_TOKEN` /
  `MERGECRAFT_TRACING_PROJECT` even when the file held them. Fix in
  `src/mergecraft/cli/app.py` — `_load_local_env()` calls `python-dotenv`'s
  `load_dotenv(..., override=False)` so real env (CI, shell, GitHub Actions)
  wins and missing keys are populated from the file. The loader is silent on
  a missing `.env` (CI sandboxes, fresh checkouts)
- `_validate_logfire_token` now rejects HTTP 302 responses instead of saving
  the bearer anyway. Logfire's `GET /api/v1/projects` returns 302 to the sign-in
  URL when the bearer is missing or expired; previously the validator treated
  the redirect as "saving anyway" and the operator walked away with a saved
  token that never produced a span silently. The probe now uses
  `httpx.Client(follow_redirects=False)` and explicitly refuses any 3xx
  response (401/403 still reject; 5xx still warn-and-save). Tested in
  `tests/cli/test_auth_logfire_cmd.py::test_auth_logfire_validator_rejects_302_redirect`
  and `tests/cli/test_auth_logfire_cmd.py::test_tracing_logfire_enable_rejects_302`
- `auth logfire` `--help` no longer renders `` `` `` `` as literal
  four-backticks. The docstring's ``[tracing]`` was parsed by Rich
  (`rich_markup_mode="rich"`) as a markup tag and the bracketed text was
  consumed, leaving a four-backtick artifact. The docstring is now a raw
  string (`r"""..."""`) with ``\[tracing]`` escapes so Rich renders the
  brackets literally. The runtime warning for a missing `[tracing]` extra uses
  `console.print(..., markup=False)` to keep the install command verbatim.
  Test: `test_auth_logfire_help_does_not_emit_unbalanced_backticks`
- Bump `aquasecurity/trivy-action` from `v0.33.1` to `v0.36.0` (SHA
  `ed142fd0`). The pinned `v0.33.1` defaults to Trivy `v0.65.0`, whose
  release tag was deleted from `aquasecurity/trivy`; the action's
  install script resolves the version from the GitHub API (success) then
  downloads the asset (HTTP 404), failing the `SBOM + vulnerability scan`
  job deterministically on every `pre-0.0.1` push since the T1-reconcile
  commit. `v0.36.0` defaults to Trivy `v0.70.0`, which is still
  published. Two-line change to `.github/workflows/ci-cd.yml`.

### Added

- `feat(tracing): one trace_id per run + OTel context bridge` — every span
  emitted by a single `mergecraft diff-review` run shares one Logfire trace;
  the OTel context is propagated so any nested OTel auto-instrumented
  operation inherits the same trace. `TraceEvent.trace_id` is the new
  per-run Logfire/OTel trace identifier (resolved once per process via
  `resolve_trace_id()` in `src/mergecraft/tracing/tracer.py` with the env
  precedence `MERGECRAFT_TRACE_ID` → `MERGECRAFT_TRACE_SESSION_ID` →
  `GITHUB_RUN_ID` → `uuid.uuid4().hex`); `session_id` stays the per-process
  correlation id and `turn_id` stays the per-span uuid4. `OTLPSink.write`
  rewrites the OTel `trace_id` on the produced span so Logfire groups by it
  automatically (the `mergecraft.trace_id` attribute is the structural
  fallback). The new `src/mergecraft/tracing/otel_bridge.py` ships
  `attach_trace_context(span)` — a context manager that bridges the OTel
  context so nested OTel auto-instrumented calls (e.g. an `httpx` call
  inside a tool) inherit the run's trace without the caller having to know
  about mergeCraft's tracer. `agents/_stream_consumer.py::consume_stream`
  wraps the per-event handler in `attach_trace_context` when an active
  span is present. `docs/TRACING.md` gains a "One trace per run" section
  describing the precedence and the Logfire-grouping contract. Tests:
  the 11-case RED suite in `tests/tracing/test_trace_id_bridge.py` (10
  green + 1 xfail passing through)
- `feat(tracing): provider.call parent + outbound HTTP spans with URL redaction` —
  each upstream API request becomes a `provider.call` row with the transport family;
  each outbound `httpx` call becomes a `http.client.request` row with inline URL
  redaction (telegram bot tokens, basic auth, query params, bearer headers).
  `agents/{claude,codex,gemini}.py::_stream_event_handler` now opens a `provider.call`
  span on the upstream's start event (`message_start` / `thread.started` / `init`),
  attaches `provider.id` and `provider.transport_family` (`anthropic` /
  `responses_api` / `chat_completions`), and closes the span in LIFO order with the
  existing `llm.call` span on the matching terminal event. The `llm.call` span
  becomes a child of `provider.call`, so the Logfire tree shows one
  `provider.call → llm.call` pair per upstream request. New
  `src/mergecraft/tracing/http.py` ships `instrument_httpx(client, *, tracer=None)`
  — a narrow, idempotent wrapper around the `httpx` `Client.send` /
  `AsyncClient.send` site in `agents/opencode.py` (D8 — only the clients
  mergeCraft constructs; no global monkey patch). The wrapper emits an
  `http.client.request` span with `http.method`, `http.url` (always
  `redact_url`-scrubbed), `http.status_code`, `http.duration_ms`, and
  `http.{request,response}_bytes` (best-effort `len(request.content)` /
  `len(response.content)`); on exception the span is closed with
  `status="error"` and `http.error_class`. New
  `mergecraft.tracing.redaction.redact_url(url)` plus the `REDACTED`
  constant extend the existing D7 redaction boundary to URLs without
  breaking parseability — `urllib.parse.urlparse` round-trips on every
  redacted shape, scheme/host/path/non-token query params survive.
  `agents/opencode.py::_prompt_session` and `::_run` use the existing
  OpenAI-compatible cached-token paths (`prompt_tokens_details.cached_tokens`
  / `input_tokens_details.cached_tokens`) to fold cached input tokens into
  `cost.cache_read` / `gen_ai.usage.cache_read_input_tokens` (matching the
  existing Anthropic `cache_read_input_tokens` /
  `cache_creation_input_tokens` behaviour). New
  `mergecraft.tracing.current_tracer()` resolves the tracer that owns the
  active mergeCraft `Span` for `instrument_httpx` callers that don't have a
  tracer in hand. `docs/TRACING.md` gains a "Provider and HTTP spans"
  section with the parent/child shape, the `instrument_httpx` site list,
  and the URL redaction table. Tests: the 12-case RED suite in
  `tests/tracing/test_http_spans.py` (12 green, including the formerly
  `xfail` `test_provider_call_span_wraps_llm_call_for_anthropic`).
- `mergecraft config tracing` now renders faithfully even when tracing is
  **disabled**, mirroring sevn's `show_tracing_config`. The table gains two
  rows plus a hint block:
  - `local sinks` — `none` when tracing is off, the configured `trace_dir`
    when on (sevn always surfaces the local-sink state so the operator can
    see at a glance that no sink is attached).
  - `trace env` — the `MERGECRAFT_*` env var names currently present in the
    environment (or `(none set)`), so the operator knows exactly which keys
    to set to enable tracing.
  - `next steps` — a hard-coded hint block (sevn: `show_tracing_config`) listing
    `mergecraft tracing logfire enable` (interactive and `--token X --project Y`),
    the local JSONL-file path (`MERGECRAFT_TRACING=true` +
    `MERGECRAFT_TRACING_TO=local_files`), and the generic OTLP path
    (`MERGECRAFT_TRACING_TO=otel` + `MERGECRAFT_OTEL_ENDPOINT`). Printed only
    when disabled; the enabled table is self-explanatory and omits the block.
    Implemented in `src/mergecraft/cli/tracing_cmd.py` (`config_tracing` +
    `render_resolved` + `_print_tracing_next_steps`). Tests:
    `test_config_tracing_shows_local_sinks_none_when_disabled`,
    `test_config_tracing_lists_trace_env_vars_when_disabled`,
    `test_config_tracing_prints_next_steps_when_disabled`,
    `test_config_tracing_omits_next_steps_when_enabled`
- First-class **MiniMax** provider via the existing custom-provider helper
  (#34 / W6). The catalog now enumerates `minimax/MiniMax-M3` as a curated
  alias (`PROVIDERS["minimax"]` in `src/mergecraft/models.py`), reachable
  through the D7 singleton env vars (`MERGECRAFT_CUSTOM_PROVIDER_BASE_URL`
  + `MERGECRAFT_CUSTOM_PROVIDER_API_KEY`) or an indexed pair
  (`MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`). The default
  endpoint is MiniMax's published OpenAI-compatible URL
  (`https://api.minimax.io/v1`, documented at
  <https://platform.minimax.io/docs/api-reference/text-openai-api.md>),
  added to `GATEWAY_PRESETS` in `src/mergecraft/agents/openai_compatible_gateways.py`
  so the slug prefix drives the provider lookup without an explicit
  `<N>` slot. The credential gate honours the D7 singleton and the
  indexed pair; the binary gate short-circuits to `True` for the
  `minimax` provider (same posture as `nous` — the opencode harness
  reads env vars directly, no CLI is required on PATH). A new
  `mergecraft auth minimax` subcommand (`src/mergecraft/cli/auth_cmd.py`)
  mirrors `auth gemini` / `auth nous` / `auth tokenhub` line-for-line:
  prompts with `getpass`, validates against
  `https://api.minimax.io/v1/chat/completions` (the unauthenticated
  catalog endpoint would return 200 for a fake bearer; the probe path
  enforces auth, matching `_validate_nous_api_key`'s shape), then writes
  `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` via `gh secret set`. The validator
  returns `True` on 200, `False` on 401/403, and `True` with a
  `logger.warning` on network errors. A `mergecraft models list` row
  appears for the new catalog entry; the credentials column flips
  `no` → `yes` when the env var is set (convention 7 — the key value
  is never rendered). The pre-existing `opencode/minimax-m2.5` and
  `opencode/minimax-m2.5-free` entries are untouched (D12 additive
  invariant — operators using OpenCode as a proxy still work). No
  Dockerfile change — MiniMax does not require a first-party CLI binary
  (D10 / option ii: route through the existing helper, not a bespoke
  `mmx-cli` harness). README "Authentication" table gains a MiniMax
  row.

### Changed

- **BREAKING** — `with: model:` no longer means "suppress the configured
  model chain" (#37 / W4 / D8). It now becomes the **head** of the effective
  chain; the configured `models:` / `modelFallbacks:` tail is preserved and
  walked on credential miss or retryable failure. A single `uses:
  alexhawat/mergeCraft@…` step now walks the configured chain across
  providers without the consumer reimplementing dual Claude → Codex steps.
  To restore the legacy "use exactly this model" semantics, set the new
  `model_pin: enabled` action input (or `modelPin: true` in
  `.mergecraft/config.yaml`). Workflows that relied on `model:` to disable
  the chain see new fallback behaviour — set `model_pin: enabled` to opt
  back into the old contract. The pinned chain order is the supplied
  `model:` head followed by the configured tail (`effective_model_chain()`,
  `utils/agent_resolve.py`). The `modelExplicit` payload field is retained
  as a back-compat alias for the explicit-pin signal — any consumer that
  branched on it sees the same answer; the new `modelHead` field carries
  the chain head.

### Added

- `mergecraft auth logfire` — operator-facing setup for the Logfire tracing sink
  (issue #56 / D5). The subcommand prompts for a Logfire write token via
  `getpass` and a project label via `typer.prompt`, validates the token against
  `GET https://logfire.pydantic.dev/api/v1/projects` (OTLP/HTTP returns 200 for
  invalid tokens — it accepts and discards — so the REST endpoint is the only
  path that actually enforces the bearer with a real `401`/`403`), then writes
  `MERGECRAFT_LOGFIRE_TOKEN` + `MERGECRAFT_TRACING_PROJECT` into the local
  `.env` (via `python-dotenv`'s idempotent `set_key`) and/or the
  `LOGFIRE_TOKEN` Actions secret via `gh secret set`. `--scope local|github|both`
  selects where the credentials land; the default is `both`. The `[tracing]`
  extra check is non-blocking — the command warns when `logfire` is missing
  but does not auto-install (BYOK / convention 5). New env var
  `MERGECRAFT_TRACING_PROJECT` plumbed through the precedence layer
  (`src/mergecraft/cli/tracing_precedence.py`) and the sink factory
  (`_resolve_logfire_project` in `src/mergecraft/tracing/exporters.py`) so the
  project label becomes the `x-logfire-project` header at runtime
- `mergecraft tracing logfire enable|disable` — non-interactive counterpart to
  `auth logfire`, symmetric with `sevn tracing logfire enable|disable` (sevn
  `specs/04-tracing.md`). `enable --token X --project Y [--scope local|github|both]`
  validates the bearer against the same Logfire REST probe and persists the
  token + project label via the same writers used by `auth logfire`; `disable`
  clears the local `.env` keys via `set_key` with an empty value and removes the
  `LOGFIRE_TOKEN` Actions secret via `gh secret delete` (a missing secret is
  treated as success — the post-condition we want — secret is absent — already
  holds). Both commands reuse `_set_gh_secret`, `_validate_logfire_token`,
  `_write_env_value`, and the local-env loader from `cli/app.py`; the new
  module lives at `src/mergecraft/cli/tracing_logfire_cmd.py`. Tests in
  `tests/cli/test_tracing_logfire_cmd.py` (10 cases covering the four validators
  × scope permutations and the missing-secret idempotency)
- Codex CLI custom OpenAI-compatible provider passthrough + multi-provider surface
  (#71 / W3). `codex.py::write_mcp_config()` now emits Codex CLI 0.146's
  `[model_providers.<id>]` TOML blocks (`base_url` / `env_key` / `wire_api =
  "responses"`) for every configured provider, so Codex can route to Nous,
  TokenHub, MiniMax, OpenRouter, or any self-hosted OpenAI-compatible gateway
  without a config fork. The shared resolver in
  `src/mergecraft/agents/openai_compatible_gateways.py` returns a
  `dict[str, ProviderRecord]` keyed by provider id, populated from two surfaces:
  the singleton back-compat alias (`MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}`
  → `default` provider) and the indexed multi-provider form
  (`MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>` → `provider_<N>`). Indexed
  pairs win over the singleton when any are set; partial indexed pairs (only one
  half) are silently dropped; numeric gaps are preserved (no renumbering). Two
  new top-level `with:` inputs (`provider_base_url` and `provider_api_key_env`)
  map onto the singleton env vars so the common single-provider case does not
  need `env:` plumbing — `provider_api_key_env` references the env-var **name**
  that holds the key (the resolved value is forwarded silently, never logged).
  The `provider_provenance` fields on `ProviderRecord` (`base_url_env`,
  `api_key_env`) let config writers pass env-var names to the loguru redactor
  (convention 7). The README's new "Custom OpenAI-compatible provider" section
  documents the env-var convention, the `with:` inputs, and a worked
  multi-provider example (#71 closes on this surface; PR #79 shipped the
  OpenCode half — both harnesses now consume the same resolver).
- First-class Nous Research / DeepSeek V4 Flash support (#57). The catalog now
  enumerates `nous/deepseek/deepseek-v4-flash` as a curated alias
  (`PROVIDERS["nous"]` in `src/mergecraft/models.py`), with `resolve` set to the
  catalog slug the opencode harness consumes. The credential gate honours
  `NOUS_API_KEY` as the operator-owned first-class secret and
  `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` as a back-compat alias (D4); the binary
  gate (`_agent_binary_available`) short-circuits to `True` for the `nous`
  provider since the opencode harness reads env vars directly and no CLI is
  required on `PATH` (D5). A new `mergecraft auth nous` subcommand
  (`src/mergecraft/cli/auth_cmd.py`) mirrors `auth gemini`/`auth cursor`
  line-for-line: prompts with `getpass`, validates against
  `https://inference-api.nousresearch.com/v1/chat/completions` (the Portal
  catalog endpoint is unauthenticated and would return 200 for a fake bearer;
  `/v1/chat/completions` enforces auth and is the probe the validator uses),
  then writes `NOUS_API_KEY` via `gh secret set`. The validator returns
  `True` on `200`, `False` on `401`/`403`, and `True` (with a `logger.warning`)
  on network errors — parity with the existing `_validate_gemini_api_key`/
  `_validate_cursor_api_key` paths
- First-class **Nous Portal** and **Tencent TokenHub** providers in the CLI and
  Action. `mergecraft auth nous` / `mergecraft auth tokenhub` store
  `NOUS_API_KEY` / `TOKENHUB_API_KEY`; models `nous/…` and `tokenhub/…`
  (including `tokenhub/hy3` and any TokenHub model id) auto-wire the opencode
  OpenAI-compatible harness without requiring `MERGECRAFT_CUSTOM_PROVIDER_*`.
  Explicit custom-provider env vars still override the named presets
- `meat_python_plus/` — Python port of [boldsoftware/meat](https://github.com/boldsoftware/meat)
  with OpenAI, Anthropic, Nous, and TokenHub (Hy3+) providers; CLI entry
  points `meat-py` / `meat_python_plus`
- Meat reading-diff harness prototype (#60 spike). `src/mergecraft/utils/meat_harness.py`
  ships `run_meat_harness(...)` — a typed, pure-boundary entry point that takes
  a unified diff, invokes `meat -json` as a subprocess with a bounded timeout,
  parses the pinned wire format (`smart_diff`, `summary`, `input_tokens`,
  `output_tokens`, optional `elision`), and returns a `MeatHarnessResult` whose
  `raw_diff` field is the input diff byte-for-byte on every code path. Trust
  gate (D7), opt-in flag (convention 7), shell-disabled gate (D7), and
  missing-binary skip (D13) are enforced inside the harness so every future
  caller inherits them. The harness never reads, logs, or stores the credential
  value (convention 8); the credential is referenced by env-var name only. Every
  failure branch (non-zero exit, malformed JSON, timeout, missing binary, gate
  tripped) degrades to the raw diff with a named `skip_reason` — a missing
  optional tool never fails a review. `tests/utils/test_meat_harness.py` carries
  the W1 contract suite (17 passing, 1 `@pytest.mark.integration` smoke test
  skipped when `meat` is not on PATH). `docs/meat-spike.md` publishes the W2
  measurements and the spike's qualified-conditional recommendation
- Operator-runnable measurement script at `scripts/measure_meat_corpus.py` that
  extracted the corpus diffs, time the harness subprocess boundary, and invoke
  the real `meat -json` once per corpus diff. The script is the reproducible
  artifact behind the spike report's tables; the four D10 measurements (token
  delta, cold/warm latency, cost, fidelity) are blocked on the operator LLM
  credential and the script is the path to producing them on rerun
- Reviews now check *how* a change was produced, not only the diff. Eight named
  trajectory checks read the tool calls mergeCraft mediated and report a file
  modified but never read, a tool error that was never retried, edits with no
  verification after them, an identical retry after a failure with nothing read
  in between, a command that failed and never passed, a repeated call loop, an
  unusually broad edit, and a run that did work and never signalled completion.
  Each carries a severity and a recommended action, and lands in the merge
  evidence packet's finding list — so `decide_approval()` weighs them like any
  other evidence rather than through a second gate. Checks stay **silent when
  the evidence is absent**: mergeCraft only sees the calls it mediates, so a
  driver whose reads never cross MCP yields "unknown", not "unread". Inline
  slots go to code findings first. `PACKET_SCHEMA_VERSION` moves to `1.4.0` for
  the new `trajectory` section (#43, #49)
- Gate outcomes now resolve to a closed action vocabulary — `auto_merge`,
  `block`, `request_changes`, `require_human_review`, `require_more_tests`,
  `quarantine`, `escalate` — instead of a free-form verdict. The five example
  policies from #46 ship as defaults: a schema failure blocks, a
  changed-unread-file asks for changes, a low-risk passing change merges, a
  tool-loop asks for more tests, and a high-risk migration asks for human
  review. `decide_action(packet)` consumes the typed packet — never re-derives
  evidence — and the call site that wires it into `build_run_packet` is the
  only place the action reaches the run. `autoMergeEnabled` remains `False`
  (D11); `auto_merge` is an action name, never an enabled gate. Every new
  gate defaults to `shadow` (D12); a typo'd value widens to `shadow`, never
  to `enforce`. `PACKET_SCHEMA_VERSION` moves to `1.5.0` for the typed
  `Decision.action` / `decided_by_action` / `mode` fields (#46)
- Shadow mode records the predicted action as a JSON-Lines breadcrumb beside
  the packet (`merge-evidence-shadow.jsonl`) without enforcing it. The
  `disagree_with_outcome` reporter groups predicted vs. actual outcomes by
  blast-radius lane and rule id; rows are key/value-shaped so a CLI can
  aggregate them once outcomes are pulled from PR events. A recorder with no
  reachable caller is the #96 failure mode, so the runtime call-site test
  (`tests/test_runtime_call_sites.py`) pins both `decide_action` and
  `record_shadow_prediction` to modules the Action orchestrator reaches
  (#50)

### Documentation

- Document the Nous Research provider in `README.md` (Authentication table
  row for `nous` / `deepseek/deepseek-v4-flash`, a worked `.mergecraft/config.yaml`
  example block, and a `mergecraft auth nous` CLI row) and add a
  cross-reference note in `docs/ANALYZERS.md` pointing at the README's
  Authentication section so the analyzer-catalog page stops looking like the
  surface for provider configuration. `Dockerfile`, `action.yml`, and
  `.github/workflows/mergecraft.yml` are deliberately unchanged (PR #120
  already mirrors the sevn cascade correctly). (#57)

### Security

- The `github-issue-triage` skill now reads issue bodies and comments only through the
  new sanitizing fetcher (`scripts/fetch_issue_safe.py`, queue sweeps via
  `fetch_open_issues.py`); each untrusted field is fenced with a nonce-delimited block
  and best-effort scanned, while maintainer-authored fields (`OWNER`/`MEMBER`/`COLLABORATOR`)
  pass through unfenced on a per-field basis
- `scripts/post_issue_update.py` rejects plans that are off-allowlist before any
  `gh` mutation runs: labels must match the live repo label set, assignees must come
  from the pinned roster in `--skw-toml`, public comments must match one of the two
  closed-set SKILL.md templates, and a `close: true` requires an attached decision
  object with `should_close: true`
- `.llmignore/blocked/` quarantines any untrusted field that the scanner flagged,
  keeps raw bytes out of agent context, and is gitignored so it never reaches a PR

### Changed

- **BREAKING** — an unrecognised `analyzers:` Action input value now resolves to
  `untrusted-only` instead of `auto`, and says so at `warning` level. Previously
  any typo was silently rewritten to `auto`, which on a trusted event selects the
  whole catalog: the input that looked strictest was the one that did nothing. A
  misspelled value now narrows selection (57 shipped manifests → 18 on a trusted
  event) rather than widening it, so the failure mode is missing coverage you can
  see in the skip rows instead of coverage you only thought you had. Spelling a
  valid value — `off`, `auto`, `full`, `untrusted-only` — is unaffected, and an
  absent input still means `auto` (#38)
- **BREAKING** — `analyzers: auto` under `pull_request_target` and fork-head pull
  requests now *means* trust-aware selection, resolving to `untrusted-only`
  rather than being trust-blind. On the catalog as shipped today this changes
  which analyzers run **not at all**: the untrusted trust tier already excluded
  every `trust: trusted` manifest on those events, and the one remaining
  `repo-native` manifest is exempt (see below). What changes is the contract —
  any future `repo-native` analyzer that declares `trust: untrusted` will be
  withheld on those events instead of resolved against a PR-authored working
  tree. It is recorded as breaking because the meaning of an existing input
  value changed, not because current behaviour did (#38, D8)

### Added

- Analyzer findings can now be published as GitHub code-scanning alerts, so
  mechanical signal stays readable when the review narrative is thin or when
  findings overflowed the inline comment budget. Opt in with
  `sarif_upload: enabled` (or `analyzers.sarifUpload: true` in
  `.mergecraft/config.yaml`) plus `security-events: write` on the job; with the
  flag unset the run makes no extra API call at all. mergeCraft has exported
  SARIF since the catalog shipped, but the only caller was the offline
  `mergecraft analyzers export --sarif` command, so no Action run ever produced
  a document. Uploads carry only findings from catalog analyzers this run's
  trust tier, `shell:` policy and `analyzers:` mode actually admitted —
  re-checked at upload time against the same predicates the pipeline uses — and
  every message, evidence line, remediation and autofix is redacted while still
  a typed `Finding`, before SARIF is built. CI-sourced findings (which carry
  truncated pipeline log excerpts) and agent narrative are never uploaded. The
  set is the clustered, placed one, so cross-tool duplicates arrive as one
  alert; it is deliberately *not* truncated at the inline comment budget,
  because the overflow is what this surface exists to show. A rejected upload —
  missing permission, no code scanning on the repository, transport error — is
  logged at `warning` and the review still completes: SARIF is complementary
  evidence, never a gate (#39, D13/D14)
- Hardened workflows can now ask for trust-aware analyzer selection explicitly:
  `analyzers: untrusted-only` runs only analyzers that need no secrets, no
  network, and no PR-authored command construction. It applies two gates at
  once — manifest selection is evaluated at the `untrusted` trust tier, *and*
  analyzers needing repo-provided tooling are withheld whatever `shell:` is set
  to, which the trust tier alone does not do. On a trusted event that narrows
  the catalog from 57 shipped manifests to 18. Everything excluded is a skipped
  row with a named reason naming the axis that caused it, never a failure, and
  `run_static_checks` remains withheld under `shell: disabled` regardless of the
  mode. The shipped `mergecraft-hardened.yml` example now sets it explicitly, and
  `docs/ANALYZERS.md` gains a generated mode axis computed from the live
  predicates (#38)
- `agentsec` now runs under `shell: disabled` and under `analyzers:
  untrusted-only`, where it was previously withheld. It declares
  `runtime: repo-native` — the marker for "resolves against tooling the repo
  supplies" — but it is mergeCraft's own agent-security policy engine: it is
  special-cased before the repo-binary preference is ever consulted and executes
  in-process, with no subprocess and no argv, so no PR-authored command can run
  through it. Withholding it bought no safety and cost hardened consumers the
  one analyzer most relevant to `pull_request_target`: the one that reads
  `.mcp.json`, `CLAUDE.md`, `AGENTS.md` and skill files as data. It is a named
  exception in `IN_PROCESS_ANALYZER_IDS` with a test asserting it really does
  resolve without repo-provided tooling, not a widening of the runtime rule
  (#38, follow-up to #35)
- Hardening your workflow no longer costs you every mechanical check. A repo
  running `pull_request_target` with `shell: disabled` previously got **no**
  analyzer coverage at all: one boolean withheld mergeCraft's own pinned catalog
  alongside the repo-declared `staticChecks` it was meant to withhold. Those are
  now separate decisions. `managed` and `container` analyzers run — 33 of the 57
  shipped manifests are eligible, whose argv comes verbatim from a manifest
  mergeCraft ships — while `repo-native` manifests are withheld with a named
  reason each, since they exist to run *your* tool against *your* config. On that
  path a binary the repo provides can no longer stand in for the pinned managed
  one, closing a way a PR could have steered an otherwise-safe analyzer by
  committing `.venv/bin/<tool>`. `run_static_checks` stays withheld
  unconditionally and its gates still report `declared-but-cannot-run`; fork,
  untrusted-tier, and offline `diff-review` behaviour is unchanged. The full
  runtime × shell × trust matrix is generated into `docs/ANALYZERS.md` (#35)
- A gate your own CI already proved no longer reports `unavailable`. The Action
  image has no `make`, no repo venv, and none of your pinned toolchains, so a
  repo-native gate could only report that it judged nothing — even when a
  `Verify (…)` job had just run the identical command on the same commit.
  Declaring `ciEvidence.gates` in `.mergecraft/config.yaml` (a gate name mapped
  to the exact GitHub check-run name that proves it) rewrites that row to a new
  `satisfied-by-ci` status naming the check run and its URL. Nothing is inferred:
  a check run merely *named* like a gate proves nothing, because a pull request
  can add a workflow with any name it likes, and with no `ciEvidence` block
  mergeCraft never reads your check runs at all. Only a passing declared run may
  substitute — a declared run that failed leaves the honest row in place and is
  reported as a finding instead — and a gate that actually ran in the review
  always outranks any CI claim about it (#36)
- CI outcomes are now recorded as structured findings, not just narrated. Each
  clustered failure from `analyze_ci_failures`, plus any failing check run
  mapped to a declared gate, becomes a `source: ci` finding on the run and is
  carried into the merge evidence packet. The blame verdict travels with it:
  a failure attributed to the diff is `Major` / `introduced_by_pr: true`, while
  a flaky or pre-existing one is `Minor` / `introduced_by_pr: false`. Since every
  consumer of findings is monotone in blocking severities, that is what makes
  "reported, not blamed" mechanical rather than a matter of wording — a flaky
  pipeline cannot block a clean pull request (#36)
- SARIF your CI already produced can be read back as review evidence. Naming
  workflow artifacts under `ciEvidence.sarifArtifacts` ingests their SARIF
  through the same parser the analyzer catalog uses. Default is empty, in which
  case no artifact API call is made; ingested results are reported at a
  non-blocking severity with `introduced_by_pr: unknown`, since SARIF from
  another pipeline describes the tree rather than this diff (#36)
- Codex reviews inside a container runner now fail loudly instead of silently.
  Codex CLI runs its own bubblewrap sandbox; inside a Docker container action
  that is already namespaced it cannot create a nested namespace, so every call
  died before doing any work — and `continue-on-error` made that look like a
  review that simply found nothing. mergeCraft now recognises the failure and
  returns the remedy with it. New `codex_sandbox: danger-full-access` Action
  input (env `MERGECRAFT_CODEX_SANDBOX`) skips the redundant nested sandbox on
  runners that are already ephemeral and isolated. mergeCraft never selects it
  on its own, an unrecognised value is ignored rather than forwarded, and the
  `shell` / `push` controls remain the security boundary either way (#70)
- The eval bank now actually catches regressions. A case can record the
  findings, run outcome and trust tier from a merge evidence packet
  (`mergecraft eval add --from-packet`), and replay re-decides it with the
  current `decide_approval()` instead of asking an operator to type the verdict
  in. Before this a promoted case produced a test whose only unconditional
  assertion was a tautology, so it passed in CI no matter what the gate did.
  Seeded with the three merge-gate failures issue #75 shipped: agent prose
  outvoting a blocking finding, a crashed run staying permissive, and an
  untrusted run self-approving. Cases without recorded evidence keep their old
  behaviour. Also fixes `mergecraft eval gate` reporting every promoted case as
  unpromoted, and widens the bank's verdict vocabulary, which had drifted from
  what `decide_approval()` actually emits (#44, #51)
- Review quality can now be measured. `mergecraft eval score` grades a run's
  findings against a frozen benchmark baseline by **locating** issues — a
  baseline issue counts as found when a reported finding overlaps its line range
  in the same file, not when the two rows match structurally. Equality scoring
  failed a run for rewording a finding it genuinely found, and could never pass
  against a corpus carrying its own `rule_id` and `fingerprint`. Severity
  vocabularies are reconciled (`high`/`medium` → `Major`/`Minor`) so agreement is
  reported honestly instead of always reading 0%. `make bench-review` now takes
  `REVIEWBENCH_DIR=...`, so the corpus can live outside this repo, and
  `make eval-gate` checks the eval bank still parses against the current schema
  — the durable cases can no longer rot in silence (#30, #51)
- The reviewer's own `Critical` and `Major` findings are now double-checked
  before they are published, not just the ones its linters and CI produced. A
  second read-only agent re-reads the cited code and returns confirm, downgrade,
  or drop; a dropped finding is written to `## Withdrawn review findings` in the
  learnings file, so the same false positive is never raised again. Findings
  already refuted there are skipped without being re-checked, and the number of
  checks per run is capped at the repo's existing `analyzers.inlineBudget` —
  `Critical` findings are checked before `Major` ones, and there is no new knob
  to configure. Beyond that cap the extra findings publish unchecked
- The verifying agent is now pinned and auditable. Its model, provider, judge
  version, and rubric version are recorded with every verdict, its model is
  fixed per provider so a changed default cannot silently change what gets
  published, and it grades against five yes/no questions about the code rather
  than a "quality" score. It refuses to run before your analyzers and repo gates
  have — it is a second opinion on top of the deterministic checks, never a
  replacement for them — and on a high blast-radius change (migrations, auth,
  secrets, irreversible infra) it cannot retire a finding on its own (#45)
- Optional `tracing:` block on `.mergecraft/config.yaml` plus a local JSONL
  sink (`type: jsonl_file`) under `src/mergecraft/tracing/`. Tracing is
  **off by default** (convention 9) — a repo that does not declare the
  block sees identical behaviour, identical performance, and zero egress.
  The block accepts the shorthand `to: local_files` (D9), normalises it
  into the canonical `sinks` list at parse time, and ships redaction that
  reuses `analyzers/redact.py` and `utils/secrets.py` so `ghp_…` / `sk-…`
  values and a deny-key list (`authorization`, `cookie`, `api_key`,
  `secret`, `password`, `access_token`, `refresh_token`, `id_token`,
  `bearer_token`, `auth_token`) cannot reach any sink (D7). The local
  sink rotates daily (`YYYY-MM-DD.jsonl`), caps `attrs` at 64 KiB with a
  truncation marker (D8), and purges files older than `retentionDays`
  (default 30). Remote exporters (`logfire`, `otel`) and the optional
  `tracing` extra land in Batch D (W8); W2 ships the surface and the
  structural guarantee that no sink is ever reachable without going
  through the redaction boundary. `docs/TRACING.md` carries the config
  schema, sink types, the redaction guarantee, the retention rule, and
  the D15 note that enabling a remote sink exports reviewed-repo content
  (#56, W2)
- `tracing:` block now emits a full per-run span tree at every production
  seam. The W3 RED suite is the contract; W4 wires the emit sites. A
  run is rooted at `mergecraft.run` (with `run_id`, `repo`, `pr_number`,
  `commit_sha`, `workflow_run_id`, `job_id` derived from env or the new
  `correlation` kwarg) and fans out to `mergecraft.prep`,
  `mergecraft.analyzers.pipeline` (each child `analyzer.run` carrying
  `analyzer.id`, `analyzer.exit_code`, `analyzer.findings_count`,
  `analyzer.duration_ms`), `agent.attempt` per fallback entry (with
  `model.id`, `agent.provider`, `agent.mode`, redacted `agent.cli_argv`,
  `model.fallback_index`, `status`), each attempt's `llm.call` (with
  `cost.tokens_in`, `cost.tokens_out`, `cost.cache_read`,
  `cost.cache_write`, `cost.usd` consumed from `AgentUsage` — D11),
  each MCP `tool.call` (`tool.name`, `tool.server`), and
  `mergecraft.publish`. The tracer is **never on the critical path**
  (convention 6) and is a true no-op when `tracing.enabled` is false
  (convention 9). `docs/TRACING.md` gains a "Span tree" section with
  the per-kind attribute table. `usage_entries` stays on `ToolState`
  for backward compat; the W3.5 consumer contract is now satisfied by
  the cost.* attributes on `llm.call` (#56, W4)
- `logfire` and `otel` remote exporters (`OTLPSink`) — one OTLP pipeline
  serving both sink types (D5). Imports of `logfire` / `opentelemetry`
  are lazy and guarded inside the configure branch; with the optional
  `[tracing]` extra uninstalled, `make ci-resume` passes (convention 5)
  and `sink_factory` resolves `logfire` / `otel` to `NullSink` with a
  clear warning (convention 8, no network call). `tokenRef` resolves
  asynchronously against `MERGECRAFT_LOGFIRE_TOKEN` (W7.4); the resolved
  token is held at runtime only — it never appears in config dumps, YAML
  round-trips, or the `mergecraft config tracing` output (D5).
  `action.yml` exposes `tracing`, `tracing-to`, `logfire-token`, and
  `otel-endpoint` inputs (W7.7) so a consumer wires tracing without
  touching YAML. The CLI adds `--tracing` / `--no-tracing`,
  `--tracing-to`, `--trace-dir`, `--logfire-token`, `--otel-endpoint` on
  `mergecraft diff-review`, plus `mergecraft config tracing` (resolved
  settings with the token redacted) and `mergecraft traces <run-id>`
  (read back a local run). The precedence is **CLI flag > env var >
  `.mergecraft/config.yaml` > default (off)** (W7.6). The full
  reference lives in `docs/TRACING.md` and the D14
  `actions/upload-artifact@v4` snippet with `if: always()` is documented
  in both `README.md` and `docs/TRACING.md` (#56, W8).
- Per-tool / per-LLM spans now stream in from the agent drivers. The
  Claude, Codex, and Gemini drivers switched from
  `subprocess.run(..., capture_output=True)` to `subprocess.Popen` with
  line-buffered reads through a shared NDJSON consumer
  (`src/mergecraft/agents/_stream_consumer.py`) so each parsed event
  drives a `tool.call` or `llm.call` span via the W4 tracer. Opencode
  streams its CLI fallback path but degrades to run-level spans because
  its event shapes are partial (W0.5); Cursor stays on its HTTP-polling
  read path (W6.4). Failure diagnosis (D13, PR #16's
  `_build_claude_failure_error` and the user-namespace bwrap hint) is
  unchanged, idle detection (`utils/activity.py`) is unaffected
  because `consume_stream` echoes lines back to stdout, and malformed
  events are skipped and counted rather than raised against. `docs/TRACING.md`
  gains a per-driver table pinning the version each driver was tested
  against and the resulting coverage. (#56, W6)

- Reviews now actually emit a Merge Evidence Packet. Every run that reviews a
  pull request writes one versioned JSON record of the findings, the analyzer
  checks that ran, the blast-radius lane, the agent's self-assessment, and the
  structural decision — the auditable answer to "why was this blocked?". The
  packet lands under `RUNNER_TEMP` (override with `MERGECRAFT_EVIDENCE_DIR`),
  outside the checkout so it can never be swept into a commit, and the Action
  exposes its path as the new **`evidence_packet`** output for
  `actions/upload-artifact`. `mergecraft diff-review` emits one too, with
  `--evidence-packet PATH` to place it. `PACKET_SCHEMA_VERSION` is unchanged at
  `1.3.0` — wiring a consumer is not a shape change (D7). Auto-merge stays
  disabled; the packet reports a lane, it does not act on one (D11) (#96, #47)

- Re-reviews now read only what changed since the last mergeCraft review. A
  re-review gets a second patch covering the commits pushed since the review it
  last posted, so a push to a large PR no longer pays for a full re-read. The
  patch is offered only when a prior reviewed commit is recoverable and the range
  is non-empty; otherwise the re-review works from the full diff as before
- Review threads for findings the new commits fixed are now closed on the next
  re-review, instead of sitting open asking for a change that already landed. A
  thread closes only when mergeCraft raised it, nobody else replied to it, the new
  commits touched its file, and the fresh review did not raise it again

- Merge-lane policy maps blast radius to a typed packet signal: low changes are
  `eligible`, medium changes are `assisted`, and high changes are `forbidden`.
  `MergeEvidencePacket.blast_radius` now validates `BlastRadiusClassification`,
  with `PACKET_SCHEMA_VERSION` bumped to `1.2.0`; repository overrides remain
  additive per category and `autoMergeEnabled` remains disabled (#42, W5).
- Blast-radius classifier: `classify_blast_radius()` maps changed paths and
  optional diff text to typed low, medium, or high merge lanes using a shipped
  declarative rule set with additive per-category overrides. The pure classifier
  covers migrations, sensitive code and config, generated files, public APIs,
  dependencies, untested source, and irreversible infrastructure (#48, W6).
- File-backed Failure Memory and Eval Bank (#51, W11): a local, file-backed
  case store under `evals/cases/` (D13) with `mergecraft eval add | list | replay`
  CLI subcommands. The `Case` model is validated against the merged evidence
  packet's verdict vocabulary (`auto_merge`, `block`, `request_changes`,
  `require_human_review`, `unavailable`, `neutral`) and **embeds**
  `mergecraft.utils.learnings.LearningProvenance` as its provenance record
  (D5, cross-file contract from `docs/test-plans/cross-file-deps.md`). The
  pure core lives at `src/mergecraft/evals/store.py` (parse / render /
  list / replay / diff — no I/O at import time, no `os.environ` reads); the
  thin I/O shell wraps it at `src/mergecraft/cli/eval_cmd.py`. Replay is
  deterministic: `replay_case(case, current_decision)` returns a
  `ReplayDiff` with `passed` / `regression` / `blocked` status; the CLI
  exits `2` on a regression so a CI loop can latch on drift. The CLI is
  non-interactive (all flags). The bank is local — no database, no hosted
  service — and tests use the `synthetic` ID prefix so the committed
  corpus never looks like a real historical failure. User-facing manual
  at `docs/eval-bank.md`. The bank is for *reviewer learning*; it does not
  enable auto-merge (D11).
- Promote-to-permanent-test workflow over the bank (#44, W12): a `mergecraft eval
  promote <case-id>` CLI subcommand writes a pytest test under `tests/evals/permanent/`
  that re-runs the case against the current code via `replay_case`. The generated
  test embeds the case payload (round-tripped through `Case.model_validate_json`) so
  it carries no bank-disk dependency; the running code's verdict is wired via
  `MERGECRAFT_PERMANENT_CURRENT_DECISION`. The merge-evidence packet's `evals`
  section is now a typed `list[EvalMetadata]` (`schema_version` bumped to `1.2.0`,
  additive minor) — each row is a lightweight summary of a replay run; the full
  case continues to live under `evals/cases/<case_id>.md`. `mergecraft eval list`
  gains first-class filters for `--category=rejected` and `--category=reverted`
  (two distinct failure modes — operator rejected pre-merge, was reverted
  post-merge). The `create_pull_request_review` MCP tool logs a one-line
  `logger.info` suggestion to capture the run as a case when the action input
  `suggest_eval_add` is `true`, the trust tier is `trusted`, the trigger is a
  re-review (not a fresh PR), and the run produced no positive findings — the log
  is informational; the agent never auto-adds. `docs/eval-bank.md` gains a
  "Workflow: rejected & reverted PRs" section; `docs/REVIEW-DOCTRINE.md` gains a
  "Failure memory" section that cross-references the bank. The bank does not
  enable auto-merge (D11); promote produces tests, not gates.
- Merge Evidence Packet: every run emits a versioned, structured
  `MergeEvidencePacket` (`src/mergecraft/evidence/packet.py`) that composes
  the existing `Finding` model and derives its JSON Schema from the Pydantic
  models (no hand-written schema). `PACKET_SCHEMA_VERSION = "1.1.0"` is
  required and pinned; `tests/evidence/test_packet_schema.py` enforces the
  contract. The packet is assembled by `build_packet()` (pure) and emitted
  by `write_packet()` (I/O shell) under `mergecraft.evidence.{build,emit}`,
  and ships with `docs/evidence-packet.md` as the field reference (#47, W1).
  W2 (#41) adds the `self_assessment: SelfAssessment | None` section as a
  sibling of `decision` and bumps the schema to `1.1.0` (additive minor).
- Merge-evidence packet `self_assessment` row carries the agent's
  `approved` boolean + the reviewed commit SHA — distinct from the
  structural `decision` verdict. `mergecraft.evidence.build._coerce_self_assessment`
  translates the legacy `ApprovalRecord` shape (`would_approve` /
  `sha`) into the packet row, so existing `mcp/review.py` call sites keep
  working unchanged. The legacy `tool_state.approval` surface is preserved
  for backward compatibility (#41, W2.1).
- `decide_approval()` overload in `src/mergecraft/agents/gates.py` now
  accepts a `MergeEvidencePacket` as the first positional argument and
  returns a `Decision` row whose `verdict` is authoritative over the
  recorded `self_assessment` (#41, W2.2, W2.3). The legacy `list[Finding]`
  overload is unchanged and `report_status_checks()` keeps working — the
  function remains a pure function of typed findings, run state, and trust
  tier; the packet overload adds the self-assessment split on top. The
  `#41` hard rule — a self-assessment-only run cannot reach `auto_merge`
  — is pinned by
  `tests/evidence/test_self_assessment.py::test_self_assessment_alone_blocks_auto_merge`.
- `mergecraft diff-review --json PATH` writes structured findings validated against
  the `Finding` schema for offline benchmark/scoring workflows (#30)
- Optional `mergecraft[harbor]` extra with `MergecraftReviewAgent` — installs
  mergecraft via `uv tool install` and runs `diff-review --json` inside Harbor task
  environments for ReviewBench evals (#30)
- `evals/README.md` documents the benchmark layout; frozen task corpus tracked in
  [tripll#64](https://github.com/sevn-bot/tripll/issues/64)
- `make bench-review` stub runs Harbor when `evals/reviewbench/` exists; exits 2
  with a tripll#64 pointer until the corpus lands (#30)
- `.mergecraft/config.yaml` accepts an ordered `models` list and optional
  `modelFallbacks` map for per-slug backup chains; the legacy scalar `model` key
  still works unchanged (#14)
- `mergecraft models list`, `models set`, and `models show` CLI commands for
  inspecting the curated catalog, writing an ordered preference list, and
  previewing which slug would run (#14)
- Runtime model chain resolution: skip entries without credentials, advance on
  retryable provider failures, and log selected/skipped slugs at Action-visible
  levels (#14)
- Reviewers can list GitHub check suites for a commit via `list_check_runs` and fetch
  one suite by id via `get_check_suite`, then pass the id to `get_check_suite_logs`
  (#8)
- Configured `staticChecks` now report a `declared-but-cannot-run` row when the gate
  cannot execute in this environment (for example `shell: disabled`), instead of
  disappearing silently (#8)
- `.mergecraft/config.yaml` accepts `commentInvocationAllowlist`, a comma-separated
  list of extra GitHub logins (release bots, automation) allowed to invoke by comment
  despite an `author_association` outside `OWNER`/`MEMBER`/`COLLABORATOR`. It does not
  re-open comment invocation under `pull_request_target` and does not override the
  fail-closed default when the association field is missing (#72)
- Per-run nonce fence (`mergecraft.utils.fence`) wraps every untrusted PR prose field
  — PR title, PR body, `eventInstructions`, `previousRunsNote`, review/issue comment
  bodies, commit messages, patch headers — with a closing delimiter bound to a CSPRNG
  nonce; attacker-supplied delimiters and nonce tokens inside the body are rewritten
  to neutral placeholders before they reach the reviewer. Trust tier per field is
  derived from `analyzers/trust.py::derive_trust_tier` so MEMBER/OWNER prose can pass
  through unfenced where the source is trusted (#73)
- Per-entry provenance record (`LearningProvenance` in `mergecraft.utils.learnings`)
  names the run id, PR number, source field, author login, author association, trust
  tier, and timestamp on every persisted learning entry; new entries land in a
  `## Staging` section by default with a provenance comment line, and only entries
  whose author association is `OWNER`/`MEMBER`/`COLLABORATOR` may be promoted when
  the new opt-in `autopromoteLearnings: true` config flag is set. Quarantined entries
  never reach the reviewer prompt and the active section is fenced at seed time via
  the W4 nonce fence, so an entry carrying a forged closing delimiter cannot
  restructure the instruction block (#74).
  **BREAKING:** the default for new learning entries is now fail-closed — entries
  persist into the staging section instead of the active section unless
  `autopromoteLearnings: true` is set in `.mergecraft/config.yaml` (D10 of
  `.ignorelocal/waves/issues-security-trust-boundary-wave-plan.md`).
- New `mergecraft learnings` CLI subcommand with `influence`, `active`, and `staging`
  listings; `influence` reads `.mergecraft/learnings.md` and emits the curated and
  quarantined entries with their provenance records as JSON (audit-friendly) or
  human-readable text (D11, #74 proposal item 5).

### Changed

- Batch B (blast radius) is PR-ready: `MergeEvidencePacket.blast_radius` accepts
  a typed `BlastRadiusClassification` from `classify_blast_radius()`, and the
  packet overload of `decide_approval()` reads it. (This entry previously read
  "populated end-to-end"; that was inaccurate until #96 supplied the runtime
  caller.) The lane policy is advisory — `autoMergeEnabled`
  remains `False` (D11) and the Batch D thermostat in
  `.ignorelocal/waves/issues-merge-evidence-gating-wave-plan.md` owns the
  gate outcome → action map. `make ci` is green on `wave/evi-b-blast`
  (666 passed, 1 skipped, 3 documented pre-existing xfails from the
  security plan's Batch B/W3/W4). `tests/evidence/test_blast_radius.py`
  ships 24/24 passing (#42, #48, B-Final).

### Removed

- Dropped the change-impact (`impactPath`) step from the review prompts. No
  release ever produced that file, so the instruction only spent tokens and
  invited the reviewer to claim it had consulted an artifact that did not exist.
  Change-impact extraction is tracked as its own piece of work (#94)

### Fixed

- The merge evidence packet was never produced. `build_packet()`,
  `write_packet()` and `classify_blast_radius()` shipped across two merged wave
  batches with unit tests but no caller anywhere in `action/`, `cli/` or
  `agents/`, so no run wrote a packet and `blast_radius` could only ever be
  `None`. They are now called from a real run. A regression test walks the
  import graph out from `main.py` and `cli/app.py` and fails if any of the three
  loses its reachable call site — "called somewhere" was not enough, because at
  the broken revision `evidence/emit.py` did call `build_packet()`; nothing
  called `emit.py` (#96)
- `docs/evidence-packet.md` opened by claiming "Every mergeCraft run emits one
  versioned, structured packet" while zero runs emitted one, and stated a
  current version of `1.2.0` against a shipped `PACKET_SCHEMA_VERSION` of
  `1.3.0`. Both corrected, and the document now says where the packet lands and
  how to attach it to a workflow (#96)
- Offline `diff-review` never carried its resolved model onto the tool context,
  so evidence packets from a local review could not attribute findings to a
  model even when one was explicitly selected. A configured or `--model` slug
  now reaches the packet; a run that lets the provider self-select still records
  `(unresolved)`, since mergeCraft has no slug to report (#96)

### Docs

- `docs/REVIEW-DOCTRINE.md` adds a "Green is evidence, not proof" section
  that documents the #41 hard rule (agent self-assessment is recorded but
  never sufficient) and the evidence-weighting table — typed `Finding`s,
  `DeterministicCheck` rows, CI check-runs, `self_assessment` (advisory),
  `decision` (authoritative). Adds an "Honesty about unavailable signals"
  subsection that names PR #17's `staticChecks` vocabulary as the
  precedent (W2.5, #41).
- `REVIEW-CHECKS.md` adds a "Mechanical evidence — what counts" section
  that distinguishes typed findings, deterministic checks, CI check-runs,
  and the agent's recorded self-assessment (advisory only) from the
  packet's `decision` row (authoritative); lists what does **not** count
  as mechanical evidence even when it appears in a check-run summary or
  in the agent's prose (#41, W2.5).
- Rewrite README with a 3-step quickstart and a dedicated Authentication section
  documenting Claude/Codex subscription auth (`mergecraft auth claude` /
  `auth codex`, `CLAUDE_CODE_OAUTH_TOKEN` / `CODEX_AUTH_JSON`) alongside API keys.
- New README section "Comment-trigger authorization" spells out who may start a run by
  comment, what a refusal looks like (no reply posted, one warning line, `unknown`
  trigger), and the reach of each opt-in knob — `allow_pr_target_comments` (action
  input) and `commentInvocationAllowlist` (repo config). `examples/config.yaml` now
  carries a commented `commentInvocationAllowlist` example, and the hardened example
  workflow explains why it declares no comment triggers under `pull_request_target` (#72)
- Add OSS governance files for parity with sevn-bot/sevn: `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`,
  and `.github/ISSUE_TEMPLATE/` (bug report, feature request, security contact link).
- Document the structural approval gate next to `status_checks: enabled`: the
  `mergecraft-approval` conclusion is now a pure function of the typed `Finding`
  list, the run's completion state, and the trust tier — narrative
  (`ApprovalRecord.would_approve`) is recorded as an advisory input only, never
  the sole positive input. The pre-W8 "neutral is non-blocking" framing is
  removed; the hardened example workflow ships a `neutral` ⇒ blocking enforce
  step (#75).

### Changed (BREAKING)

- **`mergecraft-approval` is now structural (D13 — fail closed on incomplete
  runs).** A crashed / timed-out / no-findings run posts `neutral` regardless of
  any recorded `ApprovalRecord.would_approve`. The hardened example workflow's
  enforce step treats `neutral` as blocking; GitHub branch protection must wire
  that step into the merge rule if it relied on the previous "neutral is
  non-blocking" behaviour. `report_status_checks()` consults
  `mergecraft.agents.gates.decide_approval(findings, run_succeeded, tier)`
  instead of `approval.would_approve` (#75).
- **`prApproveEnabled` is inert for `untrusted` tier runs (D14 — no self-
  approval on fork PRs).** `create_pull_request_review` does not send
  `event="APPROVE"` to GitHub when `ctx.trust_tier == "untrusted"` even with
  `pr_approve_enabled=true` and the agent's `approved=true` argument. The
  advisory `ApprovalRecord(would_approve=True, sha=...)` is still recorded so
  the trajectory / merge-evidence work (#41) reads it after the fact. Trusted
  in-repo PRs are unchanged (#75).

### Fixed

- Findings pushed out of the inline budget into the mechanical section now keep
  a distinct identity each, so a re-review recognises which ones it already
  raised and a withdrawn finding stays withdrawn; previously every overflowed
  agent finding shared one identity and they were indistinguishable across runs
- Keep mergeCraft run temp / ``CODEX_HOME`` outside ``/tmp`` (prefer
  ``RUNNER_TEMP`` or ``~/.cache/mergecraft``) so Codex can install PATH-alias
  helper binaries; Codex 0.14x refuses helpers under world-writable temp and
  exits non-zero, leaving ``mergecraft-approval`` neutral until a fallback
  reviewer completes
- Action `model` input and explicit chain selection no longer lose to
  `MERGECRAFT_MODEL`; missing agent binaries are skipped when walking the chain;
  retryable chain advancement is wired through the Action entrypoint (#14)
- Always post the `mergecraft-approval` status check on PR runs when status checks
  are enabled; use `neutral` when the review did not complete so a failed run no
  longer leaves a missing check that branch protection can misread as pass
  ([#5](https://github.com/alexhawat/mergeCraft/issues/5)).
- Anchor the `mergecraft-approval` check to the PR head SHA and name the
  actually-reviewed commit in the check summary so stale reviews are visible
  ([#6](https://github.com/alexhawat/mergeCraft/issues/6)).
- Preserve a recorded approval conclusion when the overall run fails after the
  review step (e.g. schema enforcement), instead of masking it as `neutral`
  ([#5](https://github.com/alexhawat/mergeCraft/issues/5)).
- Surface `claude` CLI stdout/stderr, exit code, and attempt context (model,
  permissions flag, CI env) at warning level on non-zero exit; propagate the
  diagnosable error into Action failure output and the `mergecraft` check-run
  summary ([#15](https://github.com/alexhawat/mergeCraft/issues/15)).
- Learnings updates on ephemeral Action runners now log a warning instead of a false
  success and include the before→after delta in the posted review or progress comment
  so operators can commit `.mergecraft/learnings.md` deliberately ([#7](https://github.com/alexhawat/mergeCraft/issues/7)).
- Wire K3 CI intelligence to the `analyze_ci_failures` MCP tool — fetches check-suite logs,
  clusters failures, and returns review-ready `section`, `preMergeSummary`, `comments`, and
  `stats`; Review/IncrementalReview prompts call the tool instead of manual log clustering.
  ``execution.py`` orchestration; register ``buf_native`` parser; gate ``verified_only``
  findings via ``filter_for_review``; require detect-glob match for ``default_enabled``
  tools; skip managed provisioning when scoped files are empty; harden scratch path writes,
  pinned download redirects, sandbox pid-namespace requirement, and ``RLIMIT_AS`` memory cap.
- Wire D7 sandbox planning into adapter execution; fail-closed trust tier when the GitHub
  event is missing; redact analyzer artifacts before persist; apply repo ``inlineBudget``;
  extract canonical ``analyzers/pipeline.py``; use baked binaries when ``MERGECRAFT_ANALYZERS=full``.
- `github-issue-manager` and `github-issue-triage` agents now route body/comment
  reads through the sanitizing fetcher; the SKILL.md `Configuration` section drops
  the `spec-kit-wave/skills` lookup (kit not vendored) and documents the
  `--skw-toml` override path

### Changed

- **Migration:** repos not ready for the analyzer catalog should set
  ``analyzers.enabled: false`` in ``.mergecraft/config.yaml`` or ``INPUT_ANALYZERS: off`` in
  the GitHub Action until they opt in.
- Gate comment-driven invocation on the GitHub `author_association` of the
  commenter: only `OWNER` / `MEMBER` / `COLLABORATOR` authors may start a run
  via `issue_comment` or `pull_request_review_comment`. Authorization is read
  from `comment.author_association` in the payload, never from the comment
  body. A missing field fails closed. ([#72](https://github.com/alexhawat/mergeCraft/issues/72))
- **BREAKING:** Comment-driven invocation under `pull_request_target` is now
  refused by default. Workflows that previously relied on `@mergecraft`
  comments under a `pull_request_target` workflow must opt in explicitly with
  `with: allow_pr_target_comments: 'true'` on the action step. The opt-in
  surfaces as `INPUT_ALLOW_PR_TARGET_COMMENTS` in the action contract and
  ships silently refused otherwise — no reply is posted to the thread, only a
  `logger.warning` line that records the event name and association. (D6)
- The `mergecraft.yml` example workflow no longer carries `issue_comment` or
  `pull_request_review_comment` triggers; on-demand runs go through
  `workflow_dispatch`. The hardened example already omitted comment triggers
  and is unchanged. ([#72](https://github.com/alexhawat/mergeCraft/issues/72))

### Added

- Hardened reference workflow at `examples/workflows/mergecraft-hardened.yml`
  (same-repo secret guard, PR-number concurrency, wait-for-CI, base-ref fetch,
  full-SHA pin, approval-check enforcement) plus a template renderer with
  `make example-workflows-check` wired into `make ci-static`.
- Codex subscription agent harness (`agents/codex.py`): invokes the official
  `codex exec` CLI with mergeCraft MCP config, reviewer/verifier instructions,
  and the same push/shell permission gates as Claude Code; resolves when
  `CODEX_AUTH_JSON` is set; Docker image installs `@openai/codex`.
- OpenAI API key path on the Codex harness: `OPENAI_API_KEY`-only runs resolve
  to the same `codex` agent for any `openai/*` model; fail-loud when neither
  `OPENAI_API_KEY` nor `CODEX_AUTH_JSON` is configured.
- Gemini agent harness (`agents/gemini.py`): invokes the official `gemini` CLI
  with mergeCraft MCP settings; resolves when `GEMINI_API_KEY` or
  `GOOGLE_GENERATIVE_AI_API_KEY` is set for `google/*` models; Docker image
  installs `@google/gemini-cli`; `mergecraft auth gemini` saves the API key via
  `gh secret set`.
- Cursor Cloud Agent harness (`agents/cursor.py`, Phase A / D9): launches a
  remote cloud agent via the Cursor API (`CURSOR_API_KEY`); polls to terminal
  status and surfaces the dashboard URL in agent metadata; local Cursor CLI
  detection remains deferred (Phase B); `mergecraft auth cursor` saves the API key via
  `gh secret set`.
- Batch D Final gate hardening: httpx-based `auth gemini`/`auth cursor` key
  validation (Bandit-clean), usable-only `CODEX_AUTH_JSON` resolution, Gemini
  system-prompt delivery, Cursor loopback MCP omission for cloud runs, and
  dict-payload shell/branch reads for Action runs.
- CI pipeline intelligence (K1): ``PipelineProvider`` protocol with ``GitHubActionsProvider``
  (delegates ``get_check_suite_logs`` behind the provider), honest CircleCI/GitLab/Azure stubs,
  normalized failure shape with stable fingerprints, and ingest-time log redaction via
  ``analyzers/redact.py``.
- CI pipeline intelligence (K2): root-cause clustering, flaky/pre-existing detection,
  failure-to-hunk blame, explicit truncation notices, and verification routing for
  PR-attributed CI findings.
- CI review integration (K3): ``### 🚨 CI failures`` section with clustered root causes,
  flaky/blame verdicts, pre-merge CI row, inline fix suggestions for contained hunks, and
  ``REVIEW-CHECKS.md`` CI section.
- Review integration for analyzers: `run_analyzers` and `analyzer_findings` MCP tools,
  read-only `mergecraft-verifier` subagent for Critical/Major hits (D11), mechanical
  findings section and pre-merge Analyzers row, offline `diff-review` wiring, and
  `REVIEW-CHECKS.md` §2 rewrite (W7).
- GitHub-native analyzer adapters: actionlint, zizmor, ShellCheck, and Hadolint manifests
  with bundled actionlint SARIF template, ``adapters.run_adapter`` end-to-end runner, and
  fixture-repo planted-finding coverage (W6).
  suppression, and ``introduced_by_pr`` annotation for analyzer findings.
- SARIF 2.1.0 ingest and export, native parsers (ruff, eslint, osv, trivy, trufflehog,
  shellcheck), D8 redaction boundary, and file-based output parsing for large analyzer runs.
- Analyzer provisioning and sandbox: pinned managed-binary fetch with SHA256 verification,
  ``.mergecraft/analyzers.lock`` reproducibility, trust tiers wired into ``ToolContext``,
  sandbox capability probing with skip-not-degrade on missing isolation, ``Dockerfile.analyzers``
  full image tier, and ``action.yml`` ``analyzers`` input (`off` | `auto` | `full`).
- Analyzer platform core: manifest schema, catalog registry, normalized ``Finding`` model,
  execution-mode resolver, shared runner, and ``analyzers:`` config block.
- **Catalog C1:** repo-native language-gate manifests and detection for Ruff, MyPy,
  Pyright, BasedPyright, ESLint, Biome, and Oxlint — config-driven ``exclusive_group``
  selection, type-checker skip (never managed substitute), and ``analyzer_run_metadata``
  version reporting (D5/C3).
- **Catalog C2:** managed OSV-Scanner and Trivy adapters with base-vs-head CVE delta
  (``supply_chain.run_differential_scan``), TruffleHog secret scanning with rotation-first
  remediation and verify-off-by-default policy (``config.trufflehog_verify_enabled``),
  and ``dependency-vuln`` exclusive-group dedup hooks (D12).
- **Catalog C3:** pattern-scanner backend with Semgrep (pip-provisioned), swappable
  OpenGrep, and ast-grep structural rules — repo rules preferred, SARIF ingest scoped to
  changed files, and Critical/Major taint hits gated on ``mergecraft-verifier`` (D11).
- **Catalog C4:** differential contract adapters for oasdiff (OpenAPI breaking changes),
  Squawk (unsafe PostgreSQL migrations), and buf breaking/lint — base ref required (D6),
  ``oasdiff_json``/``squawk_json`` parsers, and ``contracts.run_differential_adapter``.
- **Catalog C5:** native agent-manifest security scanner for MCP and skill/instruction
  manifests — YAML policy rules, optional SkillSpector corroboration, and
  ``mergecraft.analyzers.agentsec`` manifest reader (C7 exception to manifest-only catalog).
- **Catalog C6:** P1–P3 long-tail manifests (35 tools), generated ``docs/ANALYZERS.md`` with
  CI ``catalog-check`` gate, ``docs/CONTRIBUTING-ANALYZERS.md``, and ``mergecraft analyzers``
  CLI (list/detect/run/explain/export/lock).
- Initial mergeCraft snapshot (history-free).

---

<a id="010a3"></a>

## [0.1.0a3] — long-form entries

Every entry behind the curated `## [0.1.0a3]` section in the root
[`CHANGELOG.md`](../../CHANGELOG.md), as authored, with internal identifiers
and private plan pointers removed.

### Added

- Code-measured LLM review generation time in every posted review record and CLI
 JSON/text output (`⏱ LLM review time: …`), including per-reviewer breakdown
 when multiple reviewers run (#983).
- `mergecraft workflow provider add` wires harness providers without a custom base
 URL using `LLM_PROVIDER_<N>: <label>` plus provider-specific credential env keys
 (for example `OPENCODE_GO_API_KEY` for `opencode-go`).
- `mergecraft agent assign-model` on the committed roster registers missing models,
 auto-wires harness providers into `mergecraft.yml`, and updates `with.model` for
 p0 assignments.
- OpenCode Zen / Go subscription billing via `mergecraft provider auth opencode`
 (or `mergecraft auth opencode`): stores the same `auth.json` shape OpenCode
 CLI uses (`OPENCODE_AUTH_JSON` / indexed `LLM_PROVIDER_<N>_OPENCODE_AUTH_JSON`).
 The opencode harness writes that file under an isolated `XDG_DATA_HOME` for
 `opencode serve` / `opencode run` and reinjects `OPENCODE_API_KEY` when needed.
 OpenCode Zen authenticates with billing-backed API keys, not OAuth device
 tokens like Codex — see [OpenCode Zen](https://opencode.ai/docs/zen/).

### Removed

- The MCP server no longer mounts a webhook endpoint; a signed delivery was
 verified but processed nothing, and its replay window could never fire.
- Provider circuit-breaker, health, budget and routing-eval helpers that no
 review path called are removed.
- Four context-retrieval modules no review path imported are removed.

### Changed

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not
 implemented instead of being accepted and ignored.
- `mergecraft policy` help and enforcement docs state that a review run does not
 enforce policy rules.
- Recorded Jev transports and the canary assertion moved out of the runtime
 package into the test suite.
- A prepared release branch keeps `server.json`'s advertised package version in
 step with `pyproject.toml`, so the branch no longer fails its own
 `mcp-server-json-check` drift gate.

### Fixed

- The OpenCode harness hands its isolated `XDG_DATA_HOME` tree to the
 unprivileged agent user before `setpriv` drops privileges. The action
 entrypoint creates `.../opencode/auth.json` as root, so the dropped CLI failed
 with `EACCES: permission denied, mkdir '.../opencode/log'` whenever
 `OPENCODE_AUTH_JSON` was wired.
- `harness_env_for_active_provider` bridges a provider's flat workflow credential
 to the harness env name when the indexed value is absent, so an `opencode-go`
 run with only `OPENCODE_GO_API_KEY` set re-injects `OPENCODE_API_KEY` instead
 of starting the CLI without a credential.
- An offline review called as a library without a findings file now asks the
 model for structured findings, as the CLI always does. It used to ask for a
 markdown review and then reject it as malformed findings, so any model that
 followed the prompt failed.
- A review whose agent calls `run_analyzers` on a host without a sandbox no
 longer fails closed with "checkout integrity failure: tree changed during
 read-only review". The gate's output in `.mergecraft/analyzer-runs/` and the
 provisioning lock `.mergecraft/analyzers.lock` (with its `.lock` sidecar) are
 files mergeCraft itself writes into the checkout, so the integrity hash now
 skips those three exact paths, as it already skipped `analyzer-scratch` and
 `prep-scratch`. Every other file under `.mergecraft/` is still covered.
- The Action images ship OpenCode 2.x (`@opencode/cli` 2.0.29) for every model
 routed through the OpenCode harness (Nous, OpenCode Zen and Go, MiniMax,
 TokenHub, custom providers). OpenCode 2.x moved its server API, so on 2.x a
 review runs through `opencode run` in a private server per run and resumes the
 same session for follow-up turns. OpenCode 1.x keeps the previous path.
- The hardened example workflow's approval gate now receives only the review
 verdict, not the whole evidence packet. On a large pull request the packet
 exceeded the size one environment variable may hold, so the gate could not
 start. Workflows copied from the example before this change should take the
 new `REVIEW_VERDICT` line.
- The Codex reviewer now runs in the repository it reviews. An offline review
 started from another directory failed at once, because Codex refuses to run
 outside a git repository.
- The self-review passes each review step's evidence packet to later steps as a
 file. A large pull request's packet exceeded the size one environment
 variable may hold, so the verdict step could not start and an approving
 review was recorded as no verdict.
- Both Action images replace the brace-expansion and undici copies bundled
 inside npm with their patched releases, pinned by checksum. No npm release
 ships the fixes yet, and the old copies carried three HIGH advisories.
- A self-review re-run on a job token now picks up the earlier run's checkpoint and
 progress comment. The reader looked for a packet file name the workflow never
 uploads, so every re-review started again from scratch. It now reads the file
 each review step uploads, preferring the last step that ran.
- `doctor`, `config show` / `config explain` and the config loader now agree on
 which files contribute. `config.local.yaml` is reported outside CI, and a
 `MERGECRAFT_CONFIG` that points at a missing file is reported by key and
 filename instead of "no config file (defaults apply)".
- `doctor` fails before printing anything when its rendered output would contain
 a credential value, naming the environment key and never the value.
- Comment-preserving config writes replace a top-level key in place instead of
 appending a second copy, so a repeated write no longer duplicates a mapping or
 a list (for example `models:` or `providers:`), and a list no longer unions its
 old and new values.
- `provider status --json` and `health --json` carry the shared
 `schema_version: "1.0.0"` stamp; `provider status` keeps its existing
 `schemaVersion: 1`. `health` now describes what it checks — liveness plus the
 resolved telemetry mode, not a readiness probe.
- Logfire workflow wiring accepts the lowercase `alexhawat/mergecraft@<ref>`
 spelling the docs print, while still refusing similarly-prefixed forks and an
 empty ref.
- `watch` and the review comment's run link honour `GITHUB_API_URL` /
 `GITHUB_SERVER_URL` for GitHub Enterprise hosts. `watch` also emits a timeline
 event that carries no id once instead of on every poll.
- Workflow failure annotations are escaped before they reach the command stream,
 so a newline or `%` in a pull-request title or an exception message can no
 longer inject a workflow command or a log group.
- The unused hosted-plan residue is gone: the two `AccountPlan` vocabularies, the
 context `plan` field and the `proxyModel` producers and consumers were removed,
 none of which had a reader. `api_token`, the remote upload path, the local
 upload fallback and the provider catalog are unchanged.
- Provider commands read `.env` values the same way the CLI startup load does, so
 a single-quoted value no longer keeps its surrounding quotes and `export `,
 inline comments and `${VAR}` interpolation mean the same thing to every reader
 of the file.

### Added

- `mergecraft review --capture-verdicts` (or `MERGECRAFT_CAPTURE_VERDICTS=1`)
 persists every saved verifier verdict — including ones that end in `drop`,
 which never publish and so cannot be reconstructed afterwards — as one
 redacted line per verdict in `judge-verdicts.jsonl` beside the run's evidence
 packet, in the calibration-case shape the judge-calibration tooling reads.
 Capture is off by default, so an ordinary review writes nothing new.
- A self-review's incremental checkpoint and progress-comment identity can come
 from the workflow run itself: when the latest successful `pull_request_target`
 run of the self-review workflow left an evidence artefact, its
 `reviewed_head_sha` and sticky-comment id drive the checkpoint and the round
 index. A workflow definition that exists only on a pull-request branch cannot
 produce such a run, so the identity is not forgeable by the PR author.
- `mergecraft eval trajectory-gate` reads an approved trajectory protocol —
 pre-registered minimums per check plus a tolerance — and compares a candidate
 report against a frozen baseline, failing and naming any check outside the
 tolerance. Until a protocol is approved it reports `no approved protocol —
 advisory` and exits 0.
- Human golden-batch manifests declare their own batch id and case list, so a
 later batch can be reviewed without a code change; the first batch's nine case
 ids stay pinned as a frozen fixture.
- Behaviour-verification reports record which driver produced them — `cdp`,
 `stub`, or unset when not recorded — so a report says whether its page came
 from a real browser or the non-browser fallback.
- OpenCode plugin at `integrations/opencode/plugins/mergecraft/`: registers the
 public MCP server, overrides `/mergecraft/review` with the configured engine,
 redacts credentials from prompts, keeps the reviewer subagent read-only and
 on-doctrine (`permission.evaluate` forces `edit`/`shell` to deny without
 weakening a configured deny), bounds mergecraft shell timeouts, and emits one
 `mergecraft.review.native` Logfire span per native review when a write token is
 present.
- `mergecraft opencode install` copies the commands, subagents, and plugin into
 `.opencode/` (or `~/.config/opencode/` with `--global`), writes the V2
 `mcp.servers.mergecraft` block, and sets `harness: opencode` in
 `.mergecraft/config.yaml`. `mergecraft opencode doctor [--strict]` reports
 whether the CLI, assets, config, MCP block, JEV credential, and Logfire token
 are wired.
- First-class OpenCode integration under `integrations/opencode/`: `/mergecraft/*`
 slash commands for six review engines (native, cli, deep, mcp, quick,
 thirdparty), a read-only `mergecraft/reviewer` subagent, a `mergecraft/fixer`
 subagent for the review-only loop, and an `opencode.jsonc` template. The
 generated `skills/opencode/mergecraft/SKILL.md` now carries an
 OpenCode-specific install section instead of the generic body.
- `docs/opencode.md` documents the integration: engine selection, commands,
 subagents, V2 MCP wiring, JEV scope, and Logfire tracing.

### Security

- The Claude reviewer can no longer read the run's credential material. The
 driver denies reads of the runner's file-command mounts, the runner home and
 other processes' environments, writes the Codex auth file root-only, and
 records a run warning when a `Read`, `Glob` or `Grep` call names a path outside
 the checkout and the run's own temporary directory.
- The review job declares `actions: read`, and no review rung falls back to the
 shared `github-actions[bot]` login when no reviewer App is configured.

### Changed

- The local `.env` file and the tracing environment layer are read through one
 typed model each, so a variable's exact name and type live in one place and a
 new environment read has a defined home. Behaviour is unchanged apart from the
 two entries above.
- Progress comments are recognised by the identity that published them, not by
 any bot: the sticky selector uses the run's expected-publisher set, or the
 sticky id recorded by a trusted self-review run, and never falls back to
 matching any bot-authored comment. **Breaking:** when neither identity is
 available, a run creates a new progress comment rather than adopting an
 existing bot-authored one, so a repository whose sticky was posted by the
 shared Actions bot starts a fresh comment — and with it a fresh ledger —
 instead of reusing the old one.
- The built wheel no longer ships seven test-, script- and eval-support modules
 that no runtime caller imports (`evals/mcp_public.py`,
 `evals/quality_metrics.py`, `evals/skill_taxonomy_gate.py`, `utils/git_ref.py`,
 `integrations/live_providers.py`, `mcp/codegen.py`, `scm/errors.py`). Each is
 still present in the checkout for the script, Make and test callers that use
 it.
- The Gemini and Codex harness deny lists name the `push_branch` tool the way
 each CLI documents it, matching the spelling the other harnesses already used.
- The release regression gate now fails when a run adds failed or inconclusive
 cases, instead of scoring only what survived: a detection half whose every
 case failed no longer reads as a perfect `1.0`, and a release candidate
 missing a half the baseline carries fails instead of skipping it.
- Finding matching against a baseline maximises the number of matched issues, so
 recall no longer changes when baseline issues are reordered; the scorer
 version is now `1.1.0`.
- `docs/mcp.md` OpenCode install now shows the OpenCode V2 shape — servers nested
 under `mcp.servers` with `disabled`, not the V1 top-level `mcp` map with
 `enabled` — and includes the `opencode mcp add` one-liner.
- `skills/harnesses.yaml` OpenCode row gains an `install_section` covering
 commands, subagents, MCP, and JEV/Logfire, so the generated package matches the
 install path OpenCode actually reads (`.opencode/skills/`).
- `mergecraft eval publish-benchmark` validates two saved provider runs against
 an approved campaign manifest, independently adjudicated label and judge
 receipts, immutable artifact and model identities, shared protocol pins, and
 cost ceilings before writing a non-overwritable machine summary and report.
 This is offline publication preparation: no approved human-labelled campaign,
 live comparative result, benchmark claim, or release is included.
- `mergecraft verify-behavior` now drives a real Chrome over the DevTools
 Protocol and scores each acceptance criterion and reproduction claim through
 Jev, instead of refusing every run. A reachable host Chrome yields a live
 driver; an unreachable endpoint still fails closed, with a named, readable
 skip in both the test run and the report. The report states what a green
 verify does and does not prove (#752).
- `mergecraft jev enable|disable|status|set` configures the Jev advisory
 screening gate. `enable` writes only `jev.enabled: true` — every other
 value keeps coming from `JevSettings` defaults, so a later default change
 still reaches repos that never pinned their own. `enable --github` /
 `disable --github` open a PR against the default branch, mirroring
 `trust set-self-review --gh-apply`, and `status --github` reports whether
 the default branch has it on and whether the `TYPESAFE_API_KEY` Actions
 secret is present. `set` round-trips any single value through
 `JevSettings` and refuses an invalid one (a floating model alias, a
 non-positive budget) before writing. YAML comments in an existing config
 survive every write (#786).
- Offline reviews now render a Jev summary section when Jev is enabled: a
 collapsed table of per-unit predictions when it ran, or the recorded
 `jev_skip_reason` (`credential_absent`, `kill_switch`) when it did not —
 previously nothing surfaced that gap, so a missing credential looked
 identical to a clean run. The section always states Jev is advisory
 (`enforced` is always `false`) and never implies its thresholds are
 calibrated. With Jev disabled, review output is unchanged (#786).
- Order-dependent test coupling now surfaces on a scheduled, non-blocking
 unit-suite run whose seed is the per-run `github.run_id`, so a pinned seed
 no longer hides it. `MERGECRAFT_PYTEST_RANDOM_SEED` is set only on the
 `schedule` / `workflow_dispatch` path; PR runs keep the pinned `424242` and
 the job adds no required check (#776).
- Jev architecture checklist helpers (`jev/architecture.py`, `jev/pack_registry.py`):
 fan-out question merge, answer+confidence routing, per-pack state filtering with
 untrusted nonce fencing, and model/usage logging on every System One call.
 Maintainer doc: `docs/jev-architecture-checklist.md`.
- Bare CLI command names open a TTY interactive session. `mergecraft`,
 `mergecraft review`, and groups such as `mergecraft provider` offer a menu
 (or a review wizard) when stdin is a TTY. Scripts, CI, piped invocations,
 and any invocation that already passes flags keep today's non-interactive
 behaviour. Missing required arguments are prompted on a TTY instead of
 failing with Click's "Missing argument". `mergecraft config set` writes
 `models` / `tracing.enabled` into `.mergecraft/config.yaml`.
- A second gate policy (prompt 2.0.0) records through the existing recorder.
 The optional keyless job replays two hard-coded packets; it does not run a
 model and leaves #737 open. The live review path never enforces a shadow
 prediction.
- Production false positives and human dismissals can be ingested into the eval
 bank as versioned cases, each carrying explicit provenance. Ingest refuses a
 case without provenance, refuses to record a human label that has not passed
 independent adjudication, and drops a case rather than minting a label.
 Ingested cases participate as structural replay cases only, never as
 calibration labels (#738).

### Changed

- Consumer setup guidance now lists every file produced by `mergecraft init`
 that may be committed: the config, learnings file, workflow, and added
 `.gitignore` lines. Authentication remains an interactive human step.
- The critical-path and per-prefix coverage floors are rebaselined from one
 complete 2026-09-22 measurement at integrated HEAD `157f57a3`. Module line
 and branch floors use separate counts with a two point buffer; prefix line
 floors use two points and branch floors three points. `utils/token.py`
 measures 95.7% line and 93.2% branch, yielding floors of 93.7% and 91.2%.
 No current floor is lower than the prior PR #817 baseline, and the native
 combined global `fail_under = 82` is unchanged. Report hashes, runtime,
 counts and every floor delta are recorded in
 (#771, #797, #824).
- CLI `--json` payloads carry their own schema version, decoupled from the
 review snapshot's. Both stay `1.0.0`, so no payload changes; the two can now
 be bumped independently (#777).
- `mergecraft jev --help` (and each `enable` / `disable` / `status` / `set`
 `--help`) now documents every command and option, including the
 `TYPESAFE_API_KEY` local `.env` and Actions-secret paths (#803)
- `mergecraft jev enable` now requests `TYPESAFE_API_KEY` when it is not
 already set and writes it to `.env`. `enable --github` also stores the
 key as the `TYPESAFE_API_KEY` Actions secret when a key is available
 and the secret is missing (#803)
- Review records, sticky progress comments, and the Actions step summary now
 show input and output token counts separately instead of one combined total
 (#801)
- `make test` no longer runs the nine branch-walking `test_cov_*` suites: they
 carry a new `coverage` marker and the `make test` selector is now
 `-m "not integration and not coverage"`. They still run under
 `make coverage-measure` and `make ci`, so the coverage number is no longer
 inflated by suites filed among the product tests. The critical-path
 `utils/token.py` floor stays in `MODULE_FLOORS` unchanged: removing it would
 leave the token authentication path with no module-level branch check at all
 (the tree-wide `fail_under` is a line floor), so it is retained until
 behavioral tests and a measured replacement floor can land together (#771,
 #797).
- The coverage/mutation CI gate's `enforce` mode is now exercised under test —
 both `shadow` and `enforce`, asserting the gate action and `reaches`. It had
 shipped dark, so the branches deciding whether a finding blocks a merge had
 never run. `review_policy/` and five production modules gained behavioral
 suites, the `EvalMetadata` verdict vocabulary gained a rejection case, and
 stale `xfail` markers tagged to a closed issue were deleted (#766, #767,
 #768, #770).
- The action-pin bump workflow no longer advertises a push it cannot perform.
 `stage=pin` rewrites `.github/workflows/`, which GitHub refuses from a
 `GITHUB_TOKEN` push by construction, so it prepares the four consumer
 references in the runner and prints the exact local `make action-pin-prepare`
 command instead; `stage=manifest` keeps its push but emits a Conventional
 Commit subject inside the 72-character cap, and the workflow header drops the
 claim that it automates the cycle's mechanical half (#749, #750).
- PR #742 drops Playwright as the behaviour-verification driver. Live browsing
 binds to `mergecraft.browser` (custom browser-use + JEV) and fails closed
 until the CDP driver is wired (#752). The `mergecraft[browser]` extra and
 `playwright==1.63.0` pin are removed (#752, #61)
- `mergecraft verify-behavior` fails closed when the browser-use stack is
 unavailable, even with `--artifacts-dir` / `--input`; `--allow-stub` is the only
 stub opt-in (#61, #752)
- `verify_behavior.enabled: false` skips the run (kill switch); default remains
 enabled so invoking the CLI still runs on a trusted checkout (#61)
- `verify_candidate` verifies the commit that introduced an image digest rather
 than whichever commit the candidate range happens to end at. It treated any
 commit whose `action.yml` image differed from the base as a freshly minted
 manifest, and `verify_manifest` requires such a commit to differ from its
 image source in `action.yml` alone — so a forward-port, a sync, or the merge
 commit a manifest PR lands as was rejected outright. The introducing commit is
 substituted only when the candidate's `action.yml` is identical to it, so
 neither a digest minted mid-branch nor a later Action change riding on a
 legitimate digest escapes verification (#684).
- markdownlint follows the `markdownlint-cli` 0.49.1 bump: the catalog pin tracks
 the engine, so it moves 0.37.4 → 0.41.1. A markdownlint `warning` now grades
 **Minor** instead of Major — the parser reads the per-finding `severity` that
 0.49.1 emits rather than hardcoding `error`, and an unrecognised severity
 grades as `error` with a log line instead of failing the whole run. The engine
 bump also enables `MD060` (`table-column-style`) by default. This repo's
 `.markdownlint.json` disables it; consumers with no markdownlint config get
 the same MD060-only disable via the shipped `markdownlint-default-config.json`
 fallback, and a run note records that the fallback applied so operators can
 tell repo-rules-clean from fallback-clean. A consumer whose own config
 enables MD060 still gets it (#704).
- trufflehog no longer reports secrets from virtualenv trees (`.venv`,
 `.venv-dev`, `site-packages`) or four named intentional fixtures; each
 fixture suppression names why it is exempt, and a newly committed secret
 under `tests/` still fires.

### Fixed

- A Review run that records its verdict now publishes exactly one GitHub
 review from it, with the recorded findings as inline comments. A recorded
 verdict that never reached GitHub reads `inconclusive` with its own reason
 instead of passing, and a later attempt whose verdict differs from the review
 already posted on the same head is reported as a mismatch naming both
 verdicts rather than silently skipped. Findings that GitHub did not show
 inline are listed. Each fresh run still posts its own review.
- Auto-resolving earlier review threads now requires the thread's line to have
 changed (or GitHub to mark it outdated), every comment to come from the
 run's expected publisher (never the shared Actions bot), and the finding to
 be absent from the whole submission, including findings demoted to the body
 or deferred. With no known publisher, nothing is resolved and the run says so.
 A missing or malformed resolve response no longer counts as resolved.
- Issue-comment and pull-request-review listings page through every result up
 to the page cap and report `incomplete` when the cap cuts them, so the newest
 reviews are no longer dropped after the first hundred.
- An unknown or missing trust tier is treated as `untrusted` everywhere,
 including a tool context built without one. A malformed run timeout keeps a
 finite chain deadline with a warning, and a failed closing-issues lookup is
 reported as unavailable instead of as "no closing issues".
- Review prompts name only tools that exist and only finding fields the schemas
 accept: every registered tool name is interpolated, so it renders as the
 harness's real tool reference; the `collateral` list is gone (collateral still
 renders in the inline body as the **Also update:** list); and the
 classifier-router paragraph naming `classify_change`, `route_lenses` and
 `selected_lens_ids` is removed.
- Prompts no longer bake in a budget: the inline cap renders from
 `analyzers.inlineBudget`, the verifier cap is described as
 `review.verificationBudget` scaled per round by `review.roundBudgets`, and the
 stale diff-coverage-nudge note and the Fix-button rationale are gone.
- The recorded prompt version now reflects the rendered prompt the reviewer
 actually received, so two runs configured with different inline budgets record
 different versions.
- A configured inline budget of `0` is honoured everywhere: the offline analyzer
 pre-pass, the pipeline fallback and the rendered prompt now agree, instead of
 the pre-pass silently using the default.
- The review doctrine states the Python 3.11 install floor, and the `push`
 input, the compatibility matrix and the review checks describe review-only
 behaviour — no value grants commit or push.
- Documentation links and glossary anchors resolve on GitHub (the glossary's
 `{#id}` headings become real anchors), and the operator-facing `MERGECRAFT_*`
 knobs are documented in `docs/cli.md`.
- CI failures with no evidence of cause are now reported as **unattributed** —
 blocking, with `introduced_by_pr: unknown` — instead of being cleared as
 not-this-PR. A passing or unrecognised base-branch status no longer clears a
 failure: only a same-fingerprint base run that concluded `failure` does, and
 one base-branch status can no longer clear more than one cluster
 (per-fingerprint base runs can). "Pre-existing" now requires the base run to
 have failed, and its summary names the ref and what that run concluded.
 Failure paths come only from failure lines — `FAILED`/`ERROR` with a node,
 line-start `path:line:`, and `path(line,col)` — with root-level files,
 `(line,col)` and `./` forms accepted and normalised on both sides of the diff
 comparison, so passed tests, collection lines and command echoes no longer
 produce a blame path. The pre-merge CI row and the run payload report an
 unattributed count.
- A negated acceptance criterion — "No error is shown", "Error is not shown" —
 no longer passes against a page that shows the error: it is left unverified
 with a named reason, and a negated reproduction claim is partial rather than a
 false reproduction.
- `--allow-stub` permits the stub only when the browser stack is unavailable and
 logs why, instead of bypassing a reachable browser.
- Every agent CLI driver and the OpenCode server boot no longer hang when a
 child fills its stderr pipe. Each driver drains stderr concurrently with the
 stdout stream it already reads, keeping the two pipes separate so the
 stream-json parse is unchanged and the stderr tail still reaches failure
 diagnostics; the buffer is bounded and tail-kept.
- OpenCode server boot no longer blocks the event loop in a blocking
 `readline`. The process group is registered at spawn, both pipes are
 drained from spawn, and boot waits on a URL event under its deadline, so a
 server that logs a full pipe's worth of stderr before printing its URL now
 starts instead of timing out, and a hung, exited or cancelled boot kills,
 unregisters and reaps the group.
- OpenCode falls back to the alternate prompt endpoint only on 404 or 405. Any
 other error status is reported once, unretried, so a 429 or 5xx can no
 longer start a second agent turn on the same session.
- The Claude and Gemini reviewers can no longer write files, run shell tools or
 fetch the web. Their write, edit, shell and web tools are denied
 unconditionally, including the subagent forms, matching the review-only
 product boundary; permission prompting stays skipped in headless CI because
 the deny list is the boundary.
- Tracing no longer clears a bound data-residency allowlist. The tracer factory
 reads the bound enterprise block instead of re-binding it, makes no
 enterprise call at all on the disabled path, and scopes repo settings to
 sink construction only when nothing is bound.
- The OTLP span recorder is a test-only seam again: it is installed on a
 provider only when a test fixture enables it, never from an environment
 variable, its payload list is bounded, and the module-level header copy masks
 sensitive values instead of keeping a bearer token in a global.
- The sticky progress comment keeps the finding ledger and the learnings delta
 across the final deterministic-record write, so a later run hydrates every
 prior record instead of losing it. A later run reuses the existing progress
 comment rather than posting a second one, and only bot-authored comments are
 read as progress state. The run record names the reviewer slot skipped for
 missing credentials and the model that produced the recorded verdict, instead
 of claiming no reviewer ran.
- Managed analyzer caches and the semgrep pip install now live under the
 operator's cache directory (`$XDG_CACHE_HOME`, else `~/.cache`, plus
 `mergecraft/analyzer-cache`) instead of `<repo>/.mergecraft/`, so a pull
 request can no longer commit a binary, a lock row and a receipt that the fast
 path would then execute. A cache root that resolves inside the checkout is
 refused with a named skip rather than used. The checkout's
 `.mergecraft/analyzers.lock` is still written and digested for the pre-merge
 row, but it never authenticates a binary: a cache hit now requires a receipt
 binding the archive pin and the extracted binary's digest together. A lock row
 missing a required key is skipped with a warning instead of raising, and a
 lock write stages to a temporary file and renames into place under a sidecar
 lock, so a failed write leaves the previous lock intact.
- Analyzer findings are attributed to the file that actually caused them again.
 `diff --git` headers are parsed with Git's C-style quoting, the path is taken
 from `rename to` / `+++ b/` when present, and a header that cannot be parsed
 drops its hunks instead of attaching them to the previous file. A SARIF URI
 that points outside the repository is kept verbatim and labelled
 `outside repository root` rather than shortened to a basename that may name an
 unrelated file, and the CI trufflehog producer now emits
 repository-relative URIs.
- The `run_analyzers` tool confines `repo_root` to a directory the run already
 registered as a checkout, and rejects a supplied `diff_path` that escapes the
 authorized roots, is missing, is not a regular file, or is not valid UTF-8 —
 each with a named reason and without running an analyzer. Previously an
 out-of-root path was ignored in silence and the pipeline ran unscoped.
- Negative memory that cannot be read no longer aborts a trusted run: malformed
 rules and audit entries are skipped per entry, an unreadable store reports
 every finding instead of suppressing them, and the audit trail is bounded.
 The `sarif_upload` action input no longer declares a default, so an unset
 input now reaches `.mergecraft/config.yaml`'s `analyzers.sarifUpload` as
 intended; a consumer relying on the implicit `disabled` should set the input
 or the config key explicitly.
- Offline local diff materialization skips mergeCraft's generated
 `.mergecraft/analyzer-cache/` entries before per-file untracked diff
 generation, preventing a populated managed cache from adding thousands of
 subprocess calls while preserving ordinary untracked source and tracked
 changes (#829).
- Managed analyzer provisioning failures now retain a bounded, redacted final
 cause in logs and skip results, distinguishing transient GitHub release
 outages from checksum, redirect, and other provisioning failures without
 exposing credentials or download URLs (#825).
- Persisted review trajectories redact secrets while retaining exact, safe
 read-path attribution and ordinary repository filenames (#819, #823, #827). Terminal verdicts use normalized, deduplicated typed
 findings, and publication retry state clears only after a matching scope/head
 receipt is stored.
- GitHub App runs mint separate least-privilege API, Git, and cross-repository
 tokens. Cleanup attempts to revoke every internally minted token.
- Coverage gates use native line/branch metrics and accept only complete,
 fingerprinted shard sets. A single run trace covers setup through publication
 across Action, offline, and MCP execution.
- Evaluation records round-trip without dropping corpus data and write
 atomically after validation. Offline tools prepare human-review batches,
 score exact trajectory rule/path multiplicities, and support a sealed
 judge-calibration protocol. The new trajectory fixtures are agent-seeded
 development data and are ineligible for quality claims; actual human
 validation, live-model benchmarking, release verification, and publication
 remain pending.
- The keyless shadow job is a fixture replay of two hard-coded packets. It
 does not read a live review and leaves #737 open.
- A live shadow row records the model on the packet (the slug that ran, else
 the configured reviewer). When the packet has no model, the row leaves it
 unset instead of claiming Claude.
- `mergecraft eval ingest --from-dismissals` turns recorded dismissal signals
 into structural eval cases. A dismissal is stored as `agent-seeded`, not as
 a human label (#738).
- The deterministic run record no longer publishes an approval-shaped verdict
 when no credentialed reviewer ran: a skipped reviewer credential renders the
 record `inconclusive` (the GitHub check conclusion stays `neutral`),
 `Outcome` / `Verdict diagnostic` / `Decision` are reconciled so they cannot
 disagree, and the record names which analyzers ran or were withheld and
 whether a credentialed reviewer participated. The self-review roster points
 at the workflow-wired `nous/tencent/hy3` provider instead of the unwired
 synthetic `auto/efficient` (#775).
- Resetting the MCP shell sandbox cache tolerates a patched capability probe —
 it clears the probe cache only when a callable `cache_clear` is present — so
 test-isolation teardown no longer errors.
- `mergecraft verify-behavior` stays inert on a fork or `pull_request_target`
 Actions event instead of always skipping the trust gate (#61)
- `mergecraft review --verification-report` does not load a report on an
 untrusted checkout, including when a workflow treats the workspace as trusted
 (#61)
- Verify criteria are scored per criterion; reproduce matches page text to
 repro notes; `--start-command` retries navigate while the app comes up (#61)
- Codex no longer lets a stale ambient `CODEX_AUTH_JSON` override a resolved
 registry API key: the flat subscription fallback applies only when the
 registry resolved no Codex credential, so the broker stays active and the
 selected key is used instead of a stale `auth.json` (#711)

### Added

- `mergecraft verify-behavior` can reproduce a bug or check a running app and
 write a versioned report under `.mergecraft/artifacts/`. It stays inert on an
 untrusted tier or when `shell: disabled`. Optional YAML `actions` drive
 click / fill / type (#61, #752)
- A versioned behaviour-verification report (`schema_version` 1.0.0) records
 what was observed, which criteria passed, and what blocked the run — without
 turning those results into code findings (#61)
- `mergecraft review --verification-report` (also `diff-review`) consumes a
 behaviour-verification report, fences it before the prompt, and renders
 results in a separate section — not as code findings. A blocked report
 stays visible; no report leaves the review unchanged (#61)
- Reviews can ingest declared coverage receipts and report change-risk scores on the functions the PR actually touched, advisory by default (#714)
- Reviews can ingest declared mutation survivors the same way; local `mergecraft review --with-coverage` / `--with-mutation` require `--shell enabled`, wrap live tool runs in the existing sandbox backend (or refuse), and refuse a fork checkout (#714)
- Opt-in Jev / System One client (`jev.enabled`, default off) with cost
 accounting, a kill-switch, and GenAI spans; a missing TypeSafe key records a
 skip and does not fail the review (#728)
- Parallel shadow judge grades review findings and prose against their cited
 evidence without replacing the reviewer (#728)
- mergeCraft review loads `.github/skills/code-review/` as a self-contained
 Agent Skills payload — `SKILL.md` plus one-level `references/` resolved into
 the `REVIEW SKILLS` prompt section, with a 64 KiB instruction-bundle cap,
 taxonomy/spec drift gates, and a small eval corpus that must beat the
 366-byte pointer baseline; `review.instructionExtraFilenames` wires configured
 extras through the CLI and Action review-context path
- GitHub Copilot is a first-class Agent Skills harness: generated
 `skills/copilot/mergecraft/`, install path `.github/skills/mergecraft/`,
 a Copilot repo-MCP snippet with the six public tools, and a thin
 `.github/agents/mergecraft.agent.md` (#621)
- mergeCraft review prefers Copilot-style `.github/skills/code-review/`
 (and other `.github/skills/*/SKILL.md`) over generic standing skills,
 keeps the trust fence, and on the trusted tier can attach read-only
 stdio consumer MCP servers from `review.mcpServers` / `.vscode/mcp.json`
 (untrusted runs drop both) (#620)
- `mergecraft trust set-self-review --gh-apply` opens a default-branch PR
 so `pull_request_target` picks up `trust.selfReview` without a hand-edit
 on main; comment-heavy configs are patched in place with or without
 the flag, and a second `--gh-apply` reuses the existing branch/PR (#616)
- Untrusted reviews can export prompt bodies to Logfire when `tracing.content`
 is `full` **and** an operator-owned export flag is true (Action
 `tracing-export-untrusted-content`, `MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT`,
 `--tracing-export-untrusted-content`, trusted YAML, or the
 `pull_request_target` base snapshot); fork HEAD YAML cannot lift the cap;
 `content: full` alone still caps fork-PR bodies at metadata
- `mergecraft review --tracing-content` and Action `tracing-content` set the
 capture level without editing YAML
- `mergecraft provider status` shows what CI will run — each reviewer agent's
 `pN` slots, credential and workflow-wiring state, dispatch level, and skipped
 slots — with `--json` for scripting and optional `--github` to report repo
 secret presence without printing values (#520)
- `mergecraft agent` and `mergecraft agent-local` author the agent roster —
 positional `pN` slots, named agents, `after:` dispatch levels, and dense
 `modelChain` editing; local overrides write `.mergecraft/config.local.yaml`
 and are invisible to CI
- Multiple reviewer-role bindings run on one PR; findings merge by path/body/line
 and produce exactly one verdict with strictest severity winning
- `mergecraft workflow sync` keeps `.github/workflows/mergecraft.yml` auth wiring
 aligned with roster models; unwired providers fail at CLI write time and at run
 start
- First `mergecraft provider auth` after `init` seeds `agents.reviewer` p0 so
 review works with no third command
- `docs/agent-roster.md` — operator guide for slots, named agents, local scope,
 multi-reviewer verdict rules, and the run-start trust snapshot
- Operator trust knob (`trust.selfReview`: `off` / `analyzers` / `full`) with
 two-axis resolution — execution trust for analyzers vs authority trust for
 approval semantics — resolved from the base config snapshot so a PR cannot
 raise its own tier; `mergecraft trust show` / `set-self-review` CLI
- Degraded review scope: when the PR head cannot be fetched, `checkout_pr`
 returns `scope: api-only` with an API-built diff and the run may still reach
 a terminal verdict (including approve when findings allow)
- `establish_review_scope` — evidence-backed second route into review scope
 when a materialized diff already describes the PR head
- Read-only git MCP verbs (`show-ref`, `for-each-ref`, `ls-remote`, `config
 --get`) and `checkout_pr` parameter aliases (`pr_number`, `issue_number`)
- Agent stream logs render human-readable lines instead of dumping raw provider
 NDJSON. The raw dump is gone rather than demoted: the evidence packet now
 ships as a workflow artifact, so the trajectory record — tool identity,
 outcome, paths, failure class — is the forensic surface, and an interleaved
 raw dump is not reinstated even under `ACTIONS_STEP_DEBUG`
- Every review run that resolves a pull request number posts a deterministic run
 record — a sticky progress comment and a mandatory review-body preamble rendered
 from the same function, so a green review that says nothing is no longer
 indistinguishable from a review that never ran
- The merge-evidence packet gains a `run_health` section (schema `1.11.0`) for
 run-scoped findings partitioned out of the top-level `findings` list; change
 findings and run observations now have separate audiences and surfaces
- `Finding.scope` (`change` | `run`, default `change`) and `FindingSource`
 `"trajectory"` so trajectory auditor rows are attributed as process evidence,
 not PR defects
- Job step summary (`GITHUB_STEP_SUMMARY`) written from `_publish` with outcome,
 pre-merge rows, and findings — capped at GitHub's 1 MiB with the header intact
- Evidence packet persisted to a workflow artifact on every review rung
 (`if: always`, 30-day retention) so the packet survives runner teardown
- `MERGECRAFT_ACTION_SHA` workflow variable — one pin definition shared by all
 three review rungs, with `make action-pin-check` enforcing staleness and
 rung parity (#532)
- Action image digest pin gate (`action-image-digest-check`) and halved
 `wait-for-ci` poll cadence (20s → 10s, #528)

### Security

- On the root Linux backend (`CAP_SYS_ADMIN`), the MCP shell sandbox and the
 analyzer sandbox now drop root identity in the same `exec` that installs their
 masks, so the kernel enforces the read-only binds, the scratch mount, and the
 cleared capability sets against a process that can no longer lift them; a
 `sudo`-elevated shell drops back to the orchestrator's own UID/GID, and macOS
 `sandbox-exec` and unprivileged hosts are unchanged.
- Static checks now run with an explicit default-deny environment keyed on the
 trust tier, and path-safe `{files}` arguments: an entry that resolves outside
 the checkout is dropped, an option-shaped relative entry reaches the gate as a
 `./`-path, and no `--` separator is inserted.
- Untrusted static checks run inside the sandbox against a disposable
 copy-on-write view of the checkout. A gate that fails only because the sandbox
 denied it the network or a write is reported as `declared-but-cannot-run`,
 never as a finding about the diff, and the real checkout is left unchanged.
- The image runtime tree under `/opt/mergecraft` stays root-owned — bytecode is
 compiled at build time — instead of being chowned to the agent user, so a
 process dropped to that user cannot rewrite the code the root orchestrator
 imports.
- Local log sinks are scanned for credentials after the run. A hit fails the run
 and the approval gate, names the sink path without ever printing its contents,
 and removes the sink before artifact upload.
- Transitive `soupsieve` 2.8.4→2.9.2 in `uv.lock` for `pip-audit`
 (CVE-2026-85999, CVE-2026-86000) (#728)
- Fork-controlled `.mergecraft/config.yaml` can no longer lift the untrusted
 tracing-content cap; export of prompt bodies on fork PRs requires the Action
 input, env, or trusted base settings
- Codex API-key runs proxy model calls through a loopback credential broker — a
 stolen per-run bearer is worthless outside the container and after the run, but
 outbound egress stays open and ChatGPT subscription auth (`CODEX_AUTH_JSON`) is
 not brokered; clear that secret and use `OPENAI_API_KEY` when broker coverage
 matters (#553)
- The fork-head credential invariant now rejects indexed OAuth, device-code and
 cloud-chain credentials (`LLM_PROVIDER_<N>_CLAUDE_CODE_OAUTH_TOKEN`,
 `_CODEX_AUTH_JSON`, `_AWS_*`, `_GOOGLE_APPLICATION_CREDENTIALS`) instead of only
 flat names and `_API_KEY`; a fork PR can no longer carry a credential past the
 pre-dispatch rejection boundary
- Indexed Codex `device_code` credentials reach the isolated run home's
 `auth.json` and the broker reports `subscription`; `_setup_codex_auth` consumes
 the resolved child mapping instead of reading `os.environ`
- The fork-credential allowlist and the agent-env strip set both derive from
 `config.runtime_provider_registry`, the single credential authority across every
 `authKind`, cloud suffix and spelling — the pinned drift that dropped
 `GOOGLE_API_KEY` is gone, and `AWS_SESSION_TOKEN` is covered
- Critical and Major security findings are no longer demoted when incidental
 maintainability or documentation words appear in the same message; the security
 lane takes absolute precedence and capping rules are inapplicable when impact
 evidence supports the asserted severity
- Security category inference now recognizes `auth`/`unauth` stems and the named
 vulnerability classes (RCE, deserialization, pickle, path traversal, SSRF, CSRF,
 XXE, privilege escalation, prototype pollution, open redirect, hardcoded key)

### Fixed

- Local `--shell enabled` now refuses when no sandbox backend is available unless
 `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` is set; on macOS, `sandbox-exec` is
 the backend when present (#593)
- Tracked public markdown is linted for decision-ledger tokens, -dot
 citations, and pointers into gitignored plans; Priority 1 docs were
 rewritten to stand alone (#709)
- `trivy` on Apple Silicon provisions the native ARM64 build so the local
 coverage gate does not hang under Rosetta
- Action reviews no longer crash at startup with `infra_error` when loading
 the shared token cap (#741)
- Enabled Jev reviews now keep the shadow-judge record next to the evidence
 packet after the command finishes, so paid calibration rows are retrievable
 (#728)
- A TypeSafe connect, DNS, or timeout failure on the shadow judge records a
 skip and leaves the completed review successful (#728)
- `jev.model` accepts only the pinned `jev-1.13.0` id, so a configured newer
 version cannot run while audit rows still claim the pin (#728)
- Corroborating duplicates can no longer weaken a finding: clustering keeps the
 strongest member's severity while the agent's prose stays canonical wording,
 and semantic dedupe keeps the strongest paraphrase with the discarded members'
 evidence — a weaker copy arriving first can no longer turn a CI blocker green
- A partial analyzer rerun no longer erases earlier blockers: results are
 retained by covered scope, so a clean pass over a file the first pass did not
 cover leaves the prior finding, the shared finding count and the
 terminal-approve rejection intact
- `get_commit_info` can no longer replace the canonical review scope with the
 HEAD commit's patch; the single-commit diff stays an inspection artifact, so
 admissible citations, inline anchors and blast radius remain bound to the
 whole change under review
- Default local review includes eligible untracked additions, so a brand-new
 source file is reviewed without knowing an alternate flag; every exclusion —
 gitignored, oversized, binary, symlink — is surfaced as a review-coverage
 limitation, and an all-excluded diff can no longer render as a passed review
 with "no changes to review"
- The Action-pin staleness budget counts changes rather than landings. Without
 `--no-merges`, a PR touching `src/mergecraft/` scored twice — its own commit
 plus the merge that landed it — so the documented budget of 5 was really a
 budget of about 2. Measured at the ceiling: 5 raw commits, 3 of them merges,
 2 actual changes. `MERGECRAFT_MAX_ACTION_PIN_PRODUCT_LAG` is unchanged at 5;
 it now means what it says.
- A stale self-review Action pin on `main` no longer fails every open pull
 request. `action-pin-check`'s staleness rule compared `main`'s pin against
 `main`'s own tip, so it read nothing from the PR under review — one commit of
 debt on `main` froze the whole queue, including the manifest PR that was the
 only way to clear it (#669). The rule moved to `action-pin-staleness.yml`,
 which runs on every push to `main` (with a daily cron backstop) and files one
 tracking issue, keeps it current, and closes it once the pin is bumped. The required PR check
 keeps every rule a branch can act on: rung self-consistency, drift from
 `env.MERGECRAFT_ACTION_SHA`, and freshness against the default branch's pin.
 `make action-pin-staleness-check` runs the full set locally.
- The sticky run record lists Action pin (manifest C) next to baked image
 source (S) so pin-lag (pinning S deploys the previous digest) is visible
 without reading Action logs (#641)
- Untrusted allowlisted analyzers in the Action image can use a userspace
 filtered-egress backend (user+net namespace plus parent TCP relay) when
 host `CAP_NET_ADMIN` / `CAP_SYS_ADMIN` are absent; the analyzer is forked
 so the relay stays alive, and each hostname maps to its own resolved IPs
 (#538)
- Consolidated integration CI retains Python 3.11 and 3.14 coverage after
 prerelease/main reconciliation; the coverage ratchet runs once on 3.14.
- Bring the GitLab review-support matrix correction from main to the prerelease branch.
- Local base-only reviews retain working-tree changes; remote comparisons deepen
 bounded shared history and fail explicitly rather than substitute endpoint diffs.
 Untracked text additions produce valid patches, including special filenames
 and missing final newlines. Binary and non-UTF-8 untracked files are skipped
 with a diagnostic rather than producing a lossy patch or crashing.
- Installed convergence evaluations include their recall corpus. Example drift
 checks run in disposable copies and no longer rewrite tracked outputs.
- Redaction preserves closing assignment brackets and ordinary source paths while
 retaining secret-pattern and high-entropy controls.
- Optional image live checks require an actual terminal review rather than CLI help.
- Self-review App tokens now refresh per provider attempt and revoke after the
 job. Privileged approval uses a distinct App outside the reviewer action and
 requires explicit maintainer dispatch for an exact run/head; reviewer checks
 cannot automatically trigger approval. Missing App configuration fails closed.
- Action images use patched, checksum-pinned npm and GitHub CLI tooling and
 remove unused vulnerable pip bootstrap copies. Both images are scanned before
 merge; release scans retain attributable JSON alongside SARIF without relaxing
 the HIGH/CRITICAL gate. Python installation in the images uses uv.
- Local review honors configured model chains, explicit/environment precedence,
 fallback restrictions, and cumulative budgets; a process without a terminal
 verdict is inconclusive (#592).
- Provider authentication preflights the exact `--cwd` GitHub destination before
 collecting credentials in both canonical commands and legacy aliases, rejects
 unverified secret-management access, and
 keeps explicit local scope independent of GitHub (#591).
- Installed skills use a verified documentation commit containing every linked
 target and teach canonical, explicitly scoped provider authentication (#589).
- Analyzer isolation reports unsupported macOS accurately and warns when trusted
 execution lacks isolation. Filtered Linux egress denies host INPUT access,
 separates concurrent sessions, kills analyzer children on timeout, and cleans
 only owned resources; a disposable
 Linux integration harness exercises the production firewall boundary.
- Credential broker stream failures now close the connection without inserting a
 second HTTP response, and client disconnects release upstream responses (#595)
- Brokered Codex runs preserve configured proxy bypass entries and always bypass
 proxies for the loopback broker, without changing parent proxy settings (#597)
- Removed an obsolete Codex broker auth branch that suppressed the API-key
 authentication diagnostic; subscription authentication is unchanged (#596)
- Release verification uses compatible GitHub CLI policy flags, validates deployment
 candidates automatically, and publishes canonical image tags only after signed
 staging digests verify. Pin preparation safely supports repeat invocations and
 environment-only references; Docker source validation survives optimized Python.
- Release E2E now runs for reusable workflow callers, and image promotion
 requires verified signatures, source provenance, and SBOM attestations.
 Action pin preparation separates the built source from the manifest commit
 consumers execute, preventing deployment of the previous image (#579, #641).
- CLI startup `.env` loading walks up to the git root, like the writers in
 `mergecraft auth` and `tracing logfire` already did, so a credential written
 from a subdirectory is visible on the next invocation instead of landing in
 a nested `.env` nothing reads (#654)
- Logfire `llm.call` rows now include the prompt mergeCraft sent and the model
 output, with a real duration instead of an empty ~2µs span
- Codex, Claude, and Gemini tool-use now shows up as `tool.call` children on
 the same Logfire trace as the review run
- Authentication quick start uses registry labels (`anthropic`, `openai`,
 `google`) instead of harness names that `provider auth` rejects (#590)
- GitHub Action Logfire tracing honors `MERGECRAFT_TRACING_REGION`, so an EU
 write token is no longer posted to the US ingest host (#607)
- Anchor-422 recovery no longer spins on an out-of-range comment index — it
 demotes all inline comments and posts once (#570)
- The published GitHub review body always matches the terminal submission;
 probe strings and split publication races no longer land a placeholder review
 (#572)
- Multi-reviewer findings carry server-stamped `raised_by` attribution on the
 published review; agents cannot supply the field via `submit_review_verdict`
 (#574)
- Token spend slightly over `runBounds.tokenBudget` warns and completes instead
 of failing at the cliff; crossing the hard ceiling still ends the run (#571)
- Coverage delta on pull requests no longer fails when the merge-base branch
 cannot measure coverage; the PR checkout still runs `make coverage-gate` and
 the skip is surfaced as an Actions warning and job-summary line naming the
 base ref and reason (#536)
- Base-branch coverage measurement reads that worktree's
 `.mergecraft/config.yaml` instead of the PR head's — a PR that adds a config
 key and its schema field no longer fails the base run (#573)
- A refused terminal verdict now reaches the deterministic run record by name.
 `rejection_reason` — and the record's reason line — were both gated on the
 packet having no decision, but `decide_approval` always returns one, so
 neither could fire: a run that refused for lack of review scope rendered
 identically to a clean one. The refusal is read from the run state instead,
 and the non-retryable post-run path records it rather than publishing a
 second record that the finalize-time upsert would overwrite
- Git MCP containment: refuse `--no-index`, confine positional paths, deny
 credential paths (`.git/config`, askpass tree), and redact git failure text
 before it becomes a tool result
- Post-run retry loop classifies scope and policy refusals before resuming —
 deterministic refusals no longer spend a second provider turn
- Single Loguru writer with `enqueue=True` and explicit queue drain — runner
 logs no longer interleave mid-line from concurrent stdout/stderr writers
- Bubblewrap namespace failures surface `user_namespace_failure_hint` once
 per run (not gated behind a non-zero Codex exit code)
- `checkov` and `yamllint` catalog rows document linux-amd64 manifest-only
 provisioning instead of presenting as runtime failures
- Git config MCP: deny `config --list` and credential-bearing keys on
 `config --get-all` so brokered auth headers cannot leak through enumeration
- `get_commit_info` validates unified diff evidence before establishing review
 scope; successful `checkout_pr` records scope via `register_review_scope`
- Claude driver: pass ``--verbose`` alongside ``--print
 --output-format=stream-json``. The CLI refuses that pair without it and exits
 1 before emitting a single event, so the Claude backstop failed on every run
 it was ever asked to handle; the failure only became legible once zero-event
 runs began reporting their stderr (#557)
- Trajectory findings no longer block merge: `blocking_findings` is the single
 predicate shared by the terminal-verdict gate, packet gate, and approval check;
 run-scoped rows are dropped before severity grading
- A review whose inline anchors are all invalid still lands its body and verdict
 — anchors are pre-validated against the diff, 422 on non-APPROVE reviews is
 recovered server-side, and a total anchor failure posts zero inline comments
 instead of losing the review (#530)
- Trajectory auditor classifies tool failures before counting them, so
 self-corrected schema slips, policy refusals, and environment faults no
 longer masquerade as ignored errors that block the PR
- Status-check summaries are derived from the evidence packet they report — no
 hardcoded prose that the packet can contradict; failed check posts log at
 WARNING with a matching `::warning::` annotation
- Codex fallback routing reads `decision.verdict` from the in-process evidence
 packet instead of racing the check-runs API

### Changed

- Landing README Example 1 matches the `mergecraft init` / `examples/workflows/`
 scaffold (PR types, `status_checks`, `checks: write`); default trigger copy no
 longer teaches `@mergecraft review` comments, which the scaffold omits
- `evals/README.md` Harbor install pin is `v0.1.0a1`, and live detection is
 documented as `mergecraft review` (Harbor still calls the hidden
 `diff-review` alias)
- AGENTS.md and the consumer skill match the default workflow triggers
- The self-review Action pin on all three review rungs moves to `93a7897c`,
 pin 5 — GitHub Action Logfire honors `MERGECRAFT_TRACING_REGION` (#607)
- Self-review Codex fallback uses `openai/gpt-terra` (GPT 5.6 Terra) instead of
 `openai/gpt-codex`
- The self-review Action pin on all three review rungs moves to `e5f9ed5f`,
 the lane D sync on `pre-0.0.1` (#601). Reviews run the selfReview catalog,
 Claude backstop, green-CI SARIF ingest, and `agentSandbox: same-repo`
 instead of the lane E pin (`4ab87265`)
- Dogfood `trust.selfReview` / `trust.agentSandbox` knobs apply after merge to
 the default branch — `pull_request_target` reads the base config snapshot, not
 the PR head
- The self-review Action pin on all three review rungs moves to `4ab87265`,
 pin 3 of 3 — lane E agent credential broker (#594). Reviews run the loopback
 broker, pinned egress, and Codex routing fixes instead of the lane B pin
 (`4182fd45`)
- The self-review Action pin on all three review rungs moves to `3ed2c798`,
 the lane A/C sync on `pre-0.0.1` (#582). Reviews run publication attribution,
 the token-budget band, and the coverage-gate work instead of the #575 pin
- `runBounds.tokenBudget` is the soft target; `tokenBudgetTolerance` (default
 `0.10`) sets the hard ceiling — set tolerance `0` to restore strict enforcement
- Run record and job step summary token lines name target, ceiling, over-target
 status, and per-phase attribution when phases are recorded
- Policy enforcement modes score a rule's blocking intent from the finding's
 gate-facing severity, so ``contributes_blocker`` is
 read off it rather than computed beside it. ``blocking`` floors a
 non-blocking declared severity to ``Major`` and ``warning`` caps blocking
 severities to ``Minor``, and ``required`` resolves to ``Major`` while declared
 evidence is outstanding so a ``Minor`` or ``Trivial`` obligation still blocks;
 the declared severity is preserved on the finding's ``evidence`` list. No
 review path calls ``evaluate_enforcement``, so the scoring does not reach the
 approval gate. **This reverses 's "blocking no longer promotes
 Minor"**, which left the blocking intent in a field ``decide_approval`` never
 read, so a ``blocking`` rule silently passed while a ``warning`` rule blocked
 (#554)
- Render path: skip short-id assignment for non-hex fingerprints instead of
 aborting review output; export and explain paths stay strict (#493)
- Cheat-signature lint: narrow ``getattr_tautology`` to ``object`` targets so
 legitimate missing-attribute fallback asserts are not flagged; severity stays
 ``error`` (#501)
- Coverage ratchet: merge-base lookup failures and lowered-floor comparison
 failures are mutually exclusive, so honesty tests can assert which guard fired
 (#503)
- Coverage ratchet: document that the merge-base lowering guard is PR-only on
 ``push`` / ``workflow_dispatch``; absolute ``fail_under`` checks still run on
 all events (#506)
- Coverage ratchet: pin ``_default_base_branch`` resolution order
 (``GITHUB_BASE_REF`` → ``GITHUB_REF`` branch → ``pre-0.0.1``) without requiring
 a git remote (#507)
- ``indexed_credential_keys`` rejects unsupported ``cloud_chain`` provider labels
 instead of silently mapping them to Bedrock credential suffixes; the error names
 the offending label and the supported set (``bedrock``, ``vertex``) (#497)
- ``scripts/mutate_decision_modules.py``: ``_enumerate_line_mutants`` and
 ``_apply_mutant`` are importable without reading ``mutation_modules.toml`` at
 module load; the module map is lazy-loaded on first CLI use (#502)
- Regression coverage for the enterprise telemetry reset inside
 ``reset_process_tracer_cache``: leaked ``telemetry: off`` bindings no longer
 block OTLP ``claim_sink`` after cache reset under xdist (#509)

### Security

- Review publication refuses a model-supplied pull number or commit SHA that
 differs from the run's bound scope, and those identity fields are no longer
 exposed on the ``create_pull_request_review`` tool schema

### Fixed

- Pipeline predicate validation no longer rejects repository paths whose names
 contain substrings such as ``subprocess`` or ``import``; the closed regex is
 the sole control
- Pipeline severity predicates include ``Trivial`` and rank unknown severities
 below every taxonomy member instead of treating them as ``Minor``
- Pipeline preview marks non-executing steps as ``dispatched`` instead of
 ``ran``, derives terminal verdicts from collected evidence instead of
 hardcoding ``approve``, and documents ``PipelineExecutor`` as experimental
- ``ReviewEngine.run`` clears the timeout callback on every invocation so a
 second run with ``on_timeout=None`` does not retain the first run's handler
- The test suite no longer mutates the project virtualenv: ``make`` exports
 ``UV_PROJECT_ENVIRONMENT`` to a separate dev env, subprocess ``uv run`` calls
 pass ``--no-sync``, and a session guard detects interpreter replacement
- Gateway credential resolution reads repo settings from the run-scope snapshot
 instead of reloading ``.mergecraft/config.yaml`` on every model lookup, with a
 live-load fallback when no snapshot is installed (#496)
- Gate mode and per-gate action overrides resolve from the run-scope settings
 snapshot instead of package defaults, and packet assembly in ``enforce`` mode
 fails closed with a neutral decision when assembly raises
- Required static checks block approval unless every row is explicitly
 ``passed`` or ``not_applicable``; ``unavailable``, ``error``, ``timeout``,
 and unknown statuses no longer satisfy the gate
- Policy ``required`` enforcement consults ``policy.evidence`` and scores the
 rule as blocking until declared evidence is present; ``blocking`` no longer
 promotes declared ``Minor`` findings to ``Major``. Review does not apply the
 result: no review path calls ``evaluate_enforcement``, so a rule cannot gate a
 merge yet
- Gate assembly attaches the structural ``decision`` row before ``decide_action`` runs,
 refuses untrusted ``decided_by`` values on pre-set packet decisions, and requires an
 explicit ``success`` verdict plus a completed run before ``low_risk_passing`` can select
 ``auto_merge``
- Review publication reads repo settings from the run-scope snapshot taken before
 untrusted execution instead of reloading ``.mergecraft/config.yaml`` from the mutable
 checkout
- Verifier citation paths are confined to the checkout root via
 ``resolve_confined_path``, rejecting traversal, absolute paths, prefix collisions,
 and out-of-root symlinks, and must fall inside the changed-path set
- Shipped ``operational_readiness`` policy pack rules now declare the required
 evidence keys ``enforcement: required`` consults before it treats the rule as
 satisfied

### Changed

- Policy enforcement modes are pairwise distinguishable when a rule is
 evaluated: ``advisory`` caps blocking severities to ``Trivial``, ``warning``
 and ``required`` preserve declared severity, and ``required`` clears only when
 ``policy.evidence`` is satisfied. Review does not consult these modes yet

### Fixed

- Authenticated git operations against GitHub now work at all. The token was
 brokered as `Authorization: Bearer <token>`, which GitHub's git transport
 rejects with `remote: invalid credentials` — `Bearer` is the REST API form,
 and the git endpoint wants HTTP basic auth carrying the token as the password
 under the documented `x-access-token` username. With `GIT_TERMINAL_PROMPT=0`
 and the askpass helper shredded at startup, git had nothing to fall back on,
 so `checkout_pr` failed in every observed review run: reviews either produced
 no verdict at all or reached one only by improvising around the missing
 checkout, at 1.5M-4.8M tokens a run. Removing the persisted `actions/checkout`
 header changed the failure's shape but not its outcome — the header that had
 been doing the real work was checkout's basic one, and mergeCraft's own
 scheme never authenticated a fetch either way. A fetch against a local git
 remote that models GitHub's auth now covers the whole path, so the contract
 is that authentication succeeds rather than that a header string is present
- Git failures that come from a rejected or missing credential are reported as
 terminal instead of as a generic git error, so the reviewing agent stops
 re-running a fetch that cannot start working across attempts
- `actions/checkout` no longer persists its token in the review workflow, the
 shipped hardened example, its template, or the dogfood artifact. A persisted
 `extraheader = AUTHORIZATION: basic...` collided with the `Authorization:
 Bearer...` that mergeCraft's own git layer added at the time, and
 `extraHeader` is multi-valued in git, so both headers went on one request and
 GitHub answered `400 Duplicate header: "Authorization"`. `checkout_pr` failed,
 review scope was never established, and every terminal verdict was rejected —
 a review that found 45 issues posted none of them and burned 9.4M tokens
 against a 5M budget before failing closed. The action authenticates from its
 own `token:` input, so nothing needs persisting; the comment that claimed otherwise
 predated lane A giving those tools header auth of their own

### Changed

- The self-review Action pin on all three review rungs moves to `b3638ea7`,
 the merge commit of #545. Every rung at the previous pin sent git the token
 as `Authorization: Bearer`, which GitHub's git transport rejects, so
 `checkout_pr` failed on every review and the scope guard then refused the
 terminal verdict. A review that reached "approve" on #545 could not publish
 it and the approval gate failed closed with no `mergecraft-approval` check at
 all. `pull_request_target` resolves this workflow from the default branch, so
 a self-review PR cannot consume its own fix; the bump has to follow the merge
- The self-review Action pin on both review steps moved to `b34e9f25`. The
 previous pin (`5b9ded9f`, 23 August) had drifted 107 commits on
 `src/mergecraft/`, so every review since then ran product code that stale.
 The image at that pin carries no `[tracing]` extra, which would have left
 the Logfire wiring exporting nothing, and analyzer defects already fixed by
 #458 / #459 kept surfacing in Action logs. `make action-pin-check` reports
 the drift correctly but gates nothing; #532 tracks wiring it into `make ci`

### Security

- Enterprise audit log defaults outside the agent-writable workspace tree
 (``MERGECRAFT_AUDIT_ROOT`` or ``~/.local/share/mergecraft/audit``); each
 record is hash-chained and verifiable via ``mergecraft audit verify``
- MCP HTTP startup no longer treats a TCP connect probe as proof of identity;
 server-thread failures propagate and ``GET /health`` requires a per-run nonce
- Trace span redaction no longer leaks CLI secrets after a flagged argv token, applies deny-key scrubbing at every nested depth including
 list/tuple containers, and redacts Basic-auth material via the
 shared secret matcher
- Analyzer JSON and JSONL outputs are structurally redacted by key and value before
 persist, so non-prefixed secrets in trufflehog-style payloads do not reach
 prompts or ``.mergecraft/analyzer-runs/``
- Entropy-based secret redaction uses a length-relative threshold with benign-shape
 exclusions for git SHAs, hex runs, and identifiers so legitimate code tokens in
 logs are not mangled unnecessarily
- OpenCode review sessions deny ``webfetch``, ``external_directory``, and
 ``edit``; ``read`` is allowlisted to the checkout and evidence scratch
 instead of ``*``
- Post-run checkout integrity verification via
 ``security.review_integrity`` hashes the tree before review and fails closed
 on mutation
- Privilege drop gates on action-image identity (``IS_SANDBOX`` + ``/opt/mergecraft``)
 instead of uid alone; root outside the image refuses with a policy diagnostic and
 ``MERGECRAFT_ALLOW_ROOT=1`` override
- ``setpriv`` argv carries ``--no-new-privs``, ``--inh-caps=-all``, and
 ``--bounding-set=-all``; fails closed when ``setpriv`` lacks ``--bounding-set``
 support
- Root-side ``git`` subprocesses route through ``utils/git_hardening.git_argv`` with
 pinned safe-config keys; ``make lint`` enforces the route via
 ``scripts/check_git_argv.py``
- ``prepare_workspace_for_agent`` no longer recursively chowns ``.git``; sandbox shell
 binds every registered workspace root's ``.git`` read-only
- Linked-repo ``_rev_parse_commit`` rejects leading-dash revs, validates pinned SHA
 shape, and passes ``--end-of-options`` before the rev
- Sandbox capability probes run real isolation checks instead of gating on ``CI``;
 untrusted MCP shell refuses unsandboxed spawn unless
 ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1``
- Skipped untrusted analyzers emit a ``Minor`` finding
 (``rule_id: analyzers.sandbox-unavailable``) naming missing isolation primitives
- ``sudo-unshare`` shell spawn passes env by name via ``--preserve-env`` with
 ``env=env`` on ``Popen`` so provider keys never appear in argv
- Namespaced shell spawn hides every ``git`` binary and binds ``.git`` read-only
 inside ``unshare`` / ``sudo-unshare`` branches; unsandboxed opt-in runs the raw
 command without host mount soup
- Python ``prep`` installs into ``.mergecraft/prep-scratch/prep-venv`` with a
 default-deny env allowlist so PR build deps cannot mutate the reviewer's
 interpreter or inherit provider credentials

### Fixed

- ``prep`` lockfile selection prefers ``uv.lock`` over a stray ``requirements.txt``;
 ``should_run`` threads one ``cwd`` into ``run`` instead of reading ``Path.cwd``
 twice
- The Action image now installs the `[tracing]` extra
 (`uv sync --frozen --no-dev --extra tracing`). Without it, a workflow wired
 with `tracing-to: logfire` looked correct and exported nothing: the sink
 factory degrades a `logfire`/`otel` sink to `NullSink` and only logs a
 warning, so every Action review since tracing shipped silently dropped its
 spans. Verified against `uv.lock` — omitting the extra uninstalls logfire
 plus its seven OpenTelemetry dependencies
- `mergecraft.yml` now actually passes the tracing inputs it has supported
 since. Both review steps (Nous and the Codex fallback) carry
 `tracing: "true"`, `tracing-to: logfire`, `logfire-token`, and the
 `MERGECRAFT_TRACING_PROJECT` / `MERGECRAFT_TRACING_REGION` env pair

### Added

- `mergecraft tracing logfire wire-workflow --region us|eu` writes
 `MERGECRAFT_TRACING_REGION` into the wired step's `env:`. Logfire serves
 region-specific OTLP hosts and the resolver defaults to `us`, so an EU write
 token (`pylf_v{N}_eu_…`) previously posted spans to the wrong host with no
 way to fix it short of hand-editing the workflow. The key is owned (so
 `unwire-workflow` strips it) but not required, keeping a region-less wire
 complete rather than partial

### Changed

- **Breaking:** enterprise audit events are no longer written to
 ``.mergecraft/audit.jsonl`` inside the workspace by default; set
 ``MERGECRAFT_AUDIT_ROOT`` or read from the new default location
- Analyzer and trace redactors now emit the shared ``<redacted>`` placeholder from
 ``mergecraft.redaction_sentinel`` instead of the legacy ``[REDACTED]`` analyzer spelling
- Overflow agent findings now append to a server-written `### 🗂 Deferred findings` section with full finding text (non-blocking); analyzer overflow remains in `### 🔧 Mechanical findings`
- `review.verificationBudget` (default 24; `0` = no cap) caps verifier dispatches independently of `analyzers.inlineBudget`
- Harbor `MergecraftReviewAgent` resolves the default `uv tool install` ref lazily in
 `install` via `action_pin_minimal` instead of calling it at module import (#403)
- Landing README promoted from `readme_test.md` draft: agent-first layout, glossary links,
 auth table with recommended models, CLI how-it-works section, and `v0.1.0a1` Action pin (RV6)
- `mergecraft init` scaffolds a consumer-ready workflow (`alexhawat/mergeCraft@v0.1.0a1`,
 `pull_request` trigger, `models:` list) matching `examples/config.yaml` and Example 1 (RV6)
- ``probe_capabilities`` is ``lru_cache``-backed; ``reset_detection_cache`` clears
 the probe cache for xdist isolation
- ``detect_sandbox_method`` and ``network_namespace_available`` delegate to the
 cached capability probe with one unified privilege ladder
- Public MCP consumer docs: ``docs/mcp.md`` (install copy per runtime, OpenAI vs
 Anthropic sections), README ``For LLM / Agents`` row linking public stdio install,
 ``docs/agent-loop.md`` parity note, and ``skills/mergecraft/SKILL.md`` public stdio
 plus runtime HTTP Bearer; registry ownership string
 ``mcp-name: io.github.alexhawat/mergecraft``

### Added

- `mergecraft provider disable <label>` clears a provider's credentials so GitHub
 CI stops using it, without hand-editing secrets or workflow YAML. Honours
 `--scope local|github|both` like `tracing logfire disable`, deletes both the
 flat Actions secret (`NOUS_API_KEY`) and the indexed registry key
 (`LLM_PROVIDER_<N>_API_KEY`) plus every alias a provider recognises, treats an
 already-absent secret as cleared, and leaves the `providers:` registration
 intact so `provider enable` re-uses the same env index. Reporting is
 all-or-nothing: one credential that cannot be cleared fails the command rather
 than claiming the provider is off. `--cwd` selects both destructive targets
 (the `.env` and the `origin` repository). `auth` names (`codex`, `claude`,
 `gemini`) resolve onto their registry labels (#520)
- `mergecraft provider enable <label>` names the authenticate half of that
 toggle; it delegates to the existing `provider auth` flow (#520)
- Public MCP product profile: ``mergecraft mcp serve --role public`` mounts six
 semantic tools at ``/mcp/public`` (``review_change``, ``get_review``,
 ``inspect_finding``, ``explain_finding``, ``get_capabilities``, ``get_policy``)
 over the completed-review store without extending ``ReviewEntry``
- Public MCP stdio transport: ``mergecraft mcp serve --role public --transport stdio``
 serves the same six-tool public profile over newline-delimited JSON-RPC on
 stdin/stdout without Bearer auth (HTTP public still requires the per-serve token)
- Generated MCP Registry ``server.json`` at the repo root plus ``docs/mcp-tools.md``
 from public ``ToolSpec`` schemas; ``make mcp-server-json-check`` validates schema
 and drift in ``CI_STEPS`` (live registry publish remains operator G3)
- Offline public MCP tool-selection eval corpus under ``evals/mcp-public/`` with
 fixture prompts and deterministic scorer ``mergecraft.evals.mcp_public`` (no live
 LLM in ``make test``)
- CI SARIF from ruff, mypy, and bandit is review evidence: `error` keeps
 Major/Critical (not clamped to Minor); a listing error on one workflow run
 does not skip later runs; a Major/Critical finding is kept over a less
 severe duplicate fingerprint. Dogfood `.mergecraft/config.yaml` lists those
 three `ciEvidence.sarifArtifacts`, and `.github/workflows/ci.yml` uploads
 them. A ruff SARIF error can fail `mergecraft-approval` (#464)
- `make action-pin-check` also measures the pin against the default branch's own
 tip, not just against the other branch's pin. Comparing pins to each other
 passes when both are equally stale, which is what happened after #457 merged:
 both branches pinned the same SHA and the check reported OK while the reviewer
 ran none of the fixes that had just landed. Lag is counted over
 `src/mergecraft/` only, since docs and test commits do not change what the
 reviewer executes (#450)
- `make action-pin-check` guards the self-review Action pin against drift.
 Because `.github/workflows/mergecraft.yml` runs on `pull_request_target`,
 GitHub resolves its `uses:` pin from the **default branch**, so a fix merged
 to `pre-0.0.1` does not reach the reviewer until it reaches `main` — a skew
 that reached 687 commits undetected and made PR #443 time out on a ceiling
 already fixed on the branch. The check also rejects a one-sided bump that
 leaves the review and fallback steps on different SHAs. Advisory in CI: a
 stale pin is a property of the default branch, not of the PR under review
 (#450)
- First-pass recall metric (`mergecraft eval convergence`, `make eval-convergence`) with multi-round bank cases and a paired regression gate that holds first-pass recall flat while the precision corpus stays at or above its floor
- Open-PR finding ledger in the sticky progress comment — `mergecraft findings ledger --pr N` inspects inline, deferred, withdrawn, and unpublished fingerprints without filing GitHub issues
- Optional recall pass (`review.recallPass`, default off) dispatches `mergecraft-recall` after aggregation; novel findings always publish in the deferred lane
- Optional round-aware budgets (`review.roundBudgets`) scale token, cost, tool-call, and subagent ceilings by review round; defaults stay flat until opted in
- Lens execution recording on `ToolState`, review metadata, and merge-evidence packets; findings may carry optional `lens` attribution
- Collateral lists on `Critical` and `Major` findings name callers, tests, and other files that must move with the fix; inline comments render them under **Also update:**
- Incremental reviews promote deferred findings when their cited path intersects the incremental diff, bias complement lens routing toward lenses that did not run last round, and label first-pass misses on unchanged lines honestly
- Opt-in `antislop` analyzer: YAML rule pack for placeholder code, narrator comments,
 swallowed errors, pass-through wrappers, phantom imports, and related low-quality patterns
 on changed Python and JS/TS files (#393)
- Append-only enterprise audit producer for ``.mergecraft/audit.jsonl`` via
 ``append_audit_event`` and ``record_blocking_decision``; blocking terminal
 verdicts now persist audit events consumable by ``mergecraft audit export``
 (#417)
- `make lint` checks that jobs calling local reusable workflows grant at least the
 permissions the callee declares, catching ``startup_failure`` permission mismatches
 at authoring time (#425)
- Integration PR coverage now measures ``refs/pull/N/merge`` and reports delta vs the
 base branch via ``scripts/check_coverage_delta.py``, distinguishing inherited floor
 breaches from regressions caused by the PR (#432)

### Fixed

- ``prep`` lockfile selection prefers ``uv.lock`` over a stray ``requirements.txt``;
 ``should_run`` threads one ``cwd`` into ``run`` instead of reading ``Path.cwd``
 twice
- ``redact_tool_payload`` caps UTF-8 byte length (not Python character count)
 and keeps a head slice plus a visible truncation marker instead of discarding
 the whole body
- ``redact_url`` preserves ``http`` vs ``https`` when redacting basic-auth
 userinfo
- ``tests/tracing/test_redaction_doctests.py`` executes
 ``mergecraft.tracing.redaction`` doctests
- Webhook signature verification encodes signature operands with UTF-8 surrogateescape
 before ``compare_digest``, so non-ASCII header bytes are rejected instead of raising
 ``TypeError``
- The MCP server no longer mounts a webhook endpoint: a signed delivery was verified
 but processed nothing
- CI workflow log and SARIF artifact zip ingestion now use bounded
 `zf.open(info).read(n)` decompression with per-member, aggregate, member-count,
 and expansion-ratio caps instead of unbounded `zf.read(name)`
- Egress DNS pinning no longer replaces the process-global ``socket.getaddrinfo``;
 guarded downloads use a per-client ``httpx`` transport that connects to
 validated IPs while preserving hostname ``Host`` headers and TLS SNI
- `validate_http_url` rejects whitespace and control characters anywhere in a
 provider URL, not just at the ends. A stored URL is written verbatim into the
 consumer workflow YAML, so an interior newline could open a new key or step
 there. `workflow provider add` also re-validates a stored row before wiring it
- `mergecraft workflow` resolves a relative `--workflow` against `--cwd` on every
 subcommand. The registry config was scoped by `--cwd` while the workflow path
 stayed against the process working directory, so invoking from outside the
 target repository could read config from one repo and rewrite another repo's
 workflow
- The consumer workflow file is replaced atomically by `mergecraft workflow`,
 matching the config writer. A crash mid-write used to leave it truncated
- `provider migrate` validates a migrated `NOUS_BASE_URL` through
 `validate_http_url` like every other URL entry point, instead of storing it
 unchecked
- `.mergecraft/config.yaml` is replaced atomically (temporary file plus rename,
 preserving permissions) by every CLI writer. An in-place write truncates
 first, so a failure partway through left a half-written config behind
- `mergecraft workflow provider add --apply` writes the registry config only
 after the workflow file lands, and rolls the workflow back if that config
 write then fails. Either half failing used to exit nonzero with config on one
 endpoint and Actions on the other
- `mergecraft workflow provider add --url` on an already-registered provider now
 applies the validated endpoint to the row that is wired and persisted. The
 override was validated and then discarded, leaving the workflow on the
 superseded endpoint with no indication the flag was ignored
- Indexed registry credentials survive the legacy credential re-injection in
 `build_agent_env`. When an `LLM_PROVIDER_<N>_*` secret and its deprecated
 counterpart were both set, the legacy value overwrote the registry one for
 API keys, Claude Code OAuth tokens, and the Bedrock/Vertex chains, inverting
 the documented precedence
- `list_check_runs` omits `check_runs` when the listing is truncated, instead
 of returning a partial catalog with `total_count`. Analyzer JSON arrays no
 longer treat a leading `{"error":...}` then `[]` as a clean scan
- Check-suite log fetch skips with a distinct unavailable payload when no
 GitHub client is bound, instead of looking like “no failed runs”
- Catalog-check rejects all-zero `sha256` provenance pins (placeholders that
 made `provision_managed_binary` treat a trailing-slash URL as a directory and
 fail with `Is a directory`). Pip-style tools such as `checkov` and `yamllint`
 now ship `provenance: {}` like `semgrep`; a trailing-slash URL is refused
 with a `ProvisionError` that names the URL (#458)
- Empty Bandit JSON stdout is a clean scan (zero findings) instead of a skip;
 non-object `results` rows fail parse the same way as the SARIF converter;
 unparsable stdout still skips without embedding a raw stdout snippet (#467)
- A transient Nous HTTP 404 (including a false billing/credits refusal) now
 fails over to the next model instead of stopping the run and reporting a
 missing `set_output` schema failure (#466)
- The approval gate now unions agent findings with analyzer findings, so an
 agent Critical or Major finding fails ``mergecraft-approval`` and the
 evidence packet's ``request_changes`` action. An empty finding list still
 stays ``neutral``; untrusted runs still never ``success`` (#460)
- Coverage already below `fail_under` on the base branch stays inherited
 drift even if HEAD drops further; a drop of 1.0pp or more below the floor
 when the base is already at the floor is also inherited, instead of always
 treating `head < base` as caused by the PR (#485)
- A clean mypy JSON typecheck no longer fails the SARIF convert step, so the
 mypy artifact still uploads for review evidence
- Evidence packet `decision.verdict` is a GitHub check conclusion
 (`success` / `failure` / `neutral`); schema version 1.9.0
- `mergecraft-approval` posts `neutral` when the evidence packet was not
 assembled, instead of omitting the check
- Custom provider slugs not in the operator registry now fail closed instead of silently routing to OpenCode; the built-in catalog allow-list was narrowed accordingly.
- Seeded ``tokenhub``/``minimax`` registry rows no longer shadow legacy ``TOKENHUB_API_KEY`` / ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` credentials: ``resolve_runtime_agent`` honours the same legacy fallbacks as ``has_credentials_for_slug``, and ``provider migrate`` can index those keys.
- Repo-native analyzers no longer fall back to an arbitrary PATH binary. When
 the checkout did not provide a tool, resolution fell through to
 `shutil.which`, so a system copy ran against the consumer's code at an
 unpinned version of unverified provenance — Homebrew's `markdownlint`
 locally, `/usr/local/bin/tsc` on a GitHub runner, which is why `tsc` resolved
 instead of skipping. The six tools installed into the checkout
 (`markdownlint`, `jscpd`, `tsc`, `knip`, `vulture`, `typos`) are now
 repo-local only and skip when absent. Toolchain binaries with no repo-local
 install convention (`cargo` for clippy, `go` for govulncheck) are unaffected
 (#427)
- mergeCraft's consumer workflow approval gate now runs in a separate job that
 `needs:` the review-attempts job, so Codex fallback can post `mergecraft-approval`
 before the fail-closed gate samples check-runs (#433)
- An explicit `--model` now beats `MERGECRAFT_MODEL`. `resolve_model` read the env override first and
 returned before it ever looked at the flag, so a review asked for one model and ran another with no line
 saying the request was dropped — inverting the repo's own `ConfigLayer` order (CLI > env > YAML > default)
 and the flag's help text. The named model also heads the subagent chains the harness renders, so it
 reaches the whole run rather than just the top-level dispatch, and `config explain model` now reports the
 YAML layer as the config file alone instead of the env value promoted to its front (#468)
- Offline reviews (`--base`/`--head`, `--diff`, `--cwd`) can record a terminal verdict. Review scope was
 only ever established by `checkout_pr`, which an offline run has no PR for, so `submit_review_verdict` was
 refused on every attempt and a completed review — analyzer findings and all — was never decided. The
 materialized diff now establishes scope on the offline path. The post-run retry loop also stops when a
 resume leaves the identical issue set, instead of replaying a precondition that cannot change between
 attempts (#470)
- Retryability now has one decision path. `_is_retryable_failure` gated on `metadata["retryable"]` alone
 while `_retryable_failure_reason` inferred the same property from the error text, and only the
 metadata-blind one decided — so a driver that omitted the flag was silently read as "permanent" and its
 failure terminated the run. An explicit flag still wins in both directions; an omitted one now falls back
 to inference. A retryable failure at the chain tail is bounded to one in-place retry and then returns that
 failure, instead of re-asking a refusing provider until the attempt cap raised and replaced the real error
 with a cap message (#447)
- Codex `error` and `turn.failed` events are no longer discarded. Codex reports fatal failures as structured
 events on stdout, and the stream handler had no branch for them, so the message was counted and dropped
 and the run reported whatever unrelated text stderr happened to hold — PR #443 surfaced "Reading
 additional input from stdin..." for a quota exhaustion, in the job annotation, the merge evidence packet,
 and the chain log. The provider's own message is now the run's error and feeds retry classification (#445)
- Provider quota exhaustion is now classified as retryable for failover. The CLI classifier matched only
 rate-limit wording (`rate limit`, `too many requests`, `overloaded`, `429`), so Codex's "You've hit your
 usage limit" matched nothing and read as permanent — the chain refused to try the next model even though
 the next model was unaffected (#446)
- `opencode serve` output is now drained for the process lifetime. Boot read the child's stdout only until
 the listening URL appeared and nothing read either pipe afterwards, so once the child filled the ~64KB
 pipe buffer it blocked in `write` and stopped answering HTTP — a hang with no output, indistinguishable
 from an unresponsive provider. A bounded tail of that output is now attached to a provider-timeout error,
 which previously stringified to nothing at all — the tail is read under the same lock the drain threads
 hold, so collecting it cannot raise `deque mutated during iteration` in place of the failure it explains
 (#449)
- A provider timeout no longer kills the review. `ProviderTimeoutError` on the opencode path returned an
 `AgentResult` with no `retryable` metadata, and the model chain gates on that flag alone, so the single
 most recoverable failure there is read as permanent and terminated the run at attempt 1 of 10 — leaving
 the PR with no review rather than a review from the next model in the chain. Gateway 429/5xx responses on
 the same path were mis-classified the same way. Two bounds keep the retries from multiplying: opencode
 gets the initial attempt plus exactly one retry, and the chain now honours a wall-clock deadline derived
 from `RunBounds.run_timeout_s` instead of relying on the attempt cap alone. Every prompt on that path is
 covered, the initial review turn included — the likeliest one to time out, and the one whose timeout
 previously escaped the harness and aborted the chain outright. When the allowance runs out at the chain
 tail, the evidence packet now names the model that actually ran instead of the entry being skipped (#444)
- `mergecraft --version` reported `0.1.0` while the project was at `0.1.0a1`: the number was restated as a literal in `mergecraft/__init__.py` alongside `pyproject.toml` and the two drifted. It is now read from the installed distribution. The value also keys the offline result cache and is stamped on telemetry and eval reproducibility pins, so the mismatch quietly mixed artefacts from different builds
- Managed analyzers no longer report a clean scan as skipped: the adapter's fallback re-parse ran on the
 human-readable output string, which carries the `version_note` prose prefix, so any managed tool whose
 findings stream was empty failed with `Expecting value: line 1 column 1 (char 0)`. TruffleHog hit this on
 every secret-free scan, making a passing scan indistinguishable from a broken analyzer. The fallback is
 removed (it could only duplicate the file parse, and bypassed finding redaction when it did), the output
 read is classified separately so an undecodable file no longer raises `UnboundLocalError`, and analyzer
 output is persisted only from the raw stream
- `staticChecks` withholding no longer depends on how a gate was declared: with `shell: disabled` on an
 untrusted run, gates discovered from the repo's Makefile executed while configured ones were correctly
 withheld — meaning commands from a Makefile that is itself part of the diff under review could run.
 Both routes now go through the same cannot-run reporting, each with a truthful reason
- `review --dry-run` skips the analyzer catalog while still materializing the diff and returning the review prompt (#401)
- `load_audit_events` skips malformed JSONL lines and non-dict payloads instead of raising (#398)
- `route_model` routes security specialist at `critical` risk to the same capable model as `high` instead of Haiku (#394)
- Checkout and packaged `defaults.yaml` copies drifted after README v2; `make pins-check` gates byte identity (#402, #414)
- Hermes generated skill package lists `GEMINI_API_KEY` and `NOUS_API_KEY` (not `GOOGLE_API_KEY`) in `required_environment_variables`, matching `docs/authentication.md` (#415)
- Coverage ratchet floor raised to 80% after new docs contract tests increased measured line coverage above the prior ceiling
- Transitive `h2` 4.4.0→4.4.1 in `uv.lock` for `pip-audit` (PYSEC-2026-3628)
- `mergecraft init` no longer emits `uses:./` in consumer repos — published Action ref instead (V8/)
- `mergecraft init` scaffold drops comment triggers and unsafe `github.event.comment.body` prompt wiring; defaults to `CLAUDE_CODE_OAUTH_TOKEN` (README Example 1 parity)
- Offline `mergecraft review` no longer runs the analyzer catalog twice: the pre-pass in
 `run_offline_analyze` and the reviewing agent's `run_analyzers` call each provisioned tools and
 executed every eligible analyzer over the same diff, doubling review time and duplicating the
 skip block, sandbox probe, and semgrep/trufflehog output in the log. The pre-pass now records the
 inputs it ran under (repo root, changed files, trust tier, shell, analyzer mode, inline budget,
 offline flag, base ref, and a digest of the diff) and `run_analyzers` reuses that result when every
 one of them matches; any difference — and the GitHub Action path, which has no pre-pass — runs the
 pipeline exactly as before
- Offline analyze stores ``AnalyzerRunState`` on the CLI tool context and merges analyzer findings into structured output so CC1 exit codes see Critical/Major hits the agent omitted; result-cache keys include mergeCraft version and a settings digest (#399)
- Managed analyzer binaries are re-verified on every cache hit, not just at download time: the cache
 directory is keyed by the *archive* sha256, so a tool that rewrites itself in place was executed on
 every subsequent run while the path implied the pinned contents. TruffleHog's built-in updater did
 exactly that, silently replacing the pinned 3.96.0 binary with 3.97.0. Provisioning now records the
 installed binary's sha256 beside it and refuses to reuse a cache entry that no longer matches —
 discarding it (updater state included) and re-provisioning from the pin, or failing closed with a
 truthful skip reason when the pinned source is unreachable. TruffleHog is additionally run with
 `--no-update` so the updater never fires

### Changed

- Offline `--use-cache` / `--resume` store only after structured-output finalize and re-validate on hit; cache keys include trust tier, `--prompt`, and related review inputs; `--resume` reads that cache and does not call a no-op checkpoint stub (#378)
- CLI, Action, and SCM share one four-stage review engine (materialize / analyze / review / publish) with per-stage timeouts recorded after each stage; the 1h review budget is snapshot data (the agent self-times); `--resume` is an alias of `--use-cache`; `--agent` negotiates `MERGECRAFT_AGENT_PROTOCOL` and stamps protocol budgets, emitting `phase` events as each engine stage starts (#378, #379, #380)
- Eval methodology: blocker precision is `None` (unpublished) when a run reports no blockers, and severity accuracy is `None` when there are no locality matches — never a vacuous 1.0
- Landing README redesigned as a REACH-style product page (outline B): problem/solution
 cards, architecture hero, numbered install, and jump-nav. Long-form install,
 authentication, and workflow essays moved to `docs/install.md`,
 `docs/authentication.md`, and `docs/workflows.md`.

### Added

- `mergecraft review --shell {disabled,restricted,enabled}` — operator opt-in that makes the seven
 `runtime: repo-native` analyzers (ruff, mypy, bandit, vulture, typos, jscpd, markdownlint) reachable from
 the offline CLI. The offline path previously hardcoded `shell: disabled` at three sites, so those tools
 could never run locally under any configuration and a full local review exercised only the two managed
 analyzers. Defaults to `disabled`, so runs that omit the flag are unchanged; raising it lets analyzers
 execute tooling supplied by the repository under review and is unsafe for untrusted code
- Consumer glossary (`docs/glossary.md`) — plain-language definitions for trust tier, typed
 findings, blast radius, and related landing-page terms; manifest row and `llms.txt` entry.
- Per-harness Agent Skills packages generated from `skills/mergecraft/SKILL.md` via
 `scripts/gen_agent_packages.py`, with `skills/harnesses.yaml` install matrix,
 `make agent-packages-check` in CI, and Hermes/OpenClaw surfaces (#383 bullet 1, RV3)
- Runnable CLI example trees under `examples/cli/` (local diff, branch range, patch
 file, and `--agent` JSONL) with `make cli-examples` / `cli-examples-check` and
 `docs/cli-examples.md` tour page
- Agent-loop reference workflow (`docs/agent-loop.md`) for `mergecraft review --agent` (#383)
- CLI and GitHub Action runs now enter one review engine over one immutable snapshot (#380)
- `mergecraft explain`, `ask`, and `replay` plus `run inspect` / `run diff` print output-only change, line Q&A, and stored-run views (#377)
- `mergecraft review --agent` negotiates protocol version against CLI JSON `schema_version` (both fields kept, aliased), reports retryable mismatches, and names token/cost/tool-call budgets (#379)
- `mergecraft review --agent` streams the first finding before the verdict; `--use-cache` and `--resume` reuse a local result cache; cancelling a review cleans up child processes (#378)
- Generated six-axis support matrix (`docs/support-matrix.md`), RC/soak release process (`docs/release-process.md`), and a security-response plus coordinated vulnerability-disclosure path in `SECURITY.md` (#382)
- Eval methodology (#384): quality metric set (`mergecraft.evals.quality_metrics`), ablation harness (`mergecraft.evals.ablation`), expanded human-reviewed golden corpus plus a separate synthetic mutation corpus (`mergecraft.evals.corpora`), and a `docs/eval-methodology.md` page registered in `docs/manifest.yaml`. Scores stay off the landing README; #140 still owns publishing precision/recall/.
- Enterprise runtime (`mergecraft.enterprise`): offline/self-hosted install plan citing the Python 3.11 floor, HTTP(S) proxy with `HTTPS_PROXY`/`NO_PROXY` export, custom CA certificate loading via `ssl.SSLContext`, data-residency allow-list enforcement, configurable telemetry with on/opt-out/off modes, support bundles with secret redaction, audit-log and usage/cost export, blocking-decision explainability, trace-retention policy with privacy-aware log mode, operational diagnostics, organisation policy/memory distribution without a dashboard. New CLI verbs: `mergecraft health`, `mergecraft audit export`, `mergecraft support-bundle`. (#381)
- Agent install surfaces: `AGENTS.md`, consumer skill (`skills/mergecraft/SKILL.md`),
 Claude plugin manifests (`.claude-plugin/`), slash commands (`commands/`),
 GitHub Copilot instructions (`.github/copilot-instructions.md`), curated
 `llms.txt`, and a **For AI coding agents** section on the landing README.
- `llms-full.txt` generated concatenation plus docs pin/link gate (`make llms-check`,
 folded into `make docs-check`).
- Added: generated CLI and Action reference pages (`docs/cli.md`,
 `docs/action-reference.md`) plus a docs manifest; `make docs-check`
 replaces landing-README table splices.
- A provider capability catalog names context size, reasoning and tool support, structured-output support, cost, latency and data residency for the bundled models, and a residency allow-list check refuses a model outside the regions the enterprise policy permits (#371)
- Review specialists now report unique useful findings plus latency, cost, precision, and recall (#370)
- Review profiles now include `standard`, `api_compatibility`, `migration`, `monorepo`, and `cross_repo` (hyphen aliases on the CLI); `mergecraft profile recommend --risk` auto-selects from change risk, with CLI then policy overrides; profile budget exhaustion stays `inconclusive`, never a clean pass (#369)
- `.mergecraft/config.yaml` now carries a `schema_version`; unversioned files migrate on load, unknown versions fail closed, and deprecated keys warn before a breaking removal (#368)
- Review profiles record an explicit ``latency_budget_ms`` field beside their token, cost and tool-call budgets — the three budgets are exported to the run, the latency figure is recorded only; ensemble spend over the profile cost ceiling fails closed; cheap classification runs before specialists, independent work can run in parallel, and structural summaries compress context before an LLM step; early-stop fires when evidence is already sufficient, routing considers remaining budget, and regression/monorepo benches exist without publishing measured cost or latency numbers (#367)
- `mergecraft doctor --supply-chain` verifies lockfile reproducibility, bundled agent-CLI provenance, and analyzer version pins; every run manifest now records runtime and tool versions (#366)
- Failure-injection, soak, high-concurrency, monorepo, and large-PR harnesses now pin production SLOs for review completion, time to first finding, total review latency, and publication success, with a closed reliability error taxonomy and per-stage latency metrics (#364)
- A mid-review provider outage degrades instead of crashing; corrupt local cache rebuilds, disk and memory preflight fail closed, giant repositories skip or partial, SCM publication is idempotent, runs resume from a checkpoint, cleanup runs on timeout/cancel/crash, and diagnostic bundles redact secrets (#365)
- `mergecraft eval gate` now blocks a release when a prompt-injection, malicious-repository, or malicious-ticket corpus case regresses; reviewing a local path or public URL treats the tree as attacker-controlled input (#363)
- `mergecraft memory validate` checks the learnings store; learned behaviour needs historical evidence or explicit approval; factual / policy / preference / false-positive memory stay distinct; organization memory is a pluggable backend; effectiveness metrics track precision and recall together (#360)
- `mergecraft policy effective` and `simulate` resolve the effective rule set (with the source of every rule, including symbol scope), detect same-scope enforcement conflicts, emit policy audit artifacts, and report trigger / false-positive / waiver / blocking rates (#358)
- Shipped policy packs for security, public API, migrations, dependency changes, authentication/authorization, testing, and operational readiness; each rule keeps stable identity fields and ships should-trigger / should-not fixtures for `mergecraft policy test` (#359)
- `mergecraft context search` and `explain` score retrieved context, allocate per-specialist token budgets, fetch lazily through controlled tools, and record omitted scope so the evidence outcome is downgraded; retrieval quality is scored separately from the model (#356)
- Reviewed-repo instruction discovery now includes `GEMINI.md`, GitHub Copilot instructions, Windsurf rules, `SKILL.md`, and a configurable extra list; injected instruction bytes are hashed into the run manifest, competing sources record a winner, untrusted files stay inside the nonce fence, and `--context` files enforce type, size, trust, and provenance (#357)
- Review findings are ranked by materiality (security outranks style), publication and blocking floors plus per-severity, category, file, and review budgets are configurable; dismissals record a closed reason code for evaluation (not durable memory), and a release-wired corpus gate compares blocker precision against a configured floor (#355)
- `mergecraft evidence show` and `verify` display and replay a finding's evidence packet (six verifier states, freshness, provenance hash, completeness); unverified findings do not block unless policy allows it, and a failed verifier cannot promote a finding to proven (#354)
- `mergecraft xrepo explain` reports SHA-pinned linked-repo producer/consumer contract breakage without writing the reviewed tree; policy can require cross-repo review before a public-contract change passes (#353)
- `mergecraft requirements inspect` and `explain` map ticket and local-spec text to requirement states without writing the reviewed tree; policy can require that evidence before a review passes (#352)
- `mergecraft describe` prints an output-only PR title, summary, walkthrough, risk, labels, TODOs, effort band, split advice, and similar-change notes (#351)
- `mergecraft capabilities` prints the review-only capability manifest (modes Review, IncrementalReview, Plan; identify / investigate / verify / explain / prioritize / suggest) (#350)
- Python 3.11 install floor (#343, option A): `requires-python` lowered to `>=3.11`; mypy/Pyright target 3.11; CI matrix runs on 3.11 and 3.14. README and `docs/distribution.md` install copy use stock `uv` from git (PyPI not published); Docker remains for pinned runtimes. Parenthesized the last PEP 758 site in `analyzers/detect.py` for the 3.11 compile gate; `harbor` extra gated to Python >=3.12.
- Python 3.11 floor ADR (#343, option A): `docs/dev/python-version-floor.md` records parenthesize-now / binary-later. PEP 758 multi-type `except` handlers under `src/mergecraft/` are parenthesized (44 sites / 27 files).
- JS/TS lint: `biome` and `eslint` declare `supports_fix: true`; the JS-lint exclusive group (`js-lint`) now resolves the winner by config-file presence alone — `biome.json`/`biome.jsonc` beats any eslint config; eslint config beats any oxlint config — package-script and dependency signals are only consulted when no config file is found (, #310)
- `mypy` is now the default type checker for Python repos with no explicit type-checker config: auto-enabled when neither `pyrightconfig.json` nor `[tool.pyright]`/`[tool.basedpyright]` is present (, #309)
- `osv-scanner` detect globs now include `uv.lock`, so repos using uv's lock file trigger vulnerability scanning without pip-audit (#309)
- docs: `flake8` and `pylint` catalog entries note they are legacy opt-in; enabled via config override only (#309)
- Catalog manifests for `knip` (JS/TS unused exports/dependencies, `scope: repo`, `category: quality`) and `vulture` (Python dead code, `scope: repo`, `category: quality`) (#337)
- Catalog manifests for `govulncheck` (Go vulnerability scan, `scope: repo`, network allowlist `vuln.go.dev`), `cargo-audit` (Rust advisory vulnerability scan, `category: vuln`), `cargo-deny` (Rust license/advisory check, `category: license`), and `typos` (universal typo checker, `scope: repo`, `supports_fix: true`) (#337)
- Catalog manifests for `tsc` (TypeScript whole-program lint, `scope: repo`, `--noEmit`), `bandit` (Python security, version pinned to `make security` pin `1.9.4`), and `jscpd` (copy-paste detection, `scope: repo`, diff-line attribution via existing `filter_to_diff` pipeline — pre-existing clones off the diff are dropped) (#337)
- Flip `golangci-lint`, `clippy`, `rubocop`, `phpstan` to `default_enabled: auto`; adds `go.mod`, `Gemfile`, `composer.json` to their detect globs; RuboCop gates on config presence (— silent without `.rubocop.yml`/`Gemfile gem`); PHPStan injects `--level=0` when no `phpstan.neon` is found (#338)
- `detekt` flipped to `default_enabled: auto`; activates on any `*.kt` or `*.kts` change, or when `detekt.yml` is detected — provides the default Kotlin lint path (#317)
- `swiftlint` flipped to `default_enabled: auto`; activates on any `*.swift` change or when `.swiftlint.yml` is detected — provides the default Swift lint path (#318); reports `unavailable` on Linux runners (requires macOS, `declared_unavailable`)
- `sqlfluff` flipped to `default_enabled: auto`; activates on any `*.sql` change or `.sqlfluff` config presence — skips silently when no SQL dialect is declared (#319)
- `stylelint` flipped to `default_enabled: auto`; activates on any `*.css`/`*.scss` change or `stylelint.config.js`/`.stylelintrc.json` presence — provides the default CSS lint path (#320)
- `htmlhint` flipped to `default_enabled: auto`; activates on any `*.html` change or `.htmlhintrc` presence — provides the default HTML lint path (#321)
- `yamllint` flipped to `default_enabled: auto`; activates on any `*.yaml` or `*.yml` change or `.yamllint` config presence — provides the default YAML lint path (#323); `shellcheck` and `hadolint` were already `auto` (#322, #324)
- `checkmake` flipped to `default_enabled: auto`; activates on any `Makefile`, `makefile`, or `*.mk` change — provides the default Make lint path (#325)
- `markdownlint` flipped to `default_enabled: auto`; activates on any `*.md` change or `.markdownlint.json`/`.markdownlint.yaml` presence — provides the default Markdown lint path (#326)
- `tflint` and `checkov` both flipped to `default_enabled: auto`; activate on any `*.tf` or `*.tfvars` change; the shared `iac-scanner` exclusive group was removed (split to `exclusive_group: null`) so both tools run concurrently — `tflint` provides Terraform lint, `checkov` provides IaC security scanning (#327)
- `luacheck` flipped to `default_enabled: auto`; activates on any `*.lua` change or `.luacheckrc` presence — provides the default Lua lint path (#328)
- `fortitude` flipped to `default_enabled: auto`; activates on Fortran files (`*.f90`, `*.f95`, `*.`, `*.f03`, `*.f`, `*.for`) or `.fortitude.toml` — provides the default Fortran lint path (#329)
- `regal` flipped to `default_enabled: auto`; activates on any `*.rego` change — provides the default Rego/OPA policy lint path (#330)
- `psscriptanalyzer` flipped to `default_enabled: auto`, adds `*.psd1` detect glob, and sets `supports_fix: true` — provides the default PowerShell lint and auto-fix path (#331)
- `blinter` flipped to `default_enabled: auto`; activates on `*.bat`/`*.cmd` changes — provides the default Windows Batch lint path (#332)
- `shopify-theme-check` flipped to `default_enabled: auto`; gates on `.theme-check.yml` or the canonical Shopify theme layout (`sections/`, `templates/`, `snippets/` dirs) — bare `*.liquid` files do not trigger it (#333)
- `smarty-lint` flipped to `default_enabled: auto`; `ANALYZERS.md` notes that `*.tpl` is ambiguous (Go templates, Terraform) — enable only when `.smarty-lint.json` confirms Smarty intent (#334)
- `ember-template-lint` flipped to `default_enabled: auto`, sets `supports_fix: true`; gates on `ember-cli-build.js` or `ember-source` in `package.json` — bare `*.hbs` files do not trigger it (#335)
- `prisma-lint` flipped to `default_enabled: auto`; ships a conservative fallback ruleset (`prisma-lint-default-rules.yml`) and sets `config_note` referencing it when no repo-level prisma-lint config is found — avoids inert no-op runs (#336)
- `cppcheck` flipped to `default_enabled: auto`; activates on any `*.c`, `*.cpp`, `*.h`, or `*.hpp` change — provides the default C/C++ SAST path (#315); `clang-tidy` remains `default_enabled: false` (requires `compile_commands.json`,)
- `pmd` flipped to `default_enabled: auto`; activates on any `*.java` change or `pmd.ruleset.xml` presence — provides the default Java lint path (#312); `infer` remains `default_enabled: false` (requires compilation database,)
- `phpcs` and `phpmd` remain `default_enabled: false`; catalog entries note they are legacy opt-in — `phpstan` (auto) is the default PHP signal (#316)
- `brakeman` flipped to `default_enabled: auto` with tight Rails detection — only activates on Rails marker files (`config/application.rb`, `config/routes.rb`), never on plain Ruby repos (#313)
- New catalog manifest for `bundler-audit` (Ruby gem vulnerability audit, `category: vuln`, `scope: repo`, detects on `Gemfile.lock`) (#313)
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
 (`docs/dev/provider-harness.md`); opt-in sanitized capture under.
- Cross-repository intelligence indexes linked repos at pinned commits, contract surfaces (OpenAPI, GraphQL, protobuf, exports), cross-repo blast radius, reproducible citations, and ticket acceptance-criteria mapping under `mergecraft.xrepo` and `mergecraft.requirements`
- Repository context engine indexes per-file symbols (tree-sitter with generic fallback), provenance citations, and trust-gated instruction/skill discovery under `mergecraft.context`
- Call graph, change graph (changed symbol → dependents → tests → contracts), and `mergecraft context inspect` for provenance-backed context retrieval
- Feedback capture for findings (accepted / dismissed / disputed) keyed by fingerprint, with bounded negative-memory suppression, TTL/recency weighting, contradiction detection, and `mergecraft memory list|show|forget|export|import|feedback` lifecycle verbs
- Policy-as-code package (`mergecraft.policy`) with schema-validated YAML rules, deterministic org/repo/path scoping, enforcement modes that classify a rule's blocking intent (review does not consult them), required-evidence inconclusive handling, and bounded exceptions with expiry
- `mergecraft policy lint|test|explain` — validate policy rules, run should-trigger/should-not fixtures, and list effective rules with source layers
- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews
- Large-PR review engine: cluster changed paths by dependency and intent, build hierarchical diff context (map → summaries → raw hunks) with token-budget scope reduction that reserves verbatim hunks for high-risk regions, record disputed/waived/stale finding lifecycle states, and emit advisory-only PR split recommendations from independent change groups
- Finding precision pipeline: deduplicate agent/analyzer findings before publication, apply a code-defined severity rubric at the verifier seam, require structured causality on blocking findings, suppress pre-existing analyzer hits via baseline comparison, and classify generated/minified/vendored paths for review policy
- precision corpus gate (`evaluate_dg1_precision_corpus`) replays the corpus and compares confirmed precision against the pre-DG1 baseline
- PR utilities: standalone describe output (`mergecraft.pr.describe`), text-only changelog/docs/test suggestions, deterministic TODO scan, classifier-derived effort bands, advisory label suggestions, and `/mergecraft review` comment routing with author-association and permission gating (`mergecraft.mcp.comment_router`)
- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy
- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win
- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache
- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets
- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default
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
- Added typed specialist handoff and model-diversity policy for verification. An agent binding's `dispatch` key accepts `single`; `ensemble` and `shadow` are refused with a configuration error naming the mode as not implemented, instead of being accepted and then ignored
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
 (`- name:...` / ` uses: alexhawat/mergeCraft@X`) and the inline
 (`- uses: alexhawat/mergeCraft@X`) step forms; creates a `with:` block
 when absent (README Example 1 has no `with:`); public API under
 `mergecraft.cli.tracing_logfire_wf_yaml.apply_logfire_wiring` /
 `remove_logfire_wiring` / `render_workflow_diff`
- `scripts/gen_reference_docs.py` regenerates README's `action.yml` input/output
 tables and CLI command table from the live sources (never a subprocess — it
 walks the live Typer `app` object) and splices them between HTML sentinel
 comments; `make reference-docs-check` (wired into `make ci-static`) fails the
 build on drift. Closes the audit in the issues-showcase-readiness (PR G2): the README table documented 9 of 24 real `action.yml` inputs and
 neither declared output anywhere

### Changed

- `mergecraft review` uses `--output-format {text,json,jsonl,sarif}` (not `--format`) so it no longer collides with root `--format {table,json}`; root `--format json` selects JSON when `--output-format` is omitted; explicit `--output-format text` wins over inherited JSON. Human-readable review text stays on stderr — document `2>` for capture.
- Thermo-nuclear CLI remediation: global `--format json` now drives every `--json`-capable subcommand (`eval`, `findings`, `learnings`, `memory`, …) with a pinned `schema_version`; invalid `--log-level` exits `2`; eval replay regressions exit `12` (`CLI_FAILED_EXIT_CODE`); duplicate `_bail` helpers collapsed to `mergecraft.cli.errors.cli_bail`; `CLI_SUCCESS_EXIT_CODE` / `CLI_USAGE_EXIT_CODE` moved to `mergecraft.cli.exits`; colour policy runs once via pre-help bootstrap. `findings export` uses `--output-format {json,markdown}` (not `--format`) so it no longer collides with the root `--format {table,json}` switch; explicit markdown wins over inherited JSON. `eval_cmd` split into `eval_cli_output.py` / `eval_gate_cmd.py`; `diff_review_cmd` and `gha_cmd` route exit helpers through `mergecraft.cli.exits`.
- Global CLI surface (#342): root `--format {table,json}`, `--quiet` / `--verbose` / `--log-level`, and `--color {auto,always,never}` honour `NO_COLOR`, `FORCE_COLOR`, and non-TTY sinks; JSON payloads carry `schema_version`; `review` is the documented command and `diff-review` is a hidden deprecated alias (one stderr line per invocation).
- CLI exit-code contract (#341): every exit under `src/mergecraft/cli/` routes through named constants (`mergecraft.cli.exits` / `RunOutcome` helpers); usage errors exit `2`. See [`docs/EXIT-CODES.md`](../../docs/EXIT-CODES.md). **Breaking:** scripts that branched on exit code `1` for generic CLI failures must follow the new table (most former `1` paths now exit `30`).
- Shell completion for the `mergecraft` CLI: `mergecraft --install-completion` (bash/zsh/fish) and `mergecraft --show-completion` (#340). CLI status and Rich chrome now go through shared stderr consoles; machine-readable `--json` payloads stay on stdout only.
- Dependabot now batches patch and minor bumps into one grouped PR per ecosystem (pip, github-actions, docker, and the `docker/agent-clis` npm lockfile), with security updates in their own group and majors still opened individually; `open-pull-requests-limit: 5` caps each ecosystem
- `mergecraft review` skips PRs authored by `dependabot[bot]`: the gate failed closed on every version bump (the reviewer posted no `mergecraft-approval` check-run, so the enforce step's fail-closed branch blocked the PR). Both jobs are conditionally skipped rather than untriggered, so a rule requiring `mergecraft review` still reports. `changelog-preview` is deliberately left running — it already passes on bot PRs, and skipping a reusable-workflow caller would report under the bare caller job id rather than the two-part `changelog-preview / preview` check name. CI, CodeQL, the security-audit Verify job, and SHA pinning still gate these PRs
- `.github/agents/dependency-pr-manager.md` — dry-run-first sweep agent for the dependency-PR queue: classifies each bot PR into auto / review / blocked / suspicious lanes, diff-audits that a bump touches only its manifest and lockfile, and writes a per-major review brief instead of merging majors blind
- `mergecraft review --help` now states that no flags are required and includes full example commands for local worktrees, GitHub branches, and present or past PRs
- Stale pytest `xfail(strict=False)` markers that were already passing are now real tests; remaining allowed-tree xfails are strict (#276)
- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`
- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

### Fixed

- Evidence image uploads, issue comments, and PR label tools work on review-only runs again
- Linked-repo contract breakage is included in ordinary PR checkout, not only `mergecraft xrepo explain`
- Linked-repo checkout reads only operator-granted siblings, and skips a sibling whose HEAD is not the pinned SHA
- Webhook signature verification fails closed without a configured secret
- Untrusted download and clone URLs are SSRF-checked, and binary downloads pin DNS to the validated addresses
- `bandit` now uses built-in `--format json` instead of the optional SARIF extra, so auto-enabled Python security coverage still runs on plain Bandit
- `bundler-audit` now runs the gem CLI (`bundler-audit check --format json`) instead of `bundle audit`, so Ruby lockfile audits actually execute
- `tflint` no longer passes changed `.tf` files as positional args (invalid since TFLint 0.47); it lints the working directory and the pipeline still scopes findings to the diff
- `phpstan`, `golangci-lint`, and `sqlfluff` now skip when a PR only changes enablement markers (`composer.json`, `go.mod`, `.sqlfluff`) and has no source files to lint, instead of running with empty paths or linting the whole tree
- `bundler-audit`, `cargo-audit`, and `cargo-deny` findings no longer fake a line-1 GitHub anchor when the tool did not report a line; crate/gem coordinates stay in the message
- `clippy` now runs as `cargo clippy --message-format=json` (package/workspace) instead of passing PR paths as cargo args, so auto-enabled Clippy keeps rustc JSON findings
- Auto-enabled analyzers whose stdout is not SARIF now keep findings: `cargo-audit` (`--json`), `cargo-deny` (`--format json`), `vulture` (line text), `tsc` (`--pretty false`), `knip` (`--reporter json`), `jscpd` (`--reporters json`), `bundler-audit` (`--format json`), `sqlfluff` (`--format json`), and `clippy` (`--message-format=json`); `typos` 1.32.0 already emits SARIF and stays on `parser: sarif` (Thermos Finding 1)
- A successful analyzer with empty stdout (for example a clean `tsc --noEmit`) is treated as passed instead of unavailable
- `tsc` project-level diagnostics without a file location (for example `error TS18003`) now surface as body-only findings instead of a silent pass
- `tsc` help text and other unmatched nonempty stdout now fail closed instead of counting as a clean pass
- Project-level `tsc` findings survive diff scoping when the PR only changes `.ts` / `.tsx` files
- `phpstan`: command changed from `--error-format=json` to `--error-format=sarif` so the output aligns with `parser: sarif`; previously the JSON output caused `parse_sarif` to raise `ValueError` and silently drop all findings (Thermos Finding 1, #338)
- `brakeman`: command changed from `-o brakeman.sarif` (writes to file) to `-o -` (stdout) so the SARIF output is captured by the adapter; `parser: sarif` is unchanged (Thermos Finding 1, #338)
- MCP HTTP server now issues a separate bearer token for the orchestrator ``/mcp`` route; reviewer/verifier harnesses keep ``ToolContext.mcp_auth_token`` for their role endpoints (#349)
- OpenCode gateway ``extra_options`` generation knobs (temperature, ``top_p``, ``max_tokens`` when a context window is known) are applied through provider model ``limit`` / ``options`` and the primary ``build`` agent config instead of being copied into ``provider.options``; ``llm.call`` tracing stamps only params the config path actually applies (#295, #349)
- `tracing/genai`: `_optional_float` now rejects non-finite float values (`NaN`, `Inf`) and their string representations (`"nan"`, `"inf"`), matching the existing behaviour of `_optional_int`; invalid temperature/top_p degrade to omitted knobs instead of propagating the sentinel value (#348)
- OpenCode ``llm.call`` spans now carry ``ModelParams`` request knobs (``gen_ai.request.max_tokens``, temperature, and siblings) resolved from gateway ``extra_options`` env vars (``MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS``, indexed ``…_<N>``, or per-provider ``MERGECRAFT_PROVIDER_EXTRA_OPTIONS``) including named presets when only ``NOUS_API_KEY`` / ``TOKENHUB_API_KEY`` are set (#295)
- OpenCode HTTP ``llm.call`` usage attrs omit unset counters instead of zero-filling ``gen_ai.usage.*`` when the session response reports output tokens only (#297)
- `mcp/server`: `submit_review_verdict` (`TERMINAL_PROTOCOL`), `verify_agent_findings` (`VERIFICATION`), and `record_finding_verdict` (`REVIEW_WRITE` + `mutates=True`) were absent from the primary `/mcp/reviewer` surface — the playbook's "verify then publish" loop could not execute. `TERMINAL_PROTOCOL` and `VERIFICATION` are added to `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES`; `record_finding_verdict` is added to `PRIMARY_MUTATING_ALLOWLIST`. Subagents keep `REVIEWER_ALLOWED_TOOL_CLASSES` (none of the three classes) and `READONLY_MUTATING_ALLOWLIST`, so they remain denied all three tools. Verifier still has no `record_finding_verdict` and no `terminal-protocol` tools
- `agents/claude`: `write_mcp_config` wrote a single MCP server entry pointing to `/mcp/reviewer` (derived from the orchestrator's `current_agent_id` at `_run` start). Verifier subagents inherited that config and called `/mcp/reviewer` instead of `/mcp/verifier`. `write_mcp_config` now always writes two entries — `MERGECRAFT_MCP_NAME` → `/mcp/reviewer` and `MERGECRAFT_VERIFIER_MCP_NAME` → `/mcp/verifier` — without using `current_agent_id`, so the verifier surface is available to subagents from the moment the orchestrator launches; `test_role_dispatch_urls.py` now tests the production call path rather than a fake `agent_run_span`
- `tracing/sinks`: `sink_factory` dedupes resolved `OTLPSink` instances by endpoint and headers before fan-out, so a `logfire` + `otel` pair aimed at the same OTLP destination emits one span per `TraceEvent` instead of N identical rows; the #293 processor singleton guard is unchanged (#372)
- `tracing/exporters`: `OTLPSink.write` now passes `TraceEvent.ts_start_ns` / `ts_end_ns` into OTel `start_span` / `span.end`, so Logfire span duration matches provider wall time instead of zero-width export-time stamps; the `duration_ms` attribute is unchanged (#373)
- `tracing/exporters` / `tracing/otel_bridge`: exported spans now carry OTel parent context from `parent_span_id` and use mergeCraft `span_id` (first 16 hex chars) as the OTel `span_id`, so Logfire trace trees link correctly; `attach_trace_context` propagates the same ids for nested auto-instrumented calls (#374)
- `llm.call` spans now stamp `gen_ai.system`, `gen_ai.usage.*`, and `gen_ai.response.model` when the provider reports them, and `mergecraft.usage.unavailable=True` when it does not — driver parity across OpenCode HTTP, Claude streaming, and the model-chain close site; codex and gemini already stamped `gen_ai.system` on their streaming close paths (#375)
- `tracing/exporters`: `_setup_tracer_provider` no longer stacks a duplicate `BatchSpanProcessor` / OTLP exporter on every `OTLPSink` construction — when a real `TracerProvider` already exists and the same endpoint is already registered, the function reuses the existing processor pair instead of appending another one, eliminating the ~29× duplicate OTLP rows per span observed in production (#293)
- `tracing/tracer`: `get_tracer_from_settings` pins `MERGECRAFT_TRACE_ID` on first mint and reuses a process-wide `Tracer` when tracing settings match, so MCP-style `tools/call` handlers on a worker thread share one Logfire `trace_id` instead of minting a new tree per call (#292)
- `tracing/resolve`: ``MERGECRAFT_OTEL_ENDPOINT`` (or ``--otel-endpoint``) with no explicit ``tracing_to`` now selects an OTLP sink instead of falling through to ``jsonl_file`` — the endpoint env var implies OTLP export
- `tracing/_tool_attrs`: `enrich_tool_response` now classifies `ToolResult.is_error=True` as an error span even when no Python exception is raised — `tool.exit_code=error`, span status `error`, and `gen_ai.tool.output` set for the GenAI dashboard; JSON-RPC is unchanged (#296)
- `analyzers/trust`: `build_review_source` detects a linked git worktree of the same repo (same `git rev-parse --git-common-dir`) and sets kind `"local_worktree"`, which `derive_source_trust_tier` maps to `"trusted"` without `--trust`; temporary clones and unrelated repos remain `"untrusted"` (#294)
- `mcp/git_guards`: six guard functions (`_is_config_flag`, `_subcommand_declares_shorts`, `_reject_config_flags`, `_reject_namespace_flag`, `_reject_branch_writes`, `_reject_file_writing_flags`) and ten guard constants extracted from the 754-line `mcp/git.py` into a dedicated `mcp/git_guards.py` module; `mcp/git.py` re-exports every name so existing `monkeypatch` targets continue to resolve (#299)
- `cli/auth`: authenticating a provider left the contributor unable to run the CLI locally — `mergecraft auth codex|claude|gemini|cursor|nous|tokenhub|minimax` persisted the captured credential only through `gh secret set`, so it landed in GitHub Actions secrets and nowhere the local runtime reads. All seven now take `--scope local|github|both` (default `github`, so a CI-only setup keeps today's behaviour exactly, including the hard failure when the secret write fails), and `--scope local` needs no `gh` auth and no network. `auth codex` captures `auth.json` before its isolated `CODEX_HOME` tempdir is deleted, and the pretty-printed multi-line payload `codex login` writes is compacted to one line and quoted, so the `.env` entry round-trips through both `dotenv` and `source.env` (#221)
- `cli/auth`: running `mergecraft auth … --scope local` from a subdirectory reported success while writing a nested `.env` that nothing reads — the local path fell back to `.env` in the current working directory; it is now anchored at the git repository root, and a run with no repository to anchor to fails with a pointer to `MERGECRAFT_ENV` instead of writing somewhere useless. `$MERGECRAFT_ENV` still wins when set (#221)
- `agents/codex`: every Codex review failed to start whenever a custom OpenAI-compatible provider was configured (`MERGECRAFT_CUSTOM_PROVIDER_*`) — the generated `config.toml` emitted the `default_permissions` profile name *after* the `[model_providers.*]` tables, so TOML scoped it into a provider block and Codex never saw the read-only review permission profile; the generated file now always emits every root scalar ahead of the first table header, whatever order the writer populated them in, so the same ordering also covers `sandbox_mode` on the non-profile path (#222)
- `agents/structured_handoff`: a specialist handoff whose `---typed-findings---` marker differed in casing from the documented lowercase spelling lost every finding it reported — the marker was detected case-insensitively but the text was then split on the exact-case literal, so the payload came back empty and `parse_specialist_handoff` raised `ValueError: … not valid JSON` instead of returning the findings; the split is now a case-insensitive regex search over the original text, which keeps the offsets valid even when the prose half contains non-ASCII characters that `casefold` would lengthen (#261)
- `agents/ensemble`: when two ensemble models disagreed, `reconcile_ensemble` returned only the primary model's findings, so a real problem that only the secondary reviewer caught — up to and including a Critical the primary missed entirely — was silently discarded and survived nowhere but the judge brief; the disagreement path now merges both models' findings, deduplicated by `_finding_key`, keeping the primary's copy of a corroborated finding and the judge escalation unchanged (#262)
- `agents/ensemble`: the same defect reported at two different call sites in one file collapsed into a single finding when the two ensemble models' results were merged, so the second site never reached the reviewer — the deduplication key was the path and the finding body only; the line is now part of a finding's identity, and a row with no line keys on a value no line number can collide with (#262)
- `agents/_stream_consumer`: streaming runs on OpenAI-shaped providers (Nous, MiniMax, opencode Responses / Chat Completions, Codex) over-reported their prompt size — and therefore the run's token and cost accounting — by the whole cached-prompt count whenever prompt caching was active, because `prompt_tokens_details.cached_tokens` / `input_tokens_details.cached_tokens` are already *inside* the reported `input_tokens` but were added to it a second time; `to_usage` now adds the cached count only when it came from Anthropic's disjoint `cache_read_input_tokens` counter, and still reports it as `cache_read_tokens` in both cases (#273)
- `agents/opencode`: reviews served over the opencode HTTP session path — every Nous and MiniMax run — over-reported their prompt size, and therefore the run's token and cost/budget accounting, by the whole cached-prompt count whenever prompt caching was active; this path re-implemented the cached-token scan inline and kept adding OpenAI-style `prompt_tokens_details.cached_tokens` / `input_tokens_details.cached_tokens` to an `input_tokens` that already contained them, so the fix landed in `_stream_consumer` only covered the streaming CLI drivers. It now shares `_resolve_cache_read`, adding the cached count only when it came from Anthropic's disjoint `cache_read_input_tokens` counter, and still reports it as `cache_read_tokens` in both cases (#273)
- `mcp/verdict`: a pull request carrying an analyzer-reported Critical or Major could be approved as long as the reviewing agent never dispatched a verifier for it — `validate_submission`'s approve branch only walked verifier-confirmed findings, so skipping verification was a route to approval. Approve is now rejected whenever any finding the run knows about is still of blocking severity after the causality policy has run, whether or not a verifier looked at it, and a finding the gate cannot grade blocks rather than being skipped. The reviewing agent reopens the approve path by verifying and then `drop`ping a refuted finding, or by `downgrade` to a non-blocking severity — both are applied before the gate reads the state, and a `drop` recorded in an earlier run counts too. Attribution is deliberately not a second condition: under the default `baseComparison: diff` no base run happens and every diff-scoped finding stays `introduced_by_pr: "unknown"`, so gating on `"true"` exempted ruff, mypy, bandit and semgrep from the gate entirely; where a base run did happen, a pre-existing finding is stamped `"false"` and the causality policy already downgrades it below the blocking threshold (#263)
- `mcp/verification`: a verifier `downgrade` that named no `new_severity` silently rewrote the finding to `Minor`, so a single such verdict retired any Critical the approve gate was holding; a downgrade is now rejected unless it names the severity it downgrades to, that severity must be one of the four in the taxonomy, and a downgrade landing on a still-blocking severity needs the same structured causality a `confirm` does (#263)
- `mcp/check_runs`: the `list_check_runs` tool called GitHub's check-*suites* endpoint and returned a `check_suites` payload, so a reviewing agent that asked which checks ran on a ref got only per-suite rollups — the individual run names, their per-run conclusions, and therefore the logs of the one job that actually failed were unreachable through this tool; it now calls `list_check_runs_for_ref` and returns `check_runs`, and every returned run carries its parent suite's id as a top-level `check_suite_id` beside its own `id`, so the documented `get_check_suite_logs` follow-up can be handed a suite id without the agent having to pick between two nested ids. `GitHubScmAdapter.list_check_runs`, the protocol's MCP-read operation of the same name, forwarded to the suites endpoint too and is corrected with it (#266)
- `mcp/server`: a malformed `tools/call` from the reviewing agent — a missing required argument, an unreadable one, or a property the tool never declared — reached the tool body and failed in whatever ad-hoc way that tool happened to fail, or partially succeeded, instead of being rejected at the protocol boundary; `handle_rpc` now validates `arguments` against the tool's `input_schema` before dispatch and returns JSON-RPC `-32602` with the offending JSON path and the validator's message. A string-encoded scalar sent where the schema declares `integer`, `number` or `boolean` — `"1"`, `"true"` — is read as that type and passed through rather than rejected: roughly 37 tool bodies were written for exactly that tolerance and the packaged workflow itself asks the agent for a bare `check_suite_id`, so rejecting it turned a tolerated shape into a hard error and silently degraded CI-log grounding. A union that already admits `string` is left alone, and a value that cannot be read as its declared type is still reported as the schema violation it is. `inf` / `nan` spellings such as `"1e999"` are refused rather than coerced — they satisfy the schema and then raise inside the tool body — and only `true`/`false`/`1`/`0` read as booleans, since no JSON consumer recognises `yes`/`no`. A tool whose declared schema cannot be compiled fails closed as `-32603` naming that tool, rather than running unvalidated arguments — reachable in production because `set_output` adopts a consumer-supplied `output_schema` verbatim and only its JSON-object-ness was ever checked. A non-dict `arguments` is still coerced to `{}` and is now rejected by any tool that requires a property, where it previously executed with no arguments. A call rejected here is charged no tool-call budget, so a schema mismatch the agent retries cannot burn the run budget with nothing executed, and the rejection is recorded on the trajectory instead of being invisible (#267)
- `mcp/server`: a `tools/call` carrying a very long integer literal where the schema declares `number` — anything past the float range, from 309 digits up — returned HTTP 500 with no JSON-RPC envelope and no request `id`, which is the response shape Codex's MCP client cannot deserialize and answers by killing its transport worker. The non-finite guard added for the `inf`/`nan` spellings asked `math.isfinite` about a Python `int`, which converts to float first and raises `OverflowError`, and argument coercion runs before the handler's error boundary, so nothing caught it. Only a float can be non-finite, so the guard now says so; a wide integer is passed through typed as any other number is. Reachable on every top-level `number` property, including `shell.timeout`, `git_fetch.depth` and the `check_suite_id` the packaged workflow asks the agent to pass to `get_check_suite_logs` as a bare number (#267)
- `mcp/verdict`: a malformed finding the reviewing agent asserted could silently neutralise a real analyzer blocker that shared its fingerprint — the grader marked the fingerprint as already graded before discovering the row was unreadable, so the analyzer row carrying it was skipped and landed in neither the unverified nor the ungradable population, leaving the approve gate with nothing to block on. A row that cannot be read no longer spends its fingerprint (#263)
- `mcp/shell`: the shell tool's git refusal missed `sudo -u <user> git …` and `doas -g <group> git …` — the target name is neither path-shaped nor numeric, so it read as the command word and ended the scan before the git behind it was inspected, putting the whole git surface (`git clean`, `filter-branch`, `-c alias.…`) back within reach of a `restricted` shell. A wrapper flag's separate name operand is now skipped rather than treated as the command (#257)
- `wait-for-ci` job now declares a job-level `permissions: {contents: read, checks: read}` block so its `gh api …/check-runs` poll is no longer silently 403'd; stderr from the poll is no longer suppressed so permission failures are visible in the job log (#264)
- `action.yml` outputs (`result`, `evidence_packet`, `verdict_diagnostic`) no longer carry `value: steps.run.outputs.*` composite-action wiring — those expressions are inert on a Docker action and prevented consumers from ever reading the outputs; outputs are now written exclusively via `$GITHUB_OUTPUT` (#272)
- `verdict_diagnostic` output is now written to `$GITHUB_OUTPUT` on every run — the declared output was computed but never emitted, leaving the key permanently absent for consumers; an empty string is written when no terminal-verdict policy was evaluated (#265)
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
- Fixed the empty-diff early return in `run_offline_diff_review` silently reporting `RunOutcome.passed` when `apply_diff_line_budget` fully truncated (or untrusted-path filtering emptied) the diff; the run now applies the scope-reduction downgrade and reports `inconclusive` (#242 / `mergecraft-finding:v1:2e1cb9c2153087658c3481bd`)
- Fixed `mergecraft review` default text mode never producing exit codes 10/11 — the CLI now requests structured findings internally so a CI script running `review` can block on the documented exit-code contract (#242 / `mergecraft-finding:v1:7a3cdf5ef1994610113e8e37`)
- Fixed `mergecraft plan` reporting `diff_path` that pointed at a path inside a torn-down `TemporaryDirectory`; the materialized diff is now persisted to `<repo>/.mergecraft/plan-review.diff` so the report's `diff_path` is reachable after return (#242 / `mergecraft-finding:v1:e8bc195570ae6f1cc8ab5bc6`)
- Fixed tool-call budget exhaustion only surfacing as a JSON-RPC error to the agent — `BudgetTracker` now records the `BudgetExhausted` it raises (`last_exhausted`) and `main._finalize` drains the tracker at finalize time, so a run that exhausts its tool-call budget is tagged `inconclusive` rather than approving on a partial signal (#242 / `mergecraft-finding:v1:aeb5d964c1d35e5a41784ded`)
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

### Security

- Mutating MCP tools other than review-session verbs (`select_mode`, checkout, review publication) are refused unless a write-capable mode is selected, including before mode selection (#350)
- GitLab webhook `X-Gitlab-Token` is compared as a shared secret, not an HMAC of the body (#361)
- External URL retrieval also blocks decimal, hex, and short IPv4 forms, IPv6-mapped loopback, and DNS that resolves to loopback, link-local, or metadata; DNS failure is fail-closed (#362)
- Dependency and container-image vulnerability gates no longer report a pass without running a scanner (#362)
- Network egress is allow-listed (`allow_egress`), external retrieval refuses SSRF targets (loopback, link-local metadata, `file:`), dependency and container-image vulnerability gates are invocable and the image gate is not `make security`, public comments redact secret tokens, and `docs/THREAT-MODEL.md` ties those controls to `tests/security/test_cd_egress.py` plus an independent security review before a stable release (#362)
- GitHub webhooks are authenticated with a matching HMAC and GitLab with a shared-secret `X-Gitlab-Token`; a provider 429 surfaces as retryable instead of dropping the event, and webhook adapters still cannot commit, push, or edit (#361)
- `SECURITY.md` states the review-only guarantee: identify, investigate, verify, explain, prioritize, and suggest; no source edits, applied fixes, commits, pushes, or code-changing pull requests (#350)
- Review runs are review-only: `Fix`, `Build`, `Task`, `AddressReviews`, and `ResolveConflicts` are no longer selectable, and a Review or IncrementalReview run cannot edit the workspace, commit, push, or open a code-changing PR. Illustrative diffs stay GitHub suggestion comments (#350)
- `mergecraft mcp serve` now mints a per-serve Bearer token and requires it on every MCP request; unauthenticated `tools/list` and `tools/call` are rejected with HTTP 401 / JSON-RPC `-32600` (#345). `build_mcp_tool_context` mints the token via `secrets.token_hex(32)`, stores it as `ctx.mcp_auth_token`, and passes it as `auth_token=` into `create_mcp_app`; the token is printed to stderr as `MERGECRAFT_MCP_BEARER=<token>` at startup.
- `mcp/server`: primary `/mcp/reviewer` now admits session tools `set_output`, `select_mode`, and `report_progress` via `PRIMARY_MUTATING_ALLOWLIST`; routing the primary agent to `/mcp/reviewer` no longer drops tools required by the Action output schema, the mode-selection playbook (Step 1), and the no-action path. Repo mutations (`push_branch`, `commit_changes`, etc.) and review-write tools not in the allowlist (`resolve_review_thread`) stay off the reviewer surface; subagents continue to use the narrower `READONLY_MUTATING_ALLOWLIST`
- docs: `SECURITY.md` secret-stripping claim narrowed to the agent subprocess (`build_agent_env` / `filter_env`) and the sandboxed `shell` tool (`resolve_env`); `_run_git` inherits the process environment and is not covered by the filter (#286)
- Untrusted PR trees no longer receive a `shell` tool when PID-namespace isolation is unavailable (#287)
- Untrusted PR trees no longer run package install lifecycle scripts in the Action process when `shell` is the default `restricted` (#284)
- `mcp/git`: replaced permissive `_SUBCOMMAND_RE` with an explicit read-only allowlist (`status`, `log`, `diff`, `show`, `rev-parse`, `describe`, `ls-files`, `blame`, `cat-file`, `rev-list`, read-only `branch`); `git reset`, `git clean`, `git stash`, and all other mutating subcommands now raise `ValueError` unconditionally (#257)
- `mcp/git`: `-c` / `--config-env` are now rejected unconditionally regardless of `payload.shell`, closing the `git -c alias.x='!cmd'` arbitrary-shell-execution vector that bypassed the former `shell: disabled` guard (#257)
- `mcp/git`: the glued single-token spelling (`-ckey=value`) is refused alongside the spaced and inline forms, so the alias-execution block no longer depends on how the flag was written. The `-c`-shaped token is read against the short flags the subcommand defines before it is judged, which keeps `ls-files -co` and `log -c` working — a glued config payload cannot pass that test, because a key name, a `.` and an `=` are not short-flag letters (#257)
- `mcp/git`: `git branch` write forms reached refs through a tool declared repository-*read* — only `-d` / `-D` / `-m` were blocked, leaving `--delete`, `--move`, `-M`, `--copy` and bare `git branch <name>` creation to succeed. Listing flags are now an allowlist rather than a list of remembered write spellings, bundled and repeated short flags are checked letter by letter so one write letter refuses the whole token, and a rename of the checked-out branch can no longer change what a later `commit_changes` or `push_branch` targets (#257)
- `mcp/git`: `git diff --output=<path>` wrote an arbitrary file through a read-only tool — the subcommand allowlist constrains the verb, not the flags the verb accepts. `--output` and every unambiguous prefix git also honours (`--out`, `--outp`, …) are refused on every allowlisted subcommand, and `-o` is refused on the subcommands that do not define it themselves (#257)
- `mcp/shell`: a `git` invocation on its own line was never inspected, because the guard's separator class omitted the newline while `bash -c` runs every line of its argument — so `git -c alias.z='!sh …'` reached the shell and bypassed the git tool's alias block along with the `clean` and `filter-branch` verbs that tool refuses by name. Every command position in the command string is now scanned, across newlines, command substitution and backticks; git is matched by path basename so `/usr/bin/git` and the alias-suppressing `\git` are seen; and leading environment assignments, a wrapper's own numeric or path argument, and wrapper commands (`env`, `xargs`, `timeout`, `sudo`, `flock`, `script`, nested `sh -c`, and others) are looked past. `grep git README` and `ls.git` still run. This stays defence in depth behind the git tools' own allowlist, not a shell parser — arbitrarily quoted payloads, variable indirection and `printf … | sh` remain out of reach of any token scan (#257)
- `mcp/git`: `-C`, `--git-dir`, and `--work-tree` are now confined to the resolved primary repo root; any path outside raises `ValueError` with the offending path in the message (#257)
- `mcp/upload`: `upload_file` now rejects symlinks and confines the requested path to the primary repo root or the session `tmpdir`; no `file://` URI is emitted for a path that fails confinement (#258)
- `mcp/labels`: label names are now percent-encoded (`urllib.parse.quote(label, safe="")`) before interpolation into the `DELETE /labels/{label}` path segment, preventing `/` or `..` in a label name from shifting the URL path (#260)
- `cli/auth`: credentials written by `mergecraft auth` inherited the umask, so a `.env` started from the documented `cp.env.example.env` stayed readable by every user on the machine while holding Codex OAuth JSON, Claude tokens and up to five provider API keys — the first path writing any of them outside a temporary directory. The file is narrowed to `0600` *before* the credential is written as well as after, so there is no window in which the secret sits in a world-readable file. A `chmod` that fails warns rather than refusing the write (#221)
- Linked-repo reads are grant-gated: a run can only load repos declared in its authorized set; linked-repo and ticket text render through the fence as untrusted data
- Discovered repo instruction and skill files (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `.cursor/rules/*.md`) from an untrusted review source render through the fence as evidence and never enter the instruction bundle
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
- Primary reviewer surface (`/mcp/reviewer`) now includes `create_pull_request_review` (`ToolClass.REVIEW_WRITE`) via `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES` and `PRIMARY_MUTATING_ALLOWLIST`; subagents retain the narrower `REVIEWER_ALLOWED_TOOL_CLASSES` complement so they remain denied review publication (, #282)
- MCP HTTP server now issues a per-run secret at startup (`ToolContext.mcp_auth_token`); `tools/list` and `tools/call` reject unauthenticated requests with HTTP 401 / JSON-RPC `-32600`; the bearer token is wired into the harness MCP `headers` config for Claude, Gemini, OpenCode, and Cursor; Codex receives the token via `MERGECRAFT_MCP_TOKEN` and presents it through the documented `bearer_token_env_var` config key (/, #283)
- Port allocator replaced: `_select_port` now uses `bind((MCP_HOST, 0))` to let the OS pick an ephemeral port instead of scanning a fixed 50-wide band from 3764; `MERGECRAFT_MCP_PORT` override is preserved; `mergecraft doctor` reports "ephemeral port" instead of a fixed number (#283)
- `AgentRegistry.resolve_tool_names` and `_default_tool_classes` now align with `build_reviewer_tools`: reviewer binding uses `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES` and `PRIMARY_MUTATING_ALLOWLIST`, so `create_pull_request_review` is correctly included in the registry-derived surface (, #282)
- `offline_review` now routes agents to `MCP_REVIEWER_ENDPOINT` (`/mcp/reviewer`) rather than the orchestrator `/mcp`; terminal-protocol and orchestrator-only tools are no longer reachable from offline CLI reviews (#282)
- The self-review fallback decision scripts run from a copy staged in the runner home before the first Action step mounts the workspace, re-verified against a recorded content hash, so a pull request that edits those scripts can no longer run its own version with the review job's token
- Approval enforcement now takes the verdict from the review run's own evidence-packet output and requires a `mergecraft-approval` check issued by `github-actions` (or the configured App), on the reviewed head, carrying this run's `<run id>:<attempt>` id and agreeing with that verdict; an unattributable, absent, or disagreeing check fails closed, so a foreign check can neither pass a gate nor mask a genuine verdict
- The `mergecraft init` scaffold requests `contents: read`, disables checkout credential persistence, and pins every action to a full commit sha; the shipped examples and the README example pin the same way
- The changelog-preview workflow passes no repository secrets to the third-party reusable workflow it calls

### Removed

- The unused `get-installation-token/main.py` script; the `get-installation-token` composite Action is unchanged

### Fixed

- Comment-triggered reviews now resolve the pull request they will check out
 before any trust, credential, or sandbox decision, so a maintainer's review
 command on a fork pull request no longer runs with provider credentials or a
 trusted sandbox; a pull request whose metadata cannot be fetched fails closed
 with a message naming the unbound pull request. A `workflow_dispatch` review
 that names a pull request is bound the same way, reading the composed review
 prompt rather than only the operator's raw input.
- The checkout tool refuses a pull request number other than the one the run was
 bound to, and refuses a fork pull request on a run trusted for execution or
 authority.
- A checkout that falls back to the files API after a failed `git diff` now
 records itself as a files-API diff with the reason instead of registering as a
 full checkout; text patches GitHub omits from the files API are listed as
 unreviewable, a page-cap truncation is recorded, and binary files are not
 flagged.
- The incremental checkpoint and review-round index accept a mergeCraft marker
 only from the run's own expected publishers — an App bot login
 (`<slug>[bot]`) or the `GET /user` login of a non-shared publication token —
 and read paginated review history, so a marked review by any other author no
 longer moves the checkpoint. A run that can only publish as the shared
 `github-actions[bot]` has no attributable identity, so incremental checkpoints
 and round counting stay unavailable until the reviewer App or a PAT is
 configured.
- Repository instruction files are discovered and read only when their resolved
 path stays inside the repository, so a symlinked `AGENTS.md` or a symlinked
 directory pointing outside the checkout is skipped and recorded as a refusal.
- The `MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS` environment switch is removed;
 the security paragraph is always in the system prompt.
- Inside GitHub Actions the CLI no longer loads a `.env` from the checked-out
 workspace at startup; set `MERGECRAFT_ENV` to load an explicit file. Local
 (non-Actions) runs are unchanged.
- Linked-repo grants now match an exact lowercase `owner/name`; a bare name no
 longer authorizes a same-named repository, and two manifest entries sharing a
 name are both refused.
- Linked-repo findings report only contracts changed by a moved pin, and every
 omission — ungranted, missing sibling, pin mismatch, unreachable pin, an
 unreadable base manifest, or a manifest whose entries share a name — is listed
 in the review payload.
- A fallback review rung reports only the model it actually ran: it no longer
 names the primary provider's reviewer slot as a skipped credential when the
 fallback carries its own provider's credentials.
- Harbor's agent wrapper invokes `mergecraft review` instead of the deprecated
 `diff-review` alias.
- The sandbox write/network test and the symlink-target chown test run in the
 privileged lanes built for them, and fail rather than skip inside those lanes
- The keyless provider-catalog smoke no longer hides behind a live gate and runs
 in the unit suite
- Both in-image test scripts pin the same `pytest` and `pytest-asyncio` as the
 project they test

### Security

- A single log patcher now both redacts secrets and carries the bound run
 context, so every entrypoint — the Action, `mergecraft review` /
 `diff-review` (including Harbor), and `mcp serve` — logs records that are
 redacted **and** attributable to their run, repository, pull request and
 phase. Previously the two patchers replaced each other, leaving the Action
 redacted but uncorrelated and every other entrypoint correlated but not
 redacted.
- Git subprocesses no longer inherit environment-injected git configuration or
 credential redirection: ambient `GIT_CONFIG_*` pairs, the config-source
 selectors (`GIT_CONFIG`, `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`), git trace
 variables (`GIT_TRACE*`, `GIT_CURL_VERBOSE`), and askpass / ssh / proxy /
 exec-path overrides are dropped before the subprocess environment is built, so
 an ambient `credential.helper`, trace target, or substituted config file
 cannot capture the brokered credential. The operator's own default
 `~/.gitconfig` and system configuration are still honoured.
- GitHub Actions and runner metadata reach child processes by explicit
 documented name rather than by prefix, so lookalike credential variables such
 as `GITHUB_PAT` or `RUNNER_BLOB` no longer pass into agents, the restricted
 shell, or analyzers. The Actions command-file channels (`GITHUB_ENV`,
 `GITHUB_PATH`, `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`) are excluded from the
 child environment: they are writable control channels for later steps and for
 this action's outputs, not child metadata. `envAllowlist` remains the explicit
 escape hatch.
- Cleanup and token-revocation failures are logged as warnings naming the step
 and path — including a residual askpass file — instead of being suppressed.
 Cleanup stays best-effort: no failure changes the run outcome.

### Changed

- The PR integration job runs keyless hermetic integration tests instead of
 passing on a check that a helper script exists, so a green run means tests
 executed
- Nightly live-provider coverage lists only the providers this repository holds
 credentials for; the removed legs are named as not exercised instead of
 failing on secrets the repository is not configured to hold
- An E2E live slice with no model configured reports `unavailable` in a warning
 and the step summary instead of a green `skipped`; a configured-but-broken
 slice still fails
- Live-provider tests report the HTTP status before parsing a response body, and
 never echo the credential or the request URL; the Nous leg posts the
 documented default model
- CodeQL results upload to code scanning on the events whose token can write
 `security-events`, and an analysis failure fails the job; fork and Dependabot
 pull requests analyse without uploading
- `make workflow-lint` no longer reports success on a host where it could not
 lint: it fails and says lint is unavailable
- `make docker-build` tags the image with a lowercase repository name, so the
 target can succeed
- Every runtime dependency is an exact pin, every third-party import in the
 package is declared, and the declarations nothing imports are gone

### Added

- Published Python distributions are installed outside the checkout and carry
 build provenance before upload
- `pre-commit` blocks newly added large files and private keys, and scans staged
 changes for secrets with `gitleaks`
- `make test-durations` refreshes the committed `.test_durations` that
 least-duration sharding balances by
