---
description: Set up mergeCraft in this repo for OpenCode
agent: build
---

Set up mergeCraft in this repository per
<https://github.com/alexhawat/mergeCraft/blob/main/AGENTS.md>, using the
`opencode` harness.

1. Install the CLI (uv fetches its own Python — do not install Python):

   ```bash
   uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
   ```

2. Scaffold:

   ```bash
   mergecraft init
   ```

3. In `.mergecraft/config.yaml` set `harness: opencode` and a model chain, for
   example `models: ["<provider>/<model>"]`. For a third-party
   OpenAI-compatible gateway, read `docs/authentication.md` and print the
   `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL` / `MERGECRAFT_CUSTOM_PROVIDER_API_KEY`
   pair for the user to set as secrets — never handle the key.

4. **STOP.** Ask the user to run one `mergecraft provider auth <label-or-id>
   --scope github` command themselves (or `--scope local` for evaluation).
   Never invent, paste, or commit credentials.

5. Optional, on request: `mergecraft jev enable` (screening gate; prompts for
   `TYPESAFE_API_KEY`) and `mergecraft auth logfire` (tracing).

6. Install this integration: copy `integrations/opencode/commands`,
   `integrations/opencode/agents`, and `integrations/opencode/plugins` into
   `.opencode/`, and add the `mcp.servers.mergecraft` block from
   `integrations/opencode/opencode.jsonc` to the project `opencode.jsonc`.

7. Commit only `.mergecraft/config.yaml`, `.mergecraft/learnings.md`,
   `.github/workflows/mergecraft.yml`, the new `.opencode/**` and
   `opencode.jsonc`, and any `.gitignore` lines `init` added. Open a PR.

Default workflow does not listen for `@mergecraft review` comments; comment
triggers are opt-in (`docs/workflows.md`).
