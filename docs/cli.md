<!-- Generated header — sentinel block below is spliced by scripts/gen_reference_docs.py. -->

# CLI reference

Full `mergecraft` command reference derived from the live Typer application.

**Audience:** consumer

Pass `--help` to any invocation below for its full flag set.

## Repository and output locations

`review` separates the shell's invocation directory, the selected source
repository, and explicit output destinations. Choose a checkout before choosing
a revision; a diff alone is not a replacement for its surrounding source tree.

| Input or operation | Source/configuration context | Storage and side effects |
|---|---|---|
| `review --cwd PATH` | Selects that local workspace, taken literally; when omitted, the git root of the invocation directory (the invocation directory itself outside a checkout). Every command with a `--cwd`, `--repo-root` or `--repo` directory option follows the same rule. Repository settings and implicit local `.env` follow the selected local target. | Review snapshots persist in the resolved local repository. Cache entries use that repository’s identity but live in `MERGECRAFT_CACHE_DIR` or the global XDG cache. The parent shell does not change directory. |
| `review --repo PATH` | Selects an existing local repository instead of the caller's repository. | Results persist under that repository; explicit output paths still follow the invocation directory. |
| Remote `--repo URL` or PR source | Acquires a source checkout and reads its repository configuration. Remote acquisition does not load a cloned `.env` as local credentials. | Durable `.mergecraft/reviews` records live under selected `--cwd` (default: git root of the invocation directory); snapshots identify the normalized remote URL and resolved commit, with manifests/evidence from the acquired source. |
| `--head REF` or a commit range | When selecting a revision diff (without `--diff`, `--staged`, or `--unstaged`), for a local repository, the reviewed endpoint must equal its checked-out `HEAD`, and the tracked/nonignored working tree must be clean. Otherwise the command rejects the request. | Use a separate `git worktree` or check out the requested revision first. mergeCraft does not silently switch the user's local branch. |
| Default working-tree review | Includes tracked changes and eligible nonignored additions relative to the selected base. Ignored environments/caches are outside source scope. | Oversized, binary, symlink or non-UTF-8 eligible additions are reported as coverage limitations. An empty but incomplete diff is not a clean pass. |
| `--unstaged` | Reads tracked unstaged changes and eligible untracked additions, preserving omission metadata. | Does not stage or commit files. |
| `MERGECRAFT_ENV` / ambient environment | An explicit env-file override wins; existing process variables keep precedence over loaded file values. GitHub Actions skips implicit local `.env` loading; local startup also skips Git-tracked implicit files and links to them. | Relative explicit env-file paths follow the invocation directory. See [authentication](authentication.md). |
| `--output` / `--json` | Explicit destinations are interpreted relative to the invocation directory. | JSONL/SARIF require `--output` before review starts; missing destinations produce a configuration error. |
| `verify-behavior` YAML `repo_path` | Selects the policy/settings root and `startup_command` working directory. Relative paths follow the invocation directory; `~` expands. | Relative verification artifact paths remain relative to the invocation directory. See [verification](verify-behavior.md). |

**Compatibility change:** local `review --range main..HEAD` and `review --head REF`
now require the selected endpoint to match the checkout and refuse staged changes,
unstaged changes, and nonignored untracked source files, including scratch files
such as `notes.txt`. The agent reads the checkout as context, so a commit-only diff
cannot safely describe a different working tree. Commit or stash that work
(`git stash push --include-untracked` also saves untracked files), or review in a
separate clean `git worktree` at the requested revision. Ignored files and
mergeCraft's untracked runtime artifacts do not trigger this refusal. Use the
default working-tree review when you intend to review local edits.

Cache reuse requires both a matching review patch/configuration and a trustworthy
source-context identity. Changing surrounding tracked or nonignored source,
the base revision, or the reviewed endpoint invalidates reuse. When context
cannot be safely fingerprinted, caching is skipped instead of claiming a hit.
This includes submodules, external symlinks, unreadable source, and contexts
exceeding 10,000 files or 64 MiB. Debug logging explains the skip without
including file contents. External symlinks remain uncached because registered
cross-repository roots can make their mutable targets visible to review tools;
the selected repository's digest does not identify those targets.

