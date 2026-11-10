---
description: Set up mergeCraft AI PR review in the current repository
---

Set up mergeCraft in this repo by following the skill's setup checklist:

1. Check the prerequisites.
   <!-- BEGIN:requirements -->
   **Requirements:** [uv](https://docs.astral.sh/uv/) is the only prerequisite for the
   install; it downloads a compatible Python (3.11+) itself, so no system Python is
   needed. The [GitHub CLI](https://cli.github.com) (`gh auth login`) is needed only
   for `provider auth --scope github` (the default), which stores the secret
   with `gh secret set`; `mergecraft init` and `--scope local` need neither `gh` nor a
   network. Two providers need one more CLI at the credential step: the Codex CLI for `openai`
   and Claude Code for `anthropic`
   ([provider table](../docs/authentication.md)).
   <!-- END:requirements -->
   If uv cannot be installed, use the Docker Action path only
   ([`docs/install.md`](../docs/install.md)).
2. Run:

   ```bash
   uv tool install "mergecraft-action @ git+https://github.com/alexhawat/mergeCraft"
   mergecraft init
   ```

3. **STOP before authentication.** Ask me to run the interactive
   `mergecraft provider auth <provider> --scope github` step (a configured label or id from `mergecraft provider list`; see
   [`docs/authentication.md`](../docs/authentication.md)). Never invent or commit
   credentials or secrets.
4. Commit only `.mergecraft/config.yaml` and `.github/workflows/mergecraft.yml`
   on a new branch and open a pull request.
