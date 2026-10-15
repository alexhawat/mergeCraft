# Ultramarine 1 Flash as a second reviewer

Paper Instruments **Ultramarine 1 Flash** is a curated OpenAI-compatible model
(`paperinstruments/ultramarine-1-flash`). Use it as a **secondary reviewer**
alongside your primary model; mergeCraft attributes findings to each reviewer,
deduplicates overlaps, and computes per-review cost from token usage.

Review **duration** in posted messages is handled separately (not in this guide).

## Provider registry (local)

Add a `providers:` row in `.mergecraft/config.local.yaml`. Put **`harness` on the
provider row**, not at the top level of the file:

```yaml
providers:
  - label: paperinstruments
    url: https://api.paperinstruments.com/v1
    harness: opencode
    models:
      - id: ultramarine-1-flash
        modelIndex: 1
```

Register the API key with indexed workflow secrets (example index `2`):

```bash
mergecraft provider add --label paperinstruments \
  --url https://api.paperinstruments.com/v1 \
  --harness opencode
mergecraft model add --provider paperinstruments ultramarine-1-flash
```

## Environment variables

In `.env` or GitHub Actions `env:`:

```bash
LLM_PROVIDER_2=paperinstruments
LLM_PROVIDER_2_API_KEY=<your Paper Instruments API key>
MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_2='{"max_completion_tokens":8192,"reasoning_effort":"low","context_limit":128000}'
```

Ultramarine **must** have an output token cap (Paper Instruments prepay billing).
The catalog default is `8192` when you omit `max_completion_tokens`.

Use the indexed `MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_<N>` that matches your
provider's `LLM_PROVIDER_<N>` index. The singleton
`MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS` still works for single-provider setups.

## Second reviewer roster

Commit `.mergecraft/config.yaml` (or override locally with `config.local.yaml` for
CLI experiments):

```yaml
models:
  - anthropic/claude-sonnet
  - paperinstruments/ultramarine-1-flash

agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
  reviewer2:
    role: reviewer
    modelChain:
      - paperinstruments/ultramarine-1-flash
```

Both reviewers run on the same PR; findings show `_Raised by: reviewer2
(`paperinstruments/ultramarine-1-flash`)_` when provenance is displayed.

## CLI and CI

Local review with Ultramarine only:

```bash
mergecraft review --model paperinstruments/ultramarine-1-flash
```

Inspect what CI will run (credentials, dispatch levels):

```bash
mergecraft provider status --json
```

In GitHub Actions, set `with.model` to your primary slug and ensure the workflow
`env:` block includes `LLM_PROVIDER_*` rows for every registered provider, then
run `mergecraft workflow sync --apply` so the auth manifest matches config.

Posted reviews include **Cost** in the server-owned run record when token usage
is available, priced at $0.15/M uncached input, $0.03/M cached input, and
$0.50/M output (reasoning included).