Untracked `.mergecraft/reviews/`, `.mergecraft/analyzer-cache/` and the legacy
`.mergecraft/audit.jsonl` are generated output: they do not dirty an explicit
local revision review, enter its diff, or invalidate its result cache. Tracked
files at those locations still count as source. Other nonignored untracked
files, including repository configuration, continue to count.

The CLI's local file/environment rules are separate from Action checkout and
operator-setting snapshots. Bound Action reviews retain their immutable reviewed
commit for approval and completion. An unbound run can publish a diagnostic
completion against the current API head, but cannot approve it. A later PR push
needs a new review.

<!-- BEGIN:cli-commands -->
| Command | Description |
|---------|-------------|
| `mergecraft agent add-model <name> <slug>` | Append a registered model to an agent's chain (no-op when duplicate). |
| `mergecraft agent assign-model <name> <slot> <slug>` | Register the model when needed, assign the slot, wire harness providers into `mergecraft.yml`, and set `with.model` on p0 for the `reviewer` agent (idempotent). |
| `mergecraft agent create <name>` | Create a new roster entry with role defaults. |
| `mergecraft agent delete <name>` | Remove an agent binding (refuses the last required reviewer or verifier). |
| `mergecraft agent list` | List every agent, role, model chain, and dispatch level. |
| `mergecraft agent remove-model <name> <token>` | Remove a model slot and compact the chain. |
| `mergecraft agent set-after <name> <after>` | Change dispatch ordering after agent creation. |
| `mergecraft agent show <name>` | Show one agent's chain, resolved model, and effective limits. |
| `mergecraft agent-local add-model <name> <slug>` | Append a registered model to an agent's chain (no-op when duplicate). |
| `mergecraft agent-local assign-model <name> <slot> <slug>` | Register the model when needed and assign the slot in `.mergecraft/config.local.yaml` (local-only; does not change CI workflow). |
| `mergecraft agent-local create <name>` | Create a new roster entry with role defaults. |
| `mergecraft agent-local delete <name>` | Remove an agent binding (refuses the last required reviewer or verifier). |
| `mergecraft agent-local list` | List every agent, role, model chain, and dispatch level. |
| `mergecraft agent-local remove-model <name> <token>` | Remove a model slot and compact the chain. |
| `mergecraft agent-local set-after <name> <after>` | Change dispatch ordering after agent creation. |
| `mergecraft agent-local show <name>` | Show one agent's chain, resolved model, and effective limits. |
| `mergecraft agents addbackupmodel` | Append a registered model to an agent's backup chain. |
| `mergecraft agents list` | List agent bindings with model chain, prompt id, and tool count. |
| `mergecraft agents set <role>` | Write a single agent binding override into `.mergecraft/config.yaml`. |
| `mergecraft agents setmodel` | Replace the primary model for an agent role; backups are preserved. |
| `mergecraft agents show <role>` | Show resolved prompt text and MCP tool names for one role. |
| `mergecraft analyzers detect` | Show analyzers that would run for changed paths in this repo. |
| `mergecraft analyzers explain <analyzer-id>` | Print manifest fields and notes for one analyzer. |
| `mergecraft analyzers export <analyzer-id>` | Run one analyzer and export findings as SARIF. |
| `mergecraft analyzers list` | List catalog analyzers and whether they would enable here. |
| `mergecraft analyzers lock` | Write or refresh `.mergecraft/analyzers.lock` for managed tools. |
| `mergecraft analyzers run <analyzer-id>` | Execute one analyzer against the working tree. |
| `mergecraft ask` | Show a file-line excerpt or canned text; does not call a model. |
| `mergecraft audit export` | Export the audit log as a JSON array. |
| `mergecraft audit verify` | Verify the audit hash chain and print any broken line numbers. |
| `mergecraft auth claude` | Save a Claude Code OAuth token as CLAUDE_CODE_OAUTH_TOKEN. |
| `mergecraft auth codex` | Mint a Codex subscription credential and save it as CODEX_AUTH_JSON. |
| `mergecraft auth cursor` | Save a Cursor API key as CURSOR_API_KEY. |
| `mergecraft auth gemini` | Save a Gemini API key as GEMINI_API_KEY. |
| `mergecraft auth logfire` | Save a Logfire write token + project for the `logfire` tracing sink. |
| `mergecraft auth minimax` | Save a MiniMax API key as MERGECRAFT_CUSTOM_PROVIDER_API_KEY. |
| `mergecraft auth opencode` | Save OpenCode Zen credentials as OPENCODE_AUTH_JSON. |
| `mergecraft auth tokenhub` | Save a Tencent TokenHub API key as TOKENHUB_API_KEY. |
| `mergecraft cache clear` | Remove every entry from the run cache. |
| `mergecraft cache info` | Show cache location, byte ceiling, and current usage. |
| `mergecraft cache prune` | Evict oldest entries until usage is within the byte ceiling. |
| `mergecraft capabilities` | Print the review-only capability manifest. |
| `mergecraft config explain <key>` | Explain which precedence layer wins for a config key. |
| `mergecraft config set <key> <value>` | Write a supported config key into `.mergecraft/config.yaml`. |
| `mergecraft config show <key>` | Show a resolved config value and the precedence layer that supplied it. |
| `mergecraft config tracing` | Render the resolved tracing config — sinks, retention, redaction, token redacted. |
| `mergecraft config validate` | Strictly parse contributing files and validate their merged configuration. |
| `mergecraft context explain` | Explain why retrieved context was selected for a review. |
| `mergecraft context inspect` | Report sources, scope, provenance citations, and token totals. |
| `mergecraft context search <query>` | Search retrieved review context for a query. |
| `mergecraft describe` | Print a PR title, summary, walkthrough, risk areas, and testing notes. |
| `mergecraft doctor` | Diagnose git, providers, analyzers, auth, config, workflow auth, and MCP wiring. |
| `mergecraft evidence show <finding-id>` | Show the evidence packet for a finding. |
| `mergecraft evidence verify <finding-id>` | Replay verification for a finding's evidence packet (not an approval). |
| `mergecraft explain` | Explain a stored finding or the current working-tree change. |
| `mergecraft findings brief <source>` | Validate and export a fix brief. Never invokes an agent or writes files. |
| `mergecraft findings brief-schema` | Print the machine-readable schema for a fix brief. |
| `mergecraft findings carryover --pr N` | File one issue per unresolved mergeCraft finding. Dry run unless `--apply`. |
| `mergecraft findings export --pr N` | Print the findings a merge would bury. Never writes anything. |
| `mergecraft findings ledger --pr N` | Print the open-PR finding ledger from formal reviews. Never writes. |
| `mergecraft findings outcomes --pr N` | Advisory human outcomes for published mergeCraft findings. |
| `mergecraft gha token` | Acquire a GitHub App installation token, or revoke it with `--post`. |
| `mergecraft health run` | Emit JSON health status for the running mergeCraft installation. |
| `mergecraft init` | Scaffold `.mergecraft/config.yaml` and an example workflow (local, no API). |
| `mergecraft jev disable` | Write `jev.enabled: false` to the committed config. |
| `mergecraft jev enable` | Write `jev.enabled: true`. Prompt for and save `TYPESAFE_API_KEY` when unset. |
| `mergecraft jev set <key> <value>` | Write one Jev parameter, validated through `JevSettings` before writing. |
| `mergecraft jev status` | Show config, credential presence, and effective Jev values. |
| `mergecraft learnings active` | List only the active (promoted) learning entries. |
| `mergecraft learnings influence` | List active + staging learning entries with their provenance. |
| `mergecraft learnings staging` | List only the staging (quarantined) learning entries. |
| `mergecraft lens list` | List bundled lens ids and display titles. |
| `mergecraft lens show <lens-id>` | Show rubric, triggers, evidence, and tool classes for one lens. |
| `mergecraft lens test <lens-id>` | Preview one lens dispatch (rubric + routing context) for a diff fixture. |
| `mergecraft mcp list` | Print the resolved MCP tool names for a role. |
| `mergecraft mcp serve` | Start the MCP server over HTTP or stdio (public role only) for a workspace and role. |
| `mergecraft memory export --output OUTPUT` | Export repo memory to a JSON bundle. |
| `mergecraft memory feedback` | Record accepted / dismissed / disputed feedback for a finding fingerprint. |
| `mergecraft memory forget` | Remove one active memory entry. |
| `mergecraft memory import <bundle-path>` | Import a memory export bundle into a repository. |
| `mergecraft memory list` | List active memory entries for a repository. |
| `mergecraft memory show` | Show one memory entry by id. |
| `mergecraft memory validate` | Validate the repo memory document for structure, staleness, and conflicts. |
| `mergecraft model add <model-id>` | Register a model on a provider in config (env override optional). |
| `mergecraft model delete <provider> <model-id>` | Remove a model from a provider (model index gap is preserved). |
| `mergecraft model list` | List models registered on each provider. |
| `mergecraft models list` | List curated model slugs and whether credentials are detected locally. |
| `mergecraft models set <slugs>` | Write an ordered `models:` list to `.mergecraft/config.yaml`. |
| `mergecraft models show` | Show effective model order, env override, and the slug that would win now. |
| `mergecraft opencode doctor` | Report whether the OpenCode integration is fully wired. |
| `mergecraft opencode install` | Install OpenCode commands, subagents, plugin, and MCP config. |
| `mergecraft plan` | Preview model chain, toolset, analyzers, and token estimate without provider calls. |
| `mergecraft policy effective` | Show the effective policy set and the source of every rule. |
| `mergecraft policy explain --path PATH` | List effective rules for a path and name each rule's source layer. |
| `mergecraft policy lint` | Validate policy rule YAML under `.mergecraft/policy/`. |
| `mergecraft policy simulate` | Simulate a proposed rule against past PRs. |
| `mergecraft policy test --fixtures FIXTURES` | Run should-trigger and should-not policy fixtures. |
| `mergecraft profile recommend --risk RISK` | Print the review profile auto-selected from `--risk`. |
| `mergecraft provider add --label LABEL` | Register a provider in config and allocate an indexed `.env` slot. |
| `mergecraft provider auth` | Authenticate one registered provider into indexed `LLM_PROVIDER_*` secrets. |
| `mergecraft provider delete <label>` | Remove a provider label from config (env index gap is preserved). |
| `mergecraft provider disable <label>` | Clear one provider's credentials so GitHub CI and the local CLI stop using it. |
| `mergecraft provider edit <label>` | Update an existing provider entry in config. |
| `mergecraft provider enable <label>` | Authenticate one provider — the enable half of the toggle. |
| `mergecraft provider harnesses` | List supported agent harnesses (generated from code). |
| `mergecraft provider list` | List registered provider labels. |
| `mergecraft provider migrate` | Migrate legacy `*_API_KEY` env vars into indexed provider registry layout. |
| `mergecraft provider status` | Show the reviewer roster, credentials, wiring, and dispatch order. |
| `mergecraft replay` | Replay a stored review run from local traces (read-only). |
| `mergecraft report <packets>` | Write review metrics from stored evidence packets. |
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
| `mergecraft trust set-agent-sandbox <tier>` | Write `trust.agentSandbox` to the committed config at `--cwd`. |
| `mergecraft trust set-self-review <level>` | Write `trust.selfReview` to the committed config at `--cwd`. |
| `mergecraft trust show` | Show the effective trust policy, level, and resolution source. |
| `mergecraft update` | Reinstall mergecraft at the latest release, keeping installed extras. |
| `mergecraft verify-behavior` | Reproduce a bug or verify acceptance criteria in a running app. |
| `mergecraft version` | Show the mergeCraft package version. |
| `mergecraft watch --pr N` | Stream a PR/issue timeline as one JSON line per new event. |
| `mergecraft workflow agents setmodel --agent AGENT` | Wire an agent's primary model into a mergeCraft workflow step. |
| `mergecraft workflow list` | List provider/model wiring present in mergeCraft workflow steps. |
| `mergecraft workflow model add <model>` | Wire a registered model into `with.model` on a mergeCraft workflow step. |
| `mergecraft workflow model prioritize` | Promote one model ahead of another in the workflow fallback chain. |
| `mergecraft workflow provider add --label LABEL` | Register a provider and wire indexed custom-provider env keys into the workflow. |
| `mergecraft workflow provider harnesses` | List supported agent harnesses (generated from code). |
| `mergecraft workflow sync` | Keep mergecraft.yml auth wiring in sync with the committed agent roster. |
| `mergecraft xrepo explain` | Explain a cross-repo finding, or report producer/consumer contract breakage. |
<!-- END:cli-commands -->

