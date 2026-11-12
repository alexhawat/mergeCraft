# Uninstalling or pausing mergeCraft

Turn mergeCraft off for one repository, or remove it completely.

**Audience:** consumer (product and setup documentation)

Pick the smallest step that does what you want. Each step is independent.

## Pause reviews without removing anything

- **One run:** skip it by not triggering it. The default scaffold runs on
  `pull_request` and `workflow_dispatch`.
- **Stop all reviews:** disable the workflow in the repository's **Actions** tab
  (**mergeCraft → Disable workflow**), or in the CLI with
  `gh workflow disable mergecraft.yml`. Re-enable it the same way.
- **Stop one provider:** `mergecraft provider disable <label>` clears that
  provider's credentials so CI stops selecting it
  ([authentication](authentication.md#turning-a-provider-off)).

If `mergecraft` or `mergecraft-approval` is a required status check in branch
protection, a disabled workflow never reports it and pull requests will wait.
Remove it from the required checks first (below).

## Remove mergeCraft from a repository

1. **Remove the required checks.** In **Settings → Branches** (or your
   ruleset), delete `mergecraft` and `mergecraft-approval` from the required
   status checks. Do this before step 2.

2. **Delete the credentials.** Clear every provider you authenticated, in both
   places it may live:

   ```bash
   mergecraft provider list
   mergecraft provider disable <label> --scope both
   ```

   `--scope both` deletes the Actions secret and blanks the entry in your local `.env`. It
   clears both the flat secret the workflow names and the indexed
   `LLM_PROVIDER_<N>_*` key. If you added a Logfire token, clear it with
   `mergecraft tracing logfire disable --scope both`. A secret you created by
   hand is removed with `gh secret delete <NAME>`.

   Credentials issued by a provider (an API key, or a subscription login) are
   not revoked by this. Revoke them at the provider if you want them dead.

3. **Delete the workflow and config.** In a branch, remove the files `mergecraft init`
   created and open a pull request:

   ```bash
   git rm .github/workflows/mergecraft.yml
   git rm -r .mergecraft
   ```

   `.mergecraft/` holds `config.yaml` and `learnings.md`, which stays in git
   history if you want to recover it. Also remove any `.gitignore` lines `init`
   added for local files such as the analyzer cache, completed reviews and audit
   log, and delete local `.env` entries starting with `LLM_PROVIDER_`.

4. **Remove the CLI** (optional, once per machine):

   ```bash
   uv tool uninstall mergecraft-action
   ```

## Remove agent and editor integrations

mergeCraft can also be installed into coding agents. Remove what you added:

- **Agent skill:** delete the `mergecraft` directory you copied into your
  agent's skills path ([agents](agents.md)).
- **MCP server:** delete the `mergecraft` server entry from the host's MCP
  config ([MCP](mcp.md)).
- **OpenCode:** delete the commands, subagent, plugin and MCP block that
  `mergecraft opencode install` wrote ([OpenCode](opencode.md)).
- **Claude plugin:** remove the plugin from your Claude Code installation.

## What stays behind

- Review comments and check runs already posted stay on closed and merged pull
  requests; GitHub owns them.
- Workflow run logs and artifacts expire under your repository's retention
  settings.
- Nothing is held by mergeCraft: there is no hosted account or dashboard to
  close ([BYOK](glossary.md#byok)).

## See also

- [Installing mergeCraft](install.md)
- [Authentication](authentication.md)
- [Troubleshooting](troubleshooting.md)
