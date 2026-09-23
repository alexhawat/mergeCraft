---
description: Set up Logfire tracing for mergeCraft (local or CI)
agent: build
---

Set up Logfire tracing for mergeCraft. $ARGUMENTS

Local (writes `MERGECRAFT_LOGFIRE_TOKEN` and `MERGECRAFT_TRACING_PROJECT` to
`.env`, never calls GitHub):

```bash
mergecraft auth logfire
mergecraft tracing logfire enable --token "$MERGECRAFT_LOGFIRE_TOKEN" --project "$MERGECRAFT_TRACING_PROJECT"
mergecraft config tracing
```

CI (patches the mergecraft workflow to pass the Actions secret and region):

```bash
mergecraft tracing logfire wire-workflow --region us   # or --region eu
```

The CLI's own tracing covers the `cli`, `deep`, and `mcp` engines. When a Logfire
token is present, the OpenCode plugin also emits a span for each **native**
review, so native and deep runs share one Logfire project. Ask the user for the
token only through `mergecraft auth logfire` — never write a token into a file or
a prompt yourself.