The bare `gha` group invocation (no subcommand) is the Docker action's runtime
entry point — it is a Typer group callback, not a `registered_commands` leaf
itself, so it is described here in prose rather than as its own table row;
`mergecraft gha token` above is the one real leaf command under that group.

## Reports from stored review packets

`mergecraft report` reads packet files or directories of downloaded artifacts and
writes a new JSON file. It runs locally without provider calls:

```sh
mergecraft report ./review-artifacts --output ./review-report.json
```

The output path must not already exist. Directory discovery includes
`*-merge-evidence-packet.json`, `merge-evidence-packet.json`, `run-packet.json`,
and `packet-*.json`; explicit file arguments can use other names. Symlinked
packet files and non-regular files are not read. Invalid packets and non-PR
packets are counted separately.

The three metrics have deliberately narrow definitions:

- `acceptance_rate` is the **review pass rate** among full reviews with a decisive
  success or failure verdict. It does not measure whether a human accepted a
  finding. Neutral outcomes, unknown verdicts, lite reviews, and skips are
  reported separately and excluded from this denominator.
- `cost_per_pr_usd` is the mean sum of recorded reviewer model costs per PR,
  including distinct runs, for PRs whose included non-skip runs all have known
  cost. Partial or unavailable costs remain explicit; they are not treated as
  zero. Estimate and subscription-equivalent qualifications are retained. This
  is recorded reviewer usage, not a provider invoice or a complete accounting of
  every auxiliary model call.
