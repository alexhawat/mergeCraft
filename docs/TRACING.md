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
mergecraft diff-review --tracing --tracing-to logfire
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

## Config schema

```yaml
tracing:
  enabled: true                # default: false
  retentionDays: 30            # default: 30
  redaction: true              # default: true
  sinks:
    - type: jsonl_file
      path: .mergecraft/traces/
    # Batch D adds: logfire, otel (behind the [tracing] extra, D6).
```

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

## One trace per run (T3)

One `mergecraft diff-review` run emits one Logfire trace. Every span
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
mergecraft diff-review --tracing|--no-tracing [--tracing-to <shorthand>] \
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
