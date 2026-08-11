# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

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

### Added

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

### Changed

- Docker Action images pin base layers, `uv`, Node, `gh`, and agent CLIs by
  digest or lockfile so rebuilds are reproducible and Dependabot can bump
  every pinned artifact
- Security and runtime config models (`RepoSettings`, `GatesSettings`,
  `AnalyzersSettings`, `TracingSettings`) now reject unknown keys
  (`extra="forbid"`) instead of silently ignoring typos
- Unparseable Action `timeout` input fails closed as `configuration_error`
  (keep `--notimeout` to disable); dependency-install failure maps the run to
  `inconclusive` rather than a silent continue
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
- Initial mergeCraft snapshot from pullfrog-py (history-free rebrand).