- `time_to_review_seconds` is mean recorded reviewer execution duration for
  measured non-skip runs. It is not the wait between opening a PR and receiving
  its first review, and overlapping analyzer or judge timings are not added.

Sample counts accompany each metric. A metric without observations is `null`.
Copied packets from the same run are deduplicated; conflicting snapshots of one
run are excluded and counted. Older packets without run identity are deduplicated
by content, so identical historical runs cannot be distinguished from copies.
Older packets also lack cost measurements and contribute no invented cost.

Keep separate downloaded artifact directories for the runs you want to compare.
The report describes the files supplied to it; it does not fetch missing history.
Repeated runs written to the same evidence directory can overwrite the previous
packet for that PR.

## Local coverage toolchain

`mergecraft review --with-coverage --shell enabled` uses the `coverage`
executable on `PATH` for both test collection and JSON export. Activate the
consumer project's environment containing coverage, pytest, and its test
dependencies before running a separately installed mergeCraft CLI. If no
`coverage` executable is found, mergeCraft uses the coverage module in its own
Python environment when available. The existing trusted-source and sandbox
requirements still apply; the GitHub Action consumes declared CI evidence
instead of running consumer tests.

## JSON output schema

Every CLI `--json` payload carries a top-level `schema_version` field, currently
`"1.0.0"`. That value is versioned independently of the review snapshot model
and of the agent JSONL protocol: bumping it announces a change to the shape of
CLI JSON output only, and does **not** by itself mean the review snapshot or the
agent wire format changed. The converse also holds — a change to either of those
contracts does not move the CLI stamp.

