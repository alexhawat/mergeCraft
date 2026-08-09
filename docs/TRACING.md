# Tracing — configuration, sinks, redaction, retention

> Status: **active**. Batch A (W2) covers the config schema, the canonical
> span model, the local JSONL sink, and the redaction boundary. Batch B
> (W4) wires the span tree at every production seam — see "Span tree"
> below. Batch D (W8) fills in the remote exporters, the optional extra,
> and the CLI / `action.yml` surface. Reference issue: [#56][i56].

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

## What's next

| Batch | Wave  | Scope                                                |
| ----- | ----- | ---------------------------------------------------- |
| C     | W6    | `stream-json` migration for per-tool spans            |
| D     | W8    | `logfire` + `otel` exporters, CLI / action inputs, complete docs |
