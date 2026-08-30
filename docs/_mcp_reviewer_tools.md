# Runtime reviewer MCP tools (`/mcp/reviewer`)

Hand-maintained section appended to [`mcp-tools.md`](mcp-tools.md) by
`scripts/gen_mcp_server_json.py`. Documents the **in-run reviewer harness**
served at `mergecraft mcp serve` (role `reviewer`, Bearer on HTTP). Not part of
the six-tool **public** profile above.

Install surface: [`docs/mcp.md`](mcp.md) (runtime harness vs public stdio).

## Git tool — read-only verbs and guards (W2 / W3)

The `git` MCP tool (`ToolClass.REPOSITORY_READ`) enforces fail-closed restrictions
regardless of `payload.shell`. Full guard tables:
[`config-failure-policy.md` — MCP git tool](config-failure-policy.md#mcp-git-tool--reviewer-surface-enforcement-257--d7).

**Added read-only subcommands (W3):**

| Subcommand | Typical use |
|------------|-------------|
| `show-ref` | List refs without mutating |
| `for-each-ref` | Structured ref listing |
| `ls-remote` | Remote refs when fetch is blocked |
| `config` | **Lookup only** — `--get`, `--get-all` (credential-bearing keys denied) |

Credential-bearing `config` keys (`credential.*`, `url.*`) are refused. Writes
(`--set`, `--unset`, …) are refused.

**Containment hardening (W2):**

| Guard | Behaviour |
|-------|-----------|
| `--no-index` | Refused outright — operates outside a repository |
| Positional paths | Confined to workspace roots (same primitive as `-C` / `--git-dir`) |
| Credential paths | `.git/config`, `.git/credentials`, askpass tree unreadable even inside the repo |
| Failure text | `RuntimeError` bodies from `_run_git` pass through `redact_secrets` |

Redirects for mutating verbs: `push` → `push_branch`, `fetch` → `git_fetch`,
`clone` → `checkout_repo` / `checkout_pr`.

## `establish_review_scope`

Second evidence-backed route into review scope (D4) when `checkout_pr` cannot
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

## `checkout_pr` — degraded `api-only` scope (W4 / D1–D2)

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
when findings warrant it (D2) — transport failure is not an automatic merge block.

Auth-class fetch failures degrade immediately with **no retry** (D3). Transient
failures may retry once before degradation.

## Parameter aliases (W3)

`checkout_pr` accepts `pull_number`, `pr_number`, and `issue_number` as aliases
for the PR number parameter.
