<!-- Generated header — sentinel block below is spliced by scripts/gen_reference_docs.py. -->

# CLI reference

Full `mergecraft` command reference derived from the live Typer application.

**Audience:** consumer

Pass `--help` to any invocation below for its full flag set.

<!-- BEGIN:cli-commands -->
| Command | Description |
|---------|-------------|
| `mergecraft agents list` | List agent bindings with model chain, prompt id, and tool count. |
| `mergecraft agents set <role>` | Write a single agent binding override into `.mergecraft/config.yaml`. |
| `mergecraft agents show <role>` | Show resolved prompt text and MCP tool names for one role. |
| `mergecraft analyzers detect` | Show analyzers that would run for changed paths in this repo. |
| `mergecraft analyzers docs` | Regenerate `ANALYZERS.md` from manifests. |
| `mergecraft analyzers explain <analyzer-id>` | Print manifest fields and notes for one analyzer. |
| `mergecraft analyzers export <analyzer-id>` | Run one analyzer and export findings as SARIF. |
| `mergecraft analyzers list` | List catalog analyzers and whether they would enable here. |
| `mergecraft analyzers lock` | Write or refresh `.mergecraft/analyzers.lock` for managed tools. |
| `mergecraft analyzers run <analyzer-id>` | Execute one analyzer against the working tree. |
| `mergecraft ask` | Show a file-line excerpt or canned text; does not call a model. |
| `mergecraft audit export` | Export the audit log as a JSON array. |
| `mergecraft auth claude` | Save a Claude Code OAuth token as CLAUDE_CODE_OAUTH_TOKEN. |
| `mergecraft auth codex` | Mint a Codex subscription credential and save it as CODEX_AUTH_JSON. |
| `mergecraft auth cursor` | Save a Cursor API key as CURSOR_API_KEY. |
| `mergecraft auth gemini` | Save a Gemini API key as GEMINI_API_KEY. |
| `mergecraft auth logfire` | Save a Logfire write token + project for the `logfire` tracing sink. |
| `mergecraft auth minimax` | Save a MiniMax API key as MERGECRAFT_CUSTOM_PROVIDER_API_KEY. |
| `mergecraft auth nous` | Save a Nous Portal API key as NOUS_API_KEY. |
| `mergecraft auth tokenhub` | Save a Tencent TokenHub API key as TOKENHUB_API_KEY. |
| `mergecraft cache clear` | Remove every entry from the run cache. |
| `mergecraft cache info` | Show cache location, byte ceiling, and current usage. |
| `mergecraft cache prune` | Evict oldest entries until usage is within the byte ceiling. |
| `mergecraft capabilities` | Print the review-only capability manifest. |
| `mergecraft config explain <key>` | Explain which precedence layer wins for a config key. |
| `mergecraft config show <key>` | Show a resolved config value and the precedence layer that supplied it. |
| `mergecraft config tracing` | Render the resolved tracing config — sinks, retention, redaction, token redacted. |
| `mergecraft config validate` | Validate repo config — unknown keys are rejected (extra=forbid). |
| `mergecraft context explain` | Explain why retrieved context was selected for a review. |
| `mergecraft context inspect` | Report sources, scope, provenance citations, and token totals. |
| `mergecraft context search <query>` | Search retrieved review context for a query. |
| `mergecraft describe` | Print a PR title, summary, walkthrough, risk areas, and testing notes. |
| `mergecraft doctor` | Diagnose git, providers, analyzers, auth, config, and MCP wiring. |
| `mergecraft eval add` | Add a case to the bank. |
| `mergecraft eval bench` | Join structural decision replay with a live finding-location run (#140, B3). |
| `mergecraft eval gate` | Check the eval bank's integrity and adversarial corpora — the CI-safe half. |
| `mergecraft eval list` | List cases in the bank. |
| `mergecraft eval promote <case-id>` | Promote a case into a permanent pytest test file (#44, W12.1). |
| `mergecraft eval replay <case-id>` | Replay a case and report the diff. |
| `mergecraft eval replay-bank` | Replay the eval bank and write a versioned benchmark result set (#140). |
| `mergecraft eval score <actual> <expected>` | Score review findings against a frozen benchmark baseline. |
| `mergecraft evidence show <finding-id>` | Show the evidence packet for a finding. |
| `mergecraft evidence verify <finding-id>` | Replay verification for a finding's evidence packet (not an approval). |
| `mergecraft explain` | Explain a stored finding or the current working-tree change. |
| `mergecraft findings carryover --pr N` | File one issue per unresolved mergeCraft finding. Dry run unless `--apply`. |
| `mergecraft findings export --pr N` | Print the findings a merge would bury. Never writes anything. |
| `mergecraft gha token` | Acquire a GitHub App installation token, or revoke it with `--post`. |
| `mergecraft health run` | Emit JSON health status for the running mergeCraft installation. |
| `mergecraft init` | Scaffold `.mergecraft/config.yaml` and an example workflow (local, no API). |
| `mergecraft learnings active` | List only the active (promoted) learning entries. |
| `mergecraft learnings influence` | List active + staging learning entries with their provenance. |
| `mergecraft learnings staging` | List only the staging (quarantined) learning entries. |
| `mergecraft lens list` | List bundled lens ids and display titles. |
| `mergecraft lens show <lens-id>` | Show rubric, triggers, evidence, and tool classes for one lens. |
| `mergecraft lens test <lens-id>` | Preview one lens dispatch (rubric + routing context) for a diff fixture. |
| `mergecraft mcp list` | Print the resolved MCP tool names for a role. |
| `mergecraft mcp serve` | Start the MCP HTTP server for a resolved workspace and role. |
| `mergecraft memory export --output OUTPUT` | Export repo memory to a JSON bundle. |
| `mergecraft memory feedback` | Record accepted / dismissed / disputed feedback for a finding fingerprint. |
| `mergecraft memory forget` | Remove one active memory entry. |
| `mergecraft memory import <bundle-path>` | Import a memory export bundle into a repository. |
| `mergecraft memory list` | List active memory entries for a repository. |
| `mergecraft memory show` | Show one memory entry by id. |
| `mergecraft memory validate` | Validate the repo memory document for structure, staleness, and conflicts. |
| `mergecraft models list` | List curated model slugs and whether credentials are detected locally. |
| `mergecraft models set <slugs>` | Write an ordered `models:` list to `.mergecraft/config.yaml`. |
| `mergecraft models show` | Show effective model order, env override, and the slug that would win now. |
| `mergecraft pipeline explain` | Print pipeline step ids and predicate vocabulary. |
| `mergecraft pipeline lint` | Validate the pipeline file and registry agent references. |
| `mergecraft pipeline show --diff DIFF` | Preview which pipeline steps would run or skip for a diff. |
| `mergecraft plan` | Preview model chain, toolset, analyzers, and token estimate without provider calls. |
| `mergecraft policy effective` | Show the effective policy set and the source of every rule. |
| `mergecraft policy explain --path PATH` | List effective rules for a path and name each rule's source layer. |
| `mergecraft policy lint` | Validate policy rule YAML under `.mergecraft/policy/`. |
| `mergecraft policy simulate` | Simulate a proposed rule against past PRs. |
| `mergecraft policy test --fixtures FIXTURES` | Run should-trigger and should-not policy fixtures. |
| `mergecraft profile recommend --risk RISK` | Print the review profile auto-selected from `--risk`. |
| `mergecraft replay` | Replay a stored review run from local traces (read-only). |
| `mergecraft requirements explain <requirement-id>` | Explain one requirement by id; unknown ids are an error. |
| `mergecraft requirements inspect` | List ingested requirements and their states. |
| `mergecraft review` | Review a local git diff offline (no GitHub Action / PR posting). |
| `mergecraft run diff` | Compare two stored review runs by event kind. |
| `mergecraft run inspect` | Inspect a stored review run (or list known run ids). |
| `mergecraft support-bundle write` | Write a support bundle archive to OUTPUT. |
| `mergecraft traces show <run-id>` | Read back the local JSONL traces for the given run id (re-redacts on render). |
| `mergecraft tracing logfire disable` | Disable Logfire tracing by removing the token + project locally and on GitHub. |
| `mergecraft tracing logfire enable` | Enable Logfire tracing by writing the token + project locally and on GitHub. |
| `mergecraft tracing logfire unwire-workflow` | Remove Logfire tracing wiring from the consumer workflow. |
| `mergecraft tracing logfire wire-workflow` | Wire Logfire tracing into the consumer workflow. |
| `mergecraft version` | Show the mergeCraft package version. |
| `mergecraft watch --pr N` | Stream a PR/issue timeline as one JSON line per new event. |
| `mergecraft xrepo explain` | Explain a cross-repo finding, or report producer/consumer contract breakage. |
<!-- END:cli-commands -->

The bare `gha` group invocation (no subcommand) is the Docker action's runtime
entry point — it is a Typer group callback, not a `registered_commands` leaf
itself, so it is described here in prose rather than as its own table row;
`mergecraft gha token` above is the one real leaf command under that group.

## See also

- [Action reference](action-reference.md)
- [Exit codes](EXIT-CODES.md)
- [Landing README](../README.md)
