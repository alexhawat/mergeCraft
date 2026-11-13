# Runtime reviewer MCP tools (`/mcp/reviewer`)

Hand-maintained section appended to [`mcp-tools.md`](mcp-tools.md) by
`scripts/gen_mcp_server_json.py`. Documents the **in-run reviewer harness**
served at `mergecraft mcp serve` (role `reviewer`, Bearer on HTTP). Not part of
the six-tool **public** profile above.

Install surface: [`docs/mcp.md`](mcp.md) (runtime harness vs public stdio).

## Execution deadlines and concurrency

Checkout, analyzers, static checks, and foreground shell commands run blocking
work in worker threads, keeping the MCP event loop available to other requests.
Each declared tool timeout is enforced at RPC dispatch. Expiry requests
cancellation and returns JSON-RPC error `-32000` after cleanup, with the tool name
and timeout in milliseconds. Client cancellation remains cancellation.

Cancellation stops only that operation's registered process groups, including
nested analyzer workers. Cleanup joins the worker before tool state is reused;
late worker results cannot become successful tool results. Noninterruptible
synchronous filesystem or network I/O must finish or reach its own timeout before
cleanup returns, so the response may arrive after the declared deadline. Analyzer
downloads check cancellation between redirects and chunks (individual HTTP I/O
has a 120-second timeout), and cache-lock waits check cancellation while waiting.
Analyzer calls from independent contexts use separate scratch and artifact
directories. Checkout, analyzer, and static-check operations sharing a tool state
are serialized until the prior operation and its cancellation cleanup finish;
unrelated requests remain responsive.

## Git tool — read-only verbs and guards

The `git` MCP tool (`ToolClass.REPOSITORY_READ`) enforces fail-closed restrictions
regardless of `payload.shell`. Full guard tables:
[`config-failure-policy.md` — MCP git tool](config-failure-policy.md#mcp-git-tool--reviewer-surface-enforcement).

**Added read-only subcommands:**

| Subcommand | Typical use |
|------------|-------------|
| `show-ref` | List refs without mutating |
| `for-each-ref` | Structured ref listing |
| `ls-remote` | Remote refs when fetch is blocked |
| `config` | **Lookup only** — `--get`, `--get-all` (credential-bearing keys denied) |

Read-only `git` calls have a 120-second RPC deadline. Each Git subprocess captures
at most 20 MiB of combined stdout and stderr; exceeding the limit kills its process
group and refuses the partial output. Refused output is never cached. `git show`
resolves a blob's object ID and type in one query; symbolic refs are resolved again
on each call so an external ref move cannot return stale cached content.

Credential-bearing `config` keys (`credential.*`, `url.*`) are refused. Writes
(`--set`, `--unset`, …) are refused.

**Containment hardening:**

| Guard | Behaviour |
|-------|-----------|
| `--no-index` | Refused outright — operates outside a repository |
| Positional paths | Confined to workspace roots (same primitive as `-C` / `--git-dir`) |
| Credential paths | `.git/config`, `.git/credentials`, askpass tree unreadable even inside the repo |
| Failure text | `RuntimeError` bodies from `_run_git` pass through `redact_secrets` |

`push` is refused because repository mutation is unavailable in review-only
runs. Use `git_fetch` to read remote refs and `checkout_repo` / `checkout_pr`
for bounded checkout operations; `pull` cannot merge changes.

## `establish_review_scope`

Second evidence-backed route into review scope when `checkout_pr` cannot
fetch the head but a materialized diff already exists — e.g. from `get_commit_info`
at PR head.

**Input:**

| Field | Required | Meaning |
|-------|----------|---------|
| `diff_path` | yes | Path to a non-empty unified diff on disk |
| `base_sha` | yes | Base commit for the change (informational in the response) |
| `head_sha` | yes | Must match the PR head SHA from the GitHub API |

**Validation (fail closed):**

- File exists and looks like a unified diff.
- `head_sha` matches the API head for this PR — fabricated scope is refused.

**Success payload:**

```json
{
  "diffPath": "/tmp/pr-42.diff",
  "headSha": "abc123…",
  "baseSha": "def456…",
  "provenance": "local-diff",
  "reviewPhase": "ESTABLISH_SCOPE"
}
```

Also accepted scope paths: `checkout_pr` (full or degraded), `get_commit_info`
when SHA equals PR head, offline `establish_offline_review_scope`.

## `checkout_pr` — degraded `api-only` scope

When the PR head **cannot be fetched** (dead remote, auth-class failure after
classification, etc.), `checkout_pr` **does not fail the run**. It builds the
diff from `GET /repos/…/pulls/N/files`, writes `pr-<N>.diff` under the run
temp dir, and registers scope as `api-only`.

**Degraded success payload (representative):**

```json
{
  "pullNumber": 42,
  "remoteBranch": "feature/foo",
  "base": "main",
  "headSha": "abc123…",
  "checkoutSha": "abc123…",
  "isFork": false,
  "diffPath": "/tmp/pr-42.diff",
  "title": "…",
  "url": "https://github.com/…/pull/42",
  "scope": "api-only",
  "degraded": "PR head could not be fetched locally (…); review scope is api-only — …",
  "reviewPhase": "ESTABLISH_SCOPE"
}
```

| Field | Meaning |
|-------|---------|
| `scope` | `"api-only"` — diff from the API is authoritative; head-side file reads around the diff are unavailable |
| `degraded` | Human-readable reason — include in run health / operator logs |
| `diffPath` | Unified diff file the agent must treat as the change under review |

**Operator guidance for agents:** use `git show <base>:path` and the diff; do
not claim to have read a head-only file. A degraded review **may still APPROVE**
when findings warrant it — transport failure is not an automatic merge block.

Auth-class fetch failures degrade immediately with **no retry**. Transient
failures may retry once before degradation.

## Parameter aliases

`checkout_pr` accepts `pull_number`, `pr_number`, and `issue_number` as aliases
for the PR number parameter.
