# Tools by capability tier

## Table of contents

1. [Tier 1 — mergeCraft MCP](#tier-1--mergecraft-mcp)
2. [Tier 2 — Copilot / hosted review](#tier-2--copilot--hosted-review)
3. [Tier 3 — bare agent](#tier-3--bare-agent)
4. [Withdrawn findings path](#withdrawn-findings-path)

One skill serves all three tiers. Degrade steps explicitly; never pretend a tier
can do what it cannot.

## Tier 1 — mergeCraft MCP

Full review loop with typed findings and server-side validation.

### Establish scope

| Step | Tool |
| --- | --- |
| Checkout PR / materialize diff | `mcp__mergecraft__checkout_pr` |

Read `diffPath` end-to-end. When `scope: "api-only"`, the diff is authoritative;
use `git show <base>:path` for context — do not claim head file reads you lack.

### Collect evidence

| Step | Tool |
| --- | --- |
| Repo mechanical gates | `mcp__mergecraft__run_static_checks` |
| Catalog analyzers | `mcp__mergecraft__run_analyzers` |
| CI failure clustering | `mcp__mergecraft__analyze_ci_failures` |
| Lens registry | `mergecraft lens list` (CLI; not MCP) |

Pass changed paths from the diff. Treat only `failed` gates and verified analyzer
rows as automatic findings.

### Verify before publish

| Step | Tool |
| --- | --- |
| Dispatch verifier briefs | `mcp__mergecraft__verify_agent_findings` |
| Record confirm/downgrade/drop | `mcp__mergecraft__record_finding_verdict` |

Apply to **your own** Critical/Major findings and to analyzer/CI hits at the same
severity. A `drop` writes to withdrawn findings (see below).

### Terminal verdict

Call **`mcp__mergecraft__submit_review_verdict`** exactly once with:

```json
{
  "verdict": "approve",
  "summary": "…",
  "findings": []
}
```

Allowed top-level keys: `verdict`, `summary`, `findings` only.

| Field | Type | Notes |
| --- | --- | --- |
| `verdict` | `"approve"` \| `"request_changes"` | required |
| `summary` | string | required; human-readable outcome |
| `findings` | array | required; may be empty only for `approve` |

**Rejections (enforced):**

- `request_changes` with zero findings;
- `approve` with a verifier-confirmed Critical/Major blocker;
- `approve` while a required deterministic gate failed;
- unknown top-level keys.

Each finding object carries category, severity, effort, confidence, path, line
range, body, and evidence — matching the six-field contract in `SKILL.md` §5.

**Silence path:** `approve` + empty `findings` + summary stating scope read, gates
run, and nothing actionable survived the filter.

## Tier 2 — Copilot / hosted review

No mergeCraft MCP surface. Host provides the diff and review UI only.

| MCP step | Degradation |
| --- | --- |
| `checkout_pr` | Use the PR diff the host already shows |
| `run_static_checks` / `run_analyzers` | Run `make lint`, `make typecheck`, scoped tests locally when shell exists; otherwise note gates not run |
| `analyze_ci_failures` | Read failing CI logs from the Checks tab |
| `verify_agent_findings` | Re-read cited lines yourself; state confidence honestly |
| `submit_review_verdict` | Post Approve or Request changes via the host; mirror summary + inline comments |

Keep inline comments tagged with category, severity, and effort. Put Trivial and
Low value items in a single Nitpicks comment. Do not invent structured fields the
host cannot store — make prose self-contained.

## Tier 3 — bare agent

File and shell access only; no mergeCraft server.

1. Read the diff artifact and touched files directly.
2. Run repo gates when permitted (`make …` targets).
3. Draft findings with the six fields from `SKILL.md` §5.
4. End with an explicit **Approve** or **Request changes** recommendation.

List gates you could not run. Never fabricate tool output. Silence still requires
an explicit approve with rationale.

## Withdrawn findings path

When a finding is refuted — by the author, by you after re-read, or by the
verifier — the reason lands under:

`## Withdrawn review findings (known non-issues)`

in `.mergecraft/learnings.md` (loaded every run).

- **Tier 1:** `mcp__mergecraft__record_finding_verdict` with action `drop` appends
  the reason with the finding fingerprint.
- **Tier 2 / 3:** tell the author to record the withdrawal in learnings if the
  repo uses mergeCraft memory; do not re-raise the same claim on a later review.

Read this section during evidence collection (§2), not after drafting findings.
