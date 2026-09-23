---
description: Set up Logfire tracing for mergeCraft (local or CI)
agent: build
---

Set up Logfire tracing for mergeCraft. $ARGUMENTS

**Local** — `auth logfire` writes the write token and project label to `.env`; it
does not export them into the current shell. `tracing logfire enable` then reads
them from `.env`:

```bash
mergecraft auth logfire
mergecraft tracing logfire enable --scope local --region us   # or --region eu
mergecraft config tracing                                     # token redacted
```

Do not expand `$MERGECRAFT_LOGFIRE_TOKEN` / `$MERGECRAFT_TRACING_PROJECT` on the
command line — they are not exported, so the flags would receive empty values.

**CI** — `wire-workflow` is dry-run by default and prints the diff; pass `--apply`
to write it:

```bash
mergecraft tracing logfire wire-workflow --region us          # dry-run: show the diff
mergecraft tracing logfire wire-workflow --region us --apply  # write it
```

Use `--region eu` for an EU write token (`pylf_v{N}_eu_…`); otherwise spans go to
the US host.

The CLI's own tracing covers the `cli`, `deep`, and `mcp` engines. The plugin
also emits a span for each **native** review when a Logfire token is present, so
native and deep runs share one Logfire project. Ask the user for the token only
through `mergecraft auth logfire` — never write a token into a file or a prompt
yourself.