## Version startup

Standalone `mergecraft --version` and `mergecraft -v` read package/build identity
without loading application settings or repository `.env` files. Build identity
uses the process `MERGECRAFT_BUILD_COMMIT` value first, then baked build metadata,
then the source checkout's Git HEAD. The existing `build_commit` field-name alias
is a fallback only when the uppercase variable is absent or empty. Values are
stripped; a whitespace-only primary value supplies no override. These names are
build provenance, not operator settings to add to `.env`.

## Environment variables

`mergecraft` honours these operator-facing environment variables. Each row names
what the variable bounds, the default it falls back to when unset, and where it
applies. Variables not listed here are internal, generated, or reserved and are
not part of the operator contract.

| Variable | What it bounds | Default | Where it applies |
| --- | --- | --- | --- |
| `MERGECRAFT_AGENT` | Explicit agent harness (`claude`, `codex`, `opencode`, `gemini`, `cursor`); an unknown value falls through to auto-selection | unset — auto-select from credentials and model | local CLI and Action runs |
| `MERGECRAFT_AGENT_TIMEOUT` | Seconds before an agent subprocess is killed | `3600` | every harness invocation and the credential broker |
| `MERGECRAFT_CACHE_DIR` | Run-cache root directory | `~/.cache/mergecraft/run-cache` (honours `XDG_CACHE_HOME`) | CLI runs that use the cache |
| `MERGECRAFT_CACHE_MAX_BYTES` | Byte ceiling for the run cache, in bytes | `536870912` (512 MiB) | cache prune and eviction |
| `MERGECRAFT_CAPTURE_VERDICTS` | Opt-in verifier-verdict capture; `1` appends one redacted line per verdict (including dropped findings) to `judge-verdicts.jsonl` in the run's evidence directory | unset — capture off | offline `mergecraft review --capture-verdicts` and Action review runs |
| `MERGECRAFT_CDP_URL` | Chrome DevTools Protocol base URL for the browser driver | `http://127.0.0.1:9222` | `verify-behavior` browser driver |
| `MERGECRAFT_CONFIG` | Explicit path to the repo config file | unset — discovered at `<repo>/.mergecraft/config.yaml` | config resolution and the `config`/`tracing` commands |
| `MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S` | Seconds allowed for one context-retrieval call | `30` | review context retrieval |
| `MERGECRAFT_COST_BUDGET_USD` | Per-run spend ceiling, in US dollars | `3.0` | budget enforcement (exhaustion maps to inconclusive) |
| `MERGECRAFT_EGRESS_DNS_RESOLVERS` | Comma-separated IPv4 resolvers allowed inside the analyzer network namespace | host `/etc/resolv.conf` nameservers (fallback `1.1.1.1`) | isolated analyzers |
| `MERGECRAFT_ENV` | Explicit path to the `.env` file loaded at CLI startup | unset — git-root `.env`, skipped inside GitHub Actions | CLI startup and credential writers |
| `MERGECRAFT_EVIDENCE_DIR` | Parent directory for the emitted evidence packet and the captured `judge-verdicts.jsonl` | unset — `$RUNNER_TEMP/mergecraft`, else the run temp dir | review evidence-packet emission |
| `MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S` | Upper bound, in seconds, applied to every registered external operation | `600` | external I/O within a run |
| `MERGECRAFT_KEEP_TMP` | Any non-empty value keeps all of the offline review's `mergecraft-diff-review-*` temp directory, including the scratch (materialized diff, prompts, agent home) | unset — the scratch is removed when the process exits; the `evidence/` subdirectory (evidence packet, Jev shadow log, `--capture-verdicts` output) and `jev-shadow.jsonl` are kept | local and offline review |
| `MERGECRAFT_LOG_FORMAT` | Log sink format: `json` or `text` | `text` | CLI and Action logging |
| `MERGECRAFT_LOG_LEVEL` | Loguru level name (`TRACE` through `CRITICAL`) | unset — `INFO`, or `DEBUG` under `ACTIONS_STEP_DEBUG` / `--verbose` | CLI logging |
| `MERGECRAFT_MAX_DIFF_LINES` | Diff line ceiling before scope reduction is recorded | `50000` | review diff loading |
| `MERGECRAFT_MODEL` | Model slug override; wins over the config `models:` list | unset — the first configured model | model resolution |
| `MERGECRAFT_AGENTS_SDK_MODEL` | Default `provider/model` slug for `mergecraft.agents_sdk.review_agent` when using the optional `[agents]` extra | unset — `gpt-4o-mini` with `OPENAI_API_KEY`, or `opencode-go/deepseek-v4.1-flash` with `OPENCODE_GO_API_KEY` | OpenAI Agents SDK integration |
| `MERGECRAFT_NONINTERACTIVE` | Truthy disables interactive prompts | unset — prompts when stdin is a TTY | CLI interactive commands |
| `MERGECRAFT_OPENCODE_OTEL_PLUGIN` | Package path or spec of [opencode-plugin-otel-v2](https://github.com/alexhawat/opencode-plugin-otel-v2); when set and tracing exports to `otel` or `logfire`, OpenCode 2.x runs emit per-LLM-step and per-tool spans into the review's trace | unset — not loaded | OpenCode tracing |
| `MERGECRAFT_OTEL_ENDPOINT` | OTLP/HTTP endpoint for the `otel` tracing sink; setting it implies OTLP when no destination is chosen | unset | tracing sink resolution |
| `MERGECRAFT_RUN_TIMEOUT_S` | Whole-run wall-clock ceiling, in seconds | `3600` | run bounds |
| `MERGECRAFT_TEMP_DIR` | Run temp directory override | unset — the run's own temp dir, else `/tmp` | checkout, MCP shell, git, and agent seams |
| `MERGECRAFT_TEMP_PARENT` | Preferred parent directory for created temp dirs (avoids world-writable `/tmp`) | unset — `$RUNNER_TEMP`, else `~/.cache/mergecraft/tmp` | temp-dir creation |
| `MERGECRAFT_TOKEN_BUDGET` | Advisory per-run token target | `2000000` | usage reporting; overages do not fail the review or stop later reviewers (scaled by `review.roundBudgets`) |
| `MERGECRAFT_TOOL_CALL_BUDGET` | Per-run tool-call ceiling | `500` | budget enforcement (scaled by `review.roundBudgets`) |
| `MERGECRAFT_TRACE_DIR` | Directory for local JSONL traces | `.mergecraft/traces` | tracing and the `replay`/`run inspect` commands |
| `MERGECRAFT_TRACING` | Boolean toggle for tracing | unset — disabled unless config enables it | tracing resolution |
| `MERGECRAFT_TRACING_CONTENT` | Payload capture level: `off`, `metadata`, `redacted`, or `full` | `redacted` | agent and tool span capture |
| `MERGECRAFT_TRACING_PROJECT` | Logfire project label written alongside the Logfire write token | unset | Logfire tracing |
| `MERGECRAFT_TRACING_REGION` | Logfire OTLP region: `us` or `eu` | `us` | Logfire tracing |
| `MERGECRAFT_TRACING_TO` | Tracing destination: `local_files`, `otel`, or `logfire` | unset — JSONL file sink when tracing is on | tracing sink resolution |

### Control switches

Two switches weaken a control. Each is honoured only when set to the exact string
`1` (`true` or `yes` does nothing), and the error that refuses the action names the
switch that overrides it. Leave both unset unless you are on a disposable machine.

| Variable | What it allows | Default |
| --- | --- | --- |
| `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL` | `--shell enabled` runs even when no sandbox backend is available | unset — the run refuses |
| `MERGECRAFT_ALLOW_ROOT` | Running as root outside the mergeCraft Action image, for local development | unset — the run refuses |

## See also

- [Action reference](action-reference.md)
- [Exit codes](EXIT-CODES.md)
- [Landing README](../README.md)
