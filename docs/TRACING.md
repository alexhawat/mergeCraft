# Tracing — configuration, sinks, redaction, retention

> Status: **complete**. Batch A (W2) covers the config schema, canonical span
> model, local JSONL sink, and redaction boundary; Batch B (W4) wires the
> production span tree; Batch C (W6) ships the `stream-json` migration
> for per-tool / per-LLM spans; Batch D (W8) ships remote exporters, the
> optional extra, CLI / `action.yml` inputs, and complete documentation.
> Reference issue: [#56][i56].

[i56]: https://github.com/alexhawat/mergeCraft/issues/56

## Why a tracing block

mergeCraft runs are short-lived and an exhausted runner leaves nothing
behind. When a review is slow, wrong, or expensive, there is no record of
which model served it, which tools the agent called, or what was passed in.
This block writes a per-run span tree to local files (and, behind the
optional `tracing` extra, to remote exporters) so an operator can answer
"why was this blocked?".

A repo that does not declare a `tracing:` block sees identical behaviour,
identical performance, and zero egress — the default is off, and the
disabled path is a true no-op (no directory is created).

## Quick start: enable Logfire tracing

The shortest path from a fresh checkout to spans landing in Logfire:

```bash
# 1. install the optional extra (one time)
uv sync --extra tracing

# 2. run the auth command (validates the token, writes .env + gh secret)
mergecraft auth logfire

# 3. verify wiring (token is redacted in the table)
mergecraft config tracing

# 4. ship a trace
mergecraft review --tracing --tracing-to logfire
```

`mergecraft auth logfire` accepts `--scope local|github|both` (default
`both`). `local` writes `MERGECRAFT_LOGFIRE_TOKEN` + `MERGECRAFT_TRACING_PROJECT`
into `.env`; `github` calls `gh secret set LOGFIRE_TOKEN` on the origin
repo; `both` does both. The validator probes
`GET https://logfire.pydantic.dev/api/v1/projects` (parity with the other
`auth` providers) and rejects the token on `401`/`403` before any state
changes. The `[tracing]` extra must be installed for spans to actually leave
the runner — the command prints a warning when the extra is missing but does
not auto-install (BYOK, convention 5).

For the GitHub Action, the workflow step should pass
`tracing-to: logfire` + `logfire-token: ${{ secrets.LOGFIRE_TOKEN }}` (the
`LOGFIRE_TOKEN` secret is the same value `auth logfire --scope github`
sets). The Action input `logfire-token` maps to the runtime
`MERGECRAFT_LOGFIRE_TOKEN` env var; the project label is read from
`MERGECRAFT_TRACING_PROJECT` or the YAML `tracing.sinks[].project` field.

Rather than editing the workflow by hand, let the CLI write it:

```bash
mergecraft tracing logfire wire-workflow --step all --region eu   # dry-run diff
mergecraft tracing logfire wire-workflow --step all --region eu --apply
```

This inserts `tracing: "true"`, `tracing-to: logfire`, and
`logfire-token: ${{ secrets.LOGFIRE_TOKEN }}` into the step's `with:`, plus
`MERGECRAFT_TRACING_PROJECT` (and, with `--region`, `MERGECRAFT_TRACING_REGION`)
into its `env:`. `unwire-workflow` strips all of them.

### Data region

Logfire serves region-specific OTLP ingest hosts — `logfire-us.pydantic.dev`
and `logfire-eu.pydantic.dev` — and the resolver **defaults to `us`**. A write
token is regional: `pylf_v{N}_eu_…` belongs to the EU project and its spans are
rejected by the US host. Set the region explicitly whenever the token is not a
US one:

| Surface | How |
| ------- | --- |
| Local   | `mergecraft tracing logfire enable --region eu` (writes `MERGECRAFT_TRACING_REGION` to `.env`) |
| Action  | `mergecraft tracing logfire wire-workflow --region eu --apply` (writes it to the step's `env:`) |

Both paths converge on the same precedence layer
(`cli/tracing_precedence.py`) and the same resolver
(`tracing/resolve.py`), so the local `.env` shape and the workflow `env:`
shape carry identical meaning.

### The `[tracing]` extra in the Action image

The Action runs the digest-pinned `ghcr.io/alexhawat/mergecraft` slim image published by
`ci-cd.yml`. The image installs
`uv sync --frozen --no-dev --extra tracing`. Without that extra the sink
factory degrades a `logfire` / `otel` sink to `NullSink` with a warning
(`src/mergecraft/tracing/sinks.py`) — the workflow looks correctly wired and
exports nothing. If you fork the image build, keep the extra.

## Config schema

```yaml
tracing:
  enabled: true                # default: unset (treated as off); bool | null
  retentionDays: 30            # default: 30
  redaction: true              # default: true
  content: redacted            # default: redacted; off | metadata | redacted | full (OB2/D6)
  sinks:
    - type: jsonl_file
      path: .mergecraft/traces/
    # Batch D adds: logfire, otel (behind the [tracing] extra, D6).
```

`enabled` is tri-state: `true`, `false`, or unset (`null`). Unset defers to
the next precedence layer and is **not** the same as `false`. On the Action
path the precedence is: `tracing` / `INPUT_TRACING` action input >
`MERGECRAFT_TRACING` env > YAML `tracing.enabled` > default (unset → tracer
off). See `src/mergecraft/action/inputs.py::apply_tracing_overrides`.

### Shorthand form

The shorthand `to: local_files` is normalised into the canonical `sinks`
list at parse time (D9) — exactly one shape exists downstream:

```yaml
tracing:
  enabled: true
  to: local_files              # expands to [{type: jsonl_file, path: .mergecraft/traces/}]
```

### Sink entry fields

| Field         | Type                | Notes                                           |
| ------------- | ------------------- | ----------------------------------------------- |
| `type`        | string (required)   | One of `jsonl_file`, `memory`, `logfire`, `otel`. |
| `path`        | string              | Directory for `jsonl_file` (default `.mergecraft/traces/`). |
| `tokenRef`    | string              | Reference to a secret (Batch D resolves the value). |
| `project`     | string              | Project / namespace for `logfire`.              |
| `endpoint`    | string              | OTLP / collector endpoint.                      |
| `headers`     | map[string]string   | Optional headers for OTLP / collectors.         |

`tokenRef` is never inlined (D5). `path` is repo-relative when the sink
operates inside the Action container.

## Sink types

| Type         | Implementation           | Status         |
| ------------ | ------------------------ | -------------- |
| `jsonl_file` | `JSONLFileSink`          | Batch A (W2)   |
| `memory`     | `MemorySink`             | Batch A (W2)   |
| `logfire`    | OTLP exporter (one path) | Batch D (W8)   |
| `otel`       | OTLP exporter (one path) | Batch D (W8)   |
| `sqlite`     | deferred (D10)           | not scheduled  |

### `jsonl_file` — daily rotation, 30-day retention

One JSONL file per UTC day, named `YYYY-MM-DD.jsonl`, written under the
configured `path`. Default retention is 30 days; `purge_expired()` removes
files whose mtime is older than the cap.

### `memory` — in-process only

Records every event in a `list`; available for tests and short-lived
fixtures. Nothing escapes the process.

### `logfire` / `otel` — one path (D5)

Both resolve to the same OTLP exporter behind a batch processor. The
remote sink contract is owned by W8.

## Redaction guarantee (D7)

Redaction runs **once**, **before** fan-out. Every event reaches every
sink through a `RedactingSink` wrapper around `MultiSink` — no sink is
ever reachable without going through the redaction boundary.

- The implementation **reuses** `src/mergecraft/utils/secrets.py`
  (`filter_env`, `is_sensitive_env_name`) and
  `src/mergecraft/analyzers/redact.py` (`redact_secrets`). No second
  matcher is implemented.
- A deny-key list (`authorization`, `cookie`, `api_key`, `secret`,
  `password`, `access_token`, `refresh_token`, `id_token`, `bearer_token`,
  `auth_token`) — case-insensitive — replaces matching attribute values
  with `[REDACTED]`.
- The shared helper applies to every string attribute value (recursively
  into nested dicts and lists) so `ghp_…` and `sk-…` substrings cannot
  escape.

## Payload cap (D8)

`TRACE_ATTRS_JSON_MAX_BYTES = 64 * 1024`. When any single string value in
an event's `attrs` exceeds the cap, the row is written with
`attrs = {"truncated": True}` instead. The row survives on disk and
downstream consumers see the marker rather than a missing or half-written
record.

## Retention (D8)

`retentionDays` (default `30`) governs `JSONLFileSink.purge_expired()`. Files
whose mtime is older than the cap are removed on the next write (or
explicit purge).

## Limits

Two independent caps bound how much a single run can emit — both are guards
against a runaway, not budgets to plan around, and neither fails the run
when hit (convention 6).

| Cap | Constant | Value | Behaviour past the cap |
|---|---|---|---|
| Per-event `attrs` size | `TRACE_ATTRS_JSON_MAX_BYTES` (`src/mergecraft/tracing/cap.py:18`) | 64 KiB | `cap_event_attrs()` replaces `attrs` with `{"truncated": True}`; the row still lands. |
| Span count per run | `MAX_SPANS_PER_RUN` (`src/mergecraft/tracing/tracer.py`) | 10,000 | `Tracer.start_span()` keeps returning a span (so callers don't need to special-case it), but the span is suppressed — it never reaches the configured sink. Logged once at `warning` with the count on the first span past the cap, not once per subsequent call. |

10,000 is roughly 20x the realistic ceiling for a large review (one
`analyzer.run` per analyzer, one `tool.call` per tool invocation, one
`llm.call` + `provider.call` per turn), so it only fires on a genuine
runaway — a large PR review should never come close. If a legitimate run
does hit it, raise the `Final` constant; it is a single line to change.

## Behaviour guarantees

1. **Disabled is a no-op** (convention 9). A repo that does not enable
   tracing never touches the filesystem; the `attrs_source` callable on
   a `NullSink.emit` is never invoked.
2. **Tracing never fails the run** (convention 6). A sink that raises on
   `write` is caught and logged at `logger.warning`; the run continues.
3. **Optional extra** (D6). `logfire` and `opentelemetry-*` are not base
   dependencies. `pip install merge-craft[tracing]` pulls them in;
   `make ci-resume` passes with them uninstalled (convention 5).
4. **No network in `make ci-resume`** (convention 8). Exporter tests
   target a fake transport.

## D15 — remote sinks export reviewed-repo content

> Enabling a **remote** sink (`logfire`, `otel`) exports reviewed-repo
> content — the prompts the reviewer received, the tool inputs and
> outputs it produced, and the model's reasoning — to the configured
> endpoint, using the operator's token or API key. **BYOK** means the
> operator owns both the credential and the responsibility for what
> leaves the runner. Scope workflows at the GitHub Actions level
> (`if: github.event.pull_request.head.repo.fork == false`) when the
> reviewer should not exfiltrate fork-PR content.

There is no config-level trust gate. D15's hard requirement is that the
statement above appears plainly in this document, so the operator sees
it the first time they reach for a remote sink.

## Content-capture policy for model payloads (OB2 — D6/D7/D8)

D15 warns that remote sinks export reviewed-repo content; the `content`
policy is the **level control** that decides how much of it leaves the
runner. It governs model payloads (prompts, completions, reasoning) via
`tracing/content.py`, with four levels (D6):

| Level | Body | Metadata (`.chars` / `.bytes` / `.sha256`) | Use |
| --- | --- | --- | --- |
| `off` | — | — | Nothing is captured, hash included |
| `metadata` | — | ✓ | Counts + hash only — the untrusted-tier ceiling |
| `redacted` (default) | ✓, through the secret matcher (`analyzers.redact.redact_secrets`), capped | ✓ | Safe default |
| `full` | ✓, verbatim, capped only | ✓ | Local debugging |

Resolution (`resolve_content_capture(configured, trust_tier)`):
`MERGECRAFT_TRACING_CONTENT` env → the YAML `tracing.content` field → the
default `redacted`. An unrecognised value at any step falls through to the
next, ending at the default — fail safe, never `full`. Bodies are
byte-capped at the shared `TRACE_ATTRS_JSON_MAX_BYTES` budget and flagged
`.truncated`; `.chars` / `.bytes` / `.sha256` always describe the
**original** payload (D8), so the hash detects prompt drift between two
runs even when neither shipped a body.

**D7 — the untrusted cap cannot be configured away.** At any trust tier
other than `trusted`, a body-emitting level is lowered to `metadata`
**after** precedence resolution: `content: full` in YAML and
`MERGECRAFT_TRACING_CONTENT=full` both yield `metadata` on a fork-PR-shaped
run. The cap only ever lowers a level — `off` stays `off`, and nothing is
ever raised. Shipping a fork PR's prompt bodies to a remote sink is
exactly the exfiltration path trust tiers exist to close.

## Span tree (W4 — Batch B)

Every tracing-enabled run emits one **root span** (`mergecraft.run`) with
the run lifecycle, and a fixed set of **child spans** at the existing
seams. Spans carry `parent_span_id` pointers so the tree is reconstructible
from any sink's flat event stream. The root is the only span whose
`parent_span_id` is `None` — convention 9.

```text
mergecraft.run                       (root; run_id, repo, pr_number,
                                       commit_sha, workflow_run_id, job_id)
├── mergecraft.prep                  (toolchain install: language servers,
│                                       linters, action deps)
├── mergecraft.analyzers.pipeline    (W7: detect, run, scope, cluster,
│    │                                  budget — analyzer fan-out)
│    └── analyzer.run  ×N            (analyzer.id, exit_code,
│                                       findings_count, duration_ms,
│                                       skipped, error)
├── agent.attempt  ×N                (per fallback entry; model.id,
│    │                                  agent.provider, agent.mode,
│    │                                  agent.cli_argv — redacted,
│    │                                  model.fallback_index, status,
│    │                                  error)
│    └── llm.call                    (cost.tokens_in, cost.tokens_out,
│                                       cost.cache_read, cost.cache_write,
│                                       cost.usd)
├── tool.call  ×N                    (tool.name, tool.server)
└── mergecraft.publish               (finalisation: persist learnings,
                                        report status checks, emit packet)
```

### Attributes per kind

| Kind                          | Required attributes (issue §4 + W4.4)                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| `mergecraft.run`              | `run_id`, `repo`, `pr_number`, `commit_sha`, `workflow_run_id`, `job_id` (correlation from env or kwarg) |
| `mergecraft.prep`             | (no required attrs beyond span defaults)                                                              |
| `mergecraft.analyzers.pipeline` | (no required attrs beyond span defaults)                                                             |
| `analyzer.run`                | `analyzer.id`, `analyzer.exit_code`, `analyzer.findings_count`, `analyzer.duration_ms`                |
| `agent.attempt`               | `model.id`, `agent.provider`, `agent.mode`, `agent.cli_argv` (redacted), `model.fallback_index`, `status` |
| `llm.call`                    | `cost.tokens_in`, `cost.tokens_out`, `cost.cache_read`, `cost.cache_write`, `cost.usd`                 |
| `tool.call`                   | `tool.name`, `tool.server`                                                                            |
| `mergecraft.publish`          | (no required attrs beyond span defaults)                                                              |

### Defaults and guarantees

- The default is **off** (convention 9). When `tracing.enabled` is `false`,
  `get_tracer_from_settings` returns a `NullTracer` whose `start_span`
  returns a `NullSpan` that short-circuits every emit — no sink is touched,
  no `attrs_source` callable is invoked, no directory is created.
- The tracer is **never on the critical path** (convention 6). Any
  exception inside an emit site is caught by `MultiSink.write` and logged
  at `logger.warning` with the sink type and message; the run continues.
- **Redaction runs once, before fan-out** (D7). Every emit traverses a
  `RedactingSink` wrapper around `MultiSink`. The `MemorySink` that
  structural tests use also redacts on write, so test assertions and the
  production path see the same surface.
- **Correlation fields** are read from the `correlation` kwarg at the
  emit site if provided; otherwise they are derived from `GITHUB_*` env
  vars (`GITHUB_RUN_ID`, `GITHUB_REPOSITORY`, `GITHUB_PR_NUMBER`,
  `GITHUB_SHA`, `GITHUB_JOB`). Local dev runs that lack those vars get
  safe placeholders rather than `None`.

## Per-driver streaming coverage (W6 — Batch C)

The W6 read-loop migration replaces `subprocess.run(..., capture_output=True)`
with `subprocess.Popen` + a line-buffered `consume_stream` consumer that
emits a `tool.call` or `llm.call` span per event. The exact span surface
depends on what the upstream CLI emits; this table pins the version the
plan was authored against and the per-event coverage each driver
delivers today.

| Driver   | CLI version pinned (W0.5) | Streaming flag                                | Coverage                                                                                  |
| -------- | ------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `claude` | Claude Code 2.1.226       | `--print --output-format stream-json`         | **Per-event**: one `llm.call` per `message_start`/`message_stop`; one `tool.call` per `content_block_start`/`stop`. Authoritative usage from the final `result` event. |
| `codex`  | codex-cli 0.146.0         | `codex exec --json`                           | **Per-event**: one `llm.call` per `thread.started`; one `tool.call` per `item.started`/`item.completed`. Authoritative usage from the `turn.completed` event. |
| `gemini` | gemini-cli 0.53.0         | `-p <prompt> --output-format stream-json`     | **Per-event**: one `llm.call` per `init`; one `tool.call` per `tool_use`/`tool_result`. Final usage from the `result` event. |
| `opencode` | opencode 1.18.13        | `opencode run --format json` (HTTP via serve) | **Run-level only** — opencode's events are partial (W0.5), so the driver degrades to a `run`-level span per `agent.attempt`. The HTTP polling path emits no NDJSON stream to consume. |
| `cursor` | (cloud)                   | n/a — Cursor Cloud HTTP polling               | **Run-level only** — no local streaming; the driver intentionally does not change its read path (W6.4). |

Graceful degradation is the contract: a driver that cannot stream (or
whose CLI's event shapes are not granular enough) emits run-level
spans rather than failing. The `test_non_streaming_driver_degrades_to_run_level`
and `test_cursor_degrades_to_run_level` regression pins in
`tests/tracing/streaming/test_driver_degradation.py` enforce this.

Malformed events are skipped and counted: the consumer never raises on
a bad line. The counter is available via `StreamSpanAccumulator.malformed_event_count`
and the line is logged at `warning` level.

## Provider and HTTP spans (T2)

Every outbound provider request surfaces as a `provider.call` row with
the transport family on it (`provider.transport_family` is one of
`anthropic` / `responses_api` / `chat_completions`). The driver's
existing `llm.call` span becomes a child of `provider.call`, and every
outbound `httpx` call the driver made (e.g. the OpenAI-compatible
custom-provider POST) becomes a grandchild via `instrument_httpx`.

The Logfire tree therefore matches the sevn reference shape:

```
agent.attempt
├── provider.call  (provider.transport_family=...)
│   ├── http.client.request  (http.method, http.url-redacted, status)
│   └── llm.call             (model.id, cost.*, gen_ai.usage.*)
├── tool.call
└── ...
```

- **When does `provider.call` fire?** Once per upstream API request.
  Claude fires on `message_start` / closes on `message_stop`; Codex on
  `thread.started` / `turn.completed`; Gemini on `init` / `result`. The
  span exists so Logfire groups rows by transport family.
- **When does `http.client.request` fire?** Once per outbound `httpx`
  `send()` on a wrapper mergeCraft constructed (D8 — no global monkey
  patch). The wrapper installs on the two `httpx.AsyncClient` instances
  `agents/opencode.py::_prompt_session` and `agents/opencode.py::_run`
  use for the custom OpenAI-compatible provider path, the only httpx
  sites in the repo.
- **`http.url` is always redacted inline** (D9 — see the URL redaction
  table below).

### URL redaction table

`mergecraft.tracing.redaction.redact_url(url)` masks credential-shaped
fragments while preserving the URL shape. Applied in order; first
match wins per region:

| Pattern | Before | After |
|---------|--------|-------|
| Telegram bot token | `https://api.telegram.org/bot123456:ABC/sendMessage` | `https://api.telegram.org/bot<redacted>/sendMessage` |
| Basic auth | `https://user:pass@example.com/path` | `https://user:<redacted>@example.com/path` |
| Query token (`api_key`, `access_token`, `token`, `key`, `secret`) | `https://example.com/v1/messages?api_key=sk-abc&x=1` | `https://example.com/v1/messages?api_key=<redacted>&x=1` |
| Bearer header value | `Bearer ghp_longtoken123…` | `Bearer <redacted>` |
| Embedded `sk-` / `ghp_` / `eyJ…` substring | `…sk-abc123def…` | `…<redacted>…` |

The literal marker is `mergecraft.tracing.redaction.REDACTED = "<redacted>"`.
The URL stays parseable (`urllib.parse.urlparse` round-trips on every
shape), and non-token query parameters are preserved so the path-based
grouping in Logfire's row inspector keeps working.

## Tool call attributes (T1)

Every `tool.call` span carries the request/response byte counts,
`exit_code`, error class/message, and input-key list sevn splits across
`tool.invoke` / `tool.complete`. The shape is additive on the post-#137
tree (D5: one enriched `tool.call` span, not sevn's `tool.invoke` /
`tool.complete` split) so the existing `tool.name` / `tool.id` /
`tool.server` / `gen_ai.*` attrs remain on the same row. The
`src/mergecraft/tracing/_tool_attrs.py` helpers expose the open-side
`enrich_tool_request` and the close-side `enrich_tool_response`
(W4 / M1 split the legacy single `enrich_tool_call_attrs` into two
single-purpose calls), plus `emit_verb_subevent` so the three drivers
(`claude` / `codex` / `gemini`) and the MCP `tools/call` handler all
emit the same shape.

### `tool.call` attributes

| Attribute | Type | Example | Source |
|-----------|------|---------|--------|
| `tool.name` | str | `"browser"` | existing — preserved |
| `tool.id` | str | `"tool-claude-1"` | existing — preserved |
| `tool.server` | str | `"claude"` / `"codex"` / `"gemini"` / `"mergecraft"` | existing — preserved |
| `tool.input` | dict / str | `{"q": "hello"}` / `"codex-input"` | existing — preserved |
| `tool.output` | any | `"claude-output-text"` | existing — preserved |
| `tool.arguments` | dict | `{"q": "hello"}` | T1 — request-side raw args (MCP server) |
| `tool.argument_count` | int | `1` | T1 — request-side count |
| `tool.argument_bytes` | int | `15` | T1 — request-side JSON-encoded size |
| `tool.input_keys` | list[str] | `["q"]` | T1 — sorted key list (dict input only) |
| `tool.input_bytes` | int | `15` | T1 — driver-side request byte count |
| `tool.exit_code` | str | `"ok"` / `"error"` | T1 — success / failure marker |
| `tool.result_kind` | str | `"text"` / `"json"` / `"image"` / `"list_of_blocks"` / `"unknown"` | T1 — MCP server success path |
| `tool.result_bytes` | int | `18` | T1 — MCP server success path |
| `tool.output_kind` | str | `"text"` / `"json"` / `"image"` / `"list_of_blocks"` / `"unknown"` | T1 — driver-side response classification |
| `tool.output_bytes` | int | `18` | T1 — driver-side response byte count |
| `tool.error_class` | str | `"RuntimeError"` | T1 — failure path only |
| `tool.error_message` | str | `"tool kaboom: …"` (redacted + capped) | T1 — failure path only |
| `gen_ai.operation.name` | str | `"execute_tool"` | existing — preserved |
| `gen_ai.tool.name` | str | `"browser"` | existing — preserved |
| `gen_ai.tool.call.id` | str | `"ab12cd…"` | existing — preserved |
| `gen_ai.tool.input` | str | `"<redacted>"` | T1 — `redact_tool_payload` of the input |
| `gen_ai.tool.output` | str | `"<redacted>"` | T1 — `redact_tool_payload` of the output (success or error message) |

### Verb sub-events (`tool.browse` / `tool.search` / …)

Known-verb tools — `browser`, `search`, `read_file`, `write_file`,
`run_code`, `load_tool` — also emit a verb-specific child span on the
`tool_result` / `item.completed` close event. The mapping is the closed
`KNOWN_VERB_TOOLS` dict in `src/mergecraft/tracing/_tool_attrs.py`:

| Tool name | Child span kind |
|-----------|----------------|
| `browser` | `tool.browse` |
| `search` | `tool.search` |
| `read_file` | `tool.read` |
| `write_file` | `tool.write` |
| `run_code` | `tool.run_code` |
| `load_tool` | `tool.load_tool` |

The child span's `parent_span_id` is the parent `tool.call`'s `span_id`,
and its attrs mirror the parent's so Logfire's row inspector still has
full context for each verb row. Lifecycle: opened on the close event,
closed immediately — no new bookkeeping state. Tools outside the closed
set (a hypothetical `frobnicate`) emit only the parent `tool.call` and
no child.

### Cap and redaction behaviour

`tool.arguments` is capped at `TRACE_ATTRS_JSON_MAX_BYTES` (64 KiB) via
the existing `cap_event_attrs` path: a value past the cap collapses
the row's `attrs` to `{"truncated": True}` so the JSONL line stays
parseable. `tool.output` is stringified + redacted via
`mergecraft.tracing.redaction.redact_tool_payload(payload)` — the helper
runs `json.dumps(default=str)` on non-str values, caps at 64 KiB
(returning `"<truncated>"` on overflow), and pipes the result through
`redact_secrets` so embedded tokens (`ghp_…` / `sk-…` / bearer headers)
cannot escape onto the span. The same helper replaces the local
`_truncate_tool_payload` copies in `agents/claude.py` and
`agents/codex.py` so every driver + the MCP server share one source of
truth.

## One trace per run (T3)

One `mergecraft review` run emits one Logfire trace. Every span
emitted by the run — `mergecraft.run`, `mergecraft.prep`,
`mergecraft.publish`, `mergecraft.analyzers.pipeline`, `analyzer.run`,
`agent.attempt`, `llm.call`, `tool.call`, plus the future `provider.call`
and `http.client.request` — shares one Logfire `trace_id`. The UI groups
spans by `trace_id` (the OTel `trace_id` field on the produced span), so
a single click in the Logfire tree shows the full run — a feature the
pre-#137 tree did not deliver because `mergecraft.trace_id` was just an
attribute on every span rather than the OTel `trace_id` itself.

### What `trace_id` is

`trace_id` is the Logfire / OpenTelemetry trace identifier shared by every
span in one run. The mergeCraft run resolves it once per process (via
`resolve_trace_id()` in `tracing/tracer.py`) and propagates it onto every
child span via the `Tracer` (`self.trace_id`) and the `Span`
(`self.trace_id`). The OTel exporter (`OTLPSink`) forwards it as the
real OTel `trace_id` on the produced span so Logfire groups by it
automatically — no attribute search required.

### How it is generated

The resolver follows the same precedence as the existing session-id
resolver (D7 / T3.2):

1. `MERGECRAFT_TRACE_ID` — explicit per-run override.
2. `MERGECRAFT_TRACE_SESSION_ID` — alias preserving the pre-#137 contract
   so existing pipelines keep working.
3. `GITHUB_RUN_ID` — the Actions run id, monotonic and unique.
4. `uuid.uuid4().hex` — local fallback when no env vars are set.

`session_id` remains the per-process correlation id (the W4 batch-B
session correlation) and `turn_id` is the per-span `uuid4().hex`. The
three fields are orthogonal: change the env precedence and the run still
groups under one trace.

### How Logfire groups by it

`OTLPSink.write` rewrites the OTel `trace_id` on the produced span via
`SpanContext(trace_id=otel_trace_id, …)` (the same private `_context`
field the OTel SDK uses internally). The recording-processor test seam
captures the rewritten `trace_id` so the Logfire-grouping contract is
observable through the existing surface. The
`otel_bridge.attach_trace_context` context manager does the same on the
OTel **context** side, so any nested OTel auto-instrumented operation
(e.g. an `httpx` call inside a tool) inherits the same `trace_id`
without the caller having to know about mergeCraft's tracer. The
`attach_trace_context` integration in
`agents/_stream_consumer.py::consume_stream` wraps the handler call so
any nested OTel operation inside an agent's per-event handler inherits
the run's trace.

## Three identifiers: review.id, trace_id, review.correlation_key (OB1)

One logical review fans out into several processes: the orchestrating run
plus one spawned agent CLI per subagent. Three identifiers — not two —
describe that shape (D2):

| Identifier | Scope | Source |
| --- | --- | --- |
| `review.id` | **One logical review**, across every process and agent run | `tracing/review_context.py::resolve_review_id()` — `MERGECRAFT_REVIEW_ID` inherited verbatim, else a fresh `uuid4` per review |
| `trace_id` | **One agent run** (one process) | `tracing/tracer.py::resolve_trace_id()` — see *One trace per run (T3)* above |
| `review.correlation_key` | **Every attempt at one commit** — deliberately collides | `correlation_key_for()` — deterministic `sha256(repo\|pr\|head_sha)` (D3) |

The shape to remember: **one review with three agent runs has one
`review.id` and three `trace_id` values.** One `review.id` filter returns
the entire review — every agent, every tool call, the verdict — across
every process. `review.correlation_key` answers the orthogonal query:
"every attempt at this commit", because two reviews of one commit are two
reviews (distinct `review.id`s) but share the key (D3). A local patch
review has no repo/pr/head context, so its key is empty and the attribute
is omitted rather than emitted as a misleading constant.

### How the identity travels

- **Within a process:** both entry points — the CLI
  (`offline_review.py::run_offline_diff_review`) and the Action
  (`main.py::main`) — bind a frozen `ReviewContext` via
  `bind_review_context(...)`. `Span.close()` reads the bound context at
  **close time** (D4), so a context bound after the tracer was built still
  reaches spans that are already open. Merge precedence: tracer baseline →
  review context → lazy `attrs_source` → explicit `set_attribute`.
- **Across the process boundary (O2):** `agents/shared.py::spawn_agent_cli`
  — the single choke point for all five drivers — exports
  `MERGECRAFT_REVIEW_ID` + `MERGECRAFT_REVIEW_CORRELATION_KEY` into the
  child env via `setdefault`, after the privilege-drop env patch. A
  driver-pinned value wins; a fail-closed `setpriv` error still surfaces
  first. The child's `resolve_review_id()` then inherits the parent's
  review verbatim.
- **Baseline attrs (O3):** `baseline_run_attrs()` stamps every span with
  `mergecraft.version`, `mergecraft.run_id`, `mergecraft.trust_tier`, and
  the VCS/CI fields (`vcs.repository.name`, `vcs.change.id`,
  `vcs.revision`, `ci.workflow_run_id`, `ci.job_id`) so a span can say
  which build and which change produced it. The `Tracer` carries them in a
  `baseline_attrs` field with `repr=False` (D5).

## What's next

| Batch | Wave  | Scope                                                |
| ----- | ----- | ---------------------------------------------------- |
| C     | W6    | `stream-json` migration for per-tool spans            |
| D     | W8    | `logfire` + `otel` exporters, CLI / action inputs, complete docs (DONE) |

## Self-hosted endpoints (W8.1 / D5)

The `otel` sink accepts any OTLP/HTTP collector URL. The token / API key
travels as an `Authorization: Bearer …` header; the `headers` map on the
config entry can carry extra static headers for proxies, tenants, or
custom routing.

```yaml
tracing:
  enabled: true
  sinks:
    - type: otel
      endpoint: https://otel.internal.example.com:4318/v1/traces
      headers:
        x-tenant: mergecraft
```

For Logfire, the endpoint is the region-aware OTLP/HTTP ingest URL —
`https://logfire-us.pydantic.dev/v1/traces` (US) or
`https://logfire-eu.pydantic.dev/v1/traces` (EU), selected by the sink's
`region` field (default `us`). The `project` field is informational only;
Logfire routes spans by the token itself, so no `x-logfire-project` header
is sent. The token is resolved through `tokenRef` (D5) — see *Token
resolution* below.

## Token resolution (W8.2 / D5)

`logfire` tokens are referenced by name, never inlined. The factory
resolves a `tokenRef` against `os.environ` at run time; when the
reference is unset, the resolver falls back to the canonical
`MERGECRAFT_LOGFIRE_TOKEN` env var. The resolved value is held in
runtime memory only — it never appears in config dumps, YAML
round-trips, or the `mergecraft config tracing` output. The CLI
renders the value as `*** (redacted)` even in the table form.

When the token cannot be resolved, the sink is constructed but emits a
warning and degrades to a no-op for the network path. The local
`jsonl_file` sink (when configured) keeps writing.

## Action inputs (W8.5 / W7.7)

`action.yml` exposes four inputs so a consuming repo can wire tracing
without touching `.mergecraft/config.yaml`:

| Input            | Maps to                                              |
| ---------------- | ---------------------------------------------------- |
| `tracing`        | `tracing.enabled` (overrides config)                 |
| `tracing-to`     | `tracing.to` shorthand (overrides config)            |
| `logfire-token`  | resolved logfire token (D5 — held at runtime only)   |
| `otel-endpoint`  | `tracing.sinks[].endpoint` for the `otel` sink type  |

The Action wraps `${{ secrets.LOGFIRE_TOKEN }}` into `logfire-token`
so the secret never appears in the workflow file.

## CLI surface (W8.4 / W7.6)

```text
mergecraft review --tracing|--no-tracing [--tracing-to <shorthand>] \
                       [--trace-dir <path>] [--logfire-token <token>] \
                       [--otel-endpoint <url>]
mergecraft config tracing     # render resolved state with token redacted
mergecraft traces <run-id>    # read back local JSONL spans for a run id
```

The precedence order is **CLI flag > env var > `.mergecraft/config.yaml`
> default (off)**. `--no-tracing` wins over any lower-precedence
`true`. The full table is asserted by `tests/tracing/exporters/test_cli_precedence.py`.

`mergecraft config tracing` does **not** require the `tracing` extra
— it operates on resolved settings, not on the live exporters.

## Artifact upload (W8.6 / D14)

The Action writes local traces under `.mergecraft/traces/`. A typical
workflow ships them out of CI with `actions/upload-artifact@v4`:

```yaml
- uses: alexhawat/mergecraft@<ref>
  with:
    tracing: "true"
    tracing-to: local_files
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: mergecraft-traces
    path: .mergecraft/traces/
```

`if: always()` ensures the artifact is uploaded even when the review
exits non-zero — the trace is the most useful when the run failed.
The path is `.mergecraft/traces/` by default; override with the
`trace_dir` config field or the `--trace-dir` flag.

## Structured logs (operator debugging, W12.6 / #33)

Tracing owns spans; default Loguru output stays human-readable. For
correlation fields in the log stream itself (without enabling tracing),
opt into JSON:

```bash
export MERGECRAFT_LOG_FORMAT=json   # or LOG_FORMAT=json
# optional: LOG_LEVEL=DEBUG
```

When JSON is on, each record includes bound context when available:

| Field | Source |
|-------|--------|
| `run_id` | `GITHUB_RUN_ID` (bound in `main`) |
| `repo` | `owner/name` for the run |
| `pr` | pull-request number when the event carries one |
| `phase` | coarse run phase (`setup`, …) |

Bind or refresh fields from code with
`mergecraft.utils.log.bind_run_context(...)`. Use tracing (`docs/TRACING.md`
above) when you need model/tool span trees; use JSON logs when you need a
grep-friendly stream of the same run on the runner console or log drain.
