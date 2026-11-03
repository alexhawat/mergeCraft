# mergeCraft CLI — real-world test plan and agent run-book

Date: 2026-11-03. Target: `mergecraft` CLI at commit `3000d1c` (version `0.1.0a4`).
Companion document: [`plans/cli-review-2026-11-03.md`](cli-review-2026-11-03.md).

This file has two audiences:

- **Section 1 is for Alex (human).** Create `test-cli.env`, obtain credentials, decide
  budgets, and create the testbed repository (or let the agent do it with a token that
  has `repo` scope).
- **Sections 2–7 are for the AI agent** that executes the tests. The agent reads this
  file top to bottom, runs every test in Section 5 that its credentials allow, and fills
  the report template in Section 7. Tests with missing prerequisites are reported as
  `SKIPPED (reason)`, never silently dropped.

Nothing in this plan is executed by the mergeCraft repo's own CI. It is a manual,
credential-bearing campaign against real providers. Expect to spend money.

---

## 1. Human setup

### 1.1 Prerequisites on the test machine

| Tool | Why | Check |
|------|-----|-------|
| Python 3.11+ and `uv` | runs the CLI from the checkout | `uv --version` |
| `git` 2.40+ | diff selection, worktrees | `git --version` |
| `gh` CLI, logged in with a token that can read the testbed and write its secrets | `auth`/`provider auth --scope github`, `findings`, `watch`, `--repo owner/repo` | `gh auth status` |
| Node 22 + the harness CLIs | `review` shells out to `claude`, `codex`, `gemini`, `opencode` binaries; the Docker image pins them in `docker/agent-clis/package.json` | see 1.2 |
| Docker (optional) | Section 5.M Action-parity test | `docker version` |
| `jq` | result extraction in the scripts below | `jq --version` |

### 1.2 Install the harness CLIs at the pinned versions

```bash
cd /path/to/mergeCraft
(cd docker/agent-clis && npm ci)                 # installs the four pinned CLIs
export PATH="$PWD/docker/agent-clis/node_modules/.bin:$PATH"
claude --version; codex --version; gemini --version; opencode --version
```

Cursor's `cursor-agent` is not in that lockfile. Install it per Cursor's docs only if you
intend to test the `cursor` harness.

### 1.3 Create `test-cli.env`

Create the file at the mergeCraft checkout root as `test-cli.env`. It is listed in
`.gitignore`. **Never** commit it, paste it into an issue, or let the agent print it.
Leave any line empty that you do not have; the agent skips the matching tests.

```bash
# ===================== test-cli.env =====================
# Loaded by the agent with:  set -a; source test-cli.env; set +a
# All names below are the exact names the CLI reads (see docs/authentication.md).

# ---- Testbed repository ----
TESTBED_REPO=                 # owner/mergecraft-cli-testbed (created in 1.4)
TESTBED_CLONE_DIR=            # absolute path where the agent may clone it, e.g. /tmp/testbed
GH_TOKEN=                     # GitHub token with repo scope on TESTBED_REPO (read PRs, write secrets)
GITHUB_TOKEN=                 # same value as GH_TOKEN (some paths read this name)

# ---- Budgets and stop rules (the agent must honour these) ----
TEST_MAX_SPEND_USD=25         # agent stops starting new live reviews once the running estimate passes this
TEST_REVIEW_TIMEOUT_MIN=15    # per-review wall clock (passed as `timeout`)
TEST_PARALLEL=1               # run live reviews serially unless you raise this

# ---- Native harness credentials (one per harness) ----
ANTHROPIC_API_KEY=            # claude harness (API key)   -> anthropic/claude-*
CLAUDE_CODE_OAUTH_TOKEN=      # claude harness (subscription, from `mergecraft auth claude`)
OPENAI_API_KEY=               # codex harness (API key)    -> openai/gpt-*
CODEX_AUTH_JSON=              # codex harness (subscription, from `mergecraft auth codex`)
GEMINI_API_KEY=               # gemini harness             -> google/gemini-*
CURSOR_API_KEY=               # cursor harness             -> cursor models

# ---- OpenCode harness (any OpenAI-compatible endpoint) ----
OPENCODE_GO_API_KEY=          # opencode-go/* (what this repo's own CI uses)
OPENCODE_API_KEY=             # opencode/* (OpenCode Zen)
OPENCODE_AUTH_JSON=           # alternative to OPENCODE_API_KEY (from `mergecraft auth opencode`)
OPENROUTER_API_KEY=           # openrouter/* — registered via `provider add --label openrouter`
DEEPSEEK_API_KEY=             # deepseek/*   — registered via `provider add --label deepseek`
TOKENHUB_API_KEY=             # tokenhub/*   — `mergecraft auth tokenhub`
MINIMAX_API_KEY=              # minimax/*    — written by `mergecraft auth minimax` as MERGECRAFT_CUSTOM_PROVIDER_API_KEY
MINIMAX_BASE_URL=https://api.minimax.io/v1

# ---- Deliberately broken credentials for fallback tests (Section 5.D) ----
# Keep these syntactically plausible but invalid. Do NOT reuse a real key.
BAD_API_KEY=sk-invalid-0000000000000000
BAD_BASE_URL=https://127.0.0.1:9/v1

# ---- Optional integrations ----
MERGECRAFT_LOGFIRE_TOKEN=     # Logfire write token (tracing tests 5.I)
MERGECRAFT_TRACING_PROJECT=   # Logfire project label
TYPESAFE_API_KEY=             # Jev advisory gate (5.H)

# ---- Model slugs to use per provider (edit if a slug is retired; `mergecraft models list`) ----
SLUG_ANTHROPIC=anthropic/claude-sonnet
SLUG_OPENAI=openai/gpt-codex-mini
SLUG_GOOGLE=google/gemini-flash
SLUG_CURSOR=cursor/auto
SLUG_OPENCODE_GO=opencode-go/deepseek-v4.1-flash
SLUG_OPENCODE=opencode/gpt-5-nano
SLUG_OPENROUTER=openrouter/deepseek-flash
SLUG_DEEPSEEK=deepseek/deepseek-flash
SLUG_TOKENHUB=tokenhub/hy3
SLUG_MINIMAX=minimax/MiniMax-M3
# ===================== end =====================
```

Notes for Alex:

- `mergecraft auth codex` and `mergecraft auth claude` perform an interactive browser
  login and write `CODEX_AUTH_JSON` / `CLAUDE_CODE_OAUTH_TOKEN`. Run them once yourself with
  `--scope local` inside a scratch clone, then copy the values into `test-cli.env`. The
  agent cannot complete a browser login.
- `GH_TOKEN` is used both by `gh` and by `mergecraft review --repo owner/repo` for private
  clones. A fine-grained token scoped to the testbed with Contents: read, Pull requests:
  read/write, Secrets: write, Issues: write (for `findings carryover --apply`) is enough.
- Cheap models are chosen on purpose. The point is plumbing, not review quality.

### 1.4 Create the testbed repository

This session's GitHub access was scoped to `alexhawat/mergeCraft` only, so the testbed was
**not** created here. Run the script below once (needs `gh` logged in as the owner). It
creates a private repo with a small Python service, plants bugs on branches, and opens
one PR per scenario. Every PR targets `main`. The planted defects are listed so the agent
can judge findings against ground truth.

```bash
#!/usr/bin/env bash
# create-testbed.sh — run from anywhere; needs gh, git, python3
set -euo pipefail
OWNER="${1:?usage: create-testbed.sh <github-owner>}"
REPO="mergecraft-cli-testbed"
WORK="$(mktemp -d)"
cd "$WORK"
gh repo create "$OWNER/$REPO" --private --description "mergeCraft CLI testbed (planted bugs)" --clone
cd "$REPO"
git checkout -b main 2>/dev/null || git checkout main

mkdir -p svc tests
cat > README.md <<'MD'
# testbed service
Tiny inventory API used as a mergeCraft CLI test target. Every branch named `pr/*`
plants a specific defect; see PR descriptions.
MD
cat > pyproject.toml <<'TOML'
[project]
name = "testbed-svc"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["fastapi==0.141.1", "httpx==0.28.1"]
[tool.ruff]
line-length = 100
TOML
cat > svc/__init__.py <<'PY'
PY
cat > svc/db.py <<'PY'
import sqlite3
from contextlib import contextmanager

@contextmanager
def connect(path: str = "inventory.db"):
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def find_item(conn, item_id: int):
    cur = conn.execute("SELECT id, name, qty FROM items WHERE id = ?", (item_id,))
    return cur.fetchone()

def list_items(conn, limit: int = 50):
    cur = conn.execute("SELECT id, name, qty FROM items ORDER BY id LIMIT ?", (limit,))
    return cur.fetchall()
PY
cat > svc/pricing.py <<'PY'
from decimal import Decimal

TIERS = [(0, Decimal("1.00")), (10, Decimal("0.95")), (100, Decimal("0.90"))]

def unit_price(base: Decimal, qty: int) -> Decimal:
    factor = Decimal("1.00")
    for threshold, f in TIERS:
        if qty >= threshold:
            factor = f
    return (base * factor).quantize(Decimal("0.01"))

def total(base: Decimal, qty: int) -> Decimal:
    return unit_price(base, qty) * qty
PY
cat > svc/api.py <<'PY'
from fastapi import FastAPI, HTTPException
from svc import db

app = FastAPI()

@app.get("/items/{item_id}")
def get_item(item_id: int):
    with db.connect() as conn:
        row = db.find_item(conn, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"id": row[0], "name": row[1], "qty": row[2]}

@app.get("/items")
def get_items(limit: int = 50):
    with db.connect() as conn:
        return [dict(id=r[0], name=r[1], qty=r[2]) for r in db.list_items(conn, limit)]
PY
cat > tests/test_pricing.py <<'PY'
from decimal import Decimal
from svc.pricing import unit_price, total

def test_tiers():
    assert unit_price(Decimal("10"), 1) == Decimal("10.00")
    assert unit_price(Decimal("10"), 10) == Decimal("9.50")
    assert unit_price(Decimal("10"), 100) == Decimal("9.00")

def test_total():
    assert total(Decimal("10"), 3) == Decimal("30.00")
PY
cat > requirements.lock <<'LOCK'
fastapi==0.141.1
httpx==0.28.1
LOCK
printf 'inventory.db\n__pycache__/\n.mergecraft/config.local.yaml\n.env\n' > .gitignore
git add -A && git commit -qm "seed: inventory service"
git push -u origin main

mkpr () { # name, title, body
  git push -u origin "$1" >/dev/null
  gh pr create --base main --head "$1" --title "$2" --body "$3" >/dev/null
  echo "PR created: $1"
  git checkout -q main
}

# PR 1 — docs only. Ground truth: no code finding; fast-path prose candidate.
git checkout -qb pr/01-docs-only
printf '\n## Running\n\n    uvicorn svc.api:app\n' >> README.md
git commit -qam "docs: how to run"
mkpr pr/01-docs-only "docs: how to run" "Docs only. Expected: no blocking findings."

# PR 2 — SQL injection. Ground truth: blocking security finding in svc/db.py.
git checkout -qb pr/02-sql-injection
python3 - <<'PY'
import re,io
p="svc/db.py"; s=open(p).read()
s=s.replace('cur = conn.execute("SELECT id, name, qty FROM items WHERE id = ?", (item_id,))',
            'cur = conn.execute(f"SELECT id, name, qty FROM items WHERE id = {item_id}")')
s+='\n\ndef search(conn, name: str):\n    return conn.execute("SELECT * FROM items WHERE name LIKE \'%" + name + "%\'").fetchall()\n'
open(p,"w").write(s)
PY
git commit -qam "feat: add search endpoint helper"
mkpr pr/02-sql-injection "feat: search helper" "Planted: string-formatted SQL in find_item and search. Expected: blocking finding."

# PR 3 — subtle logic bug. Ground truth: off-by-one tier boundary + swallowed exception.
git checkout -qb pr/03-subtle-bug
python3 - <<'PY'
p="svc/pricing.py"; s=open(p).read()
s=s.replace("if qty >= threshold:","if qty > threshold:")
open(p,"w").write(s)
p="svc/api.py"; s=open(p).read()
s=s.replace("""    with db.connect() as conn:
        row = db.find_item(conn, item_id)
""","""    try:
        with db.connect() as conn:
            row = db.find_item(conn, item_id)
    except Exception:
        row = None
""")
open(p,"w").write(s)
PY
git commit -qam "refactor: tier boundary and error handling"
mkpr pr/03-subtle-bug "refactor: tier boundary" "Planted: qty>threshold breaks the 10/100 boundaries (tests now fail); bare except hides DB errors as 404. Expected: at least one finding; test_tiers fails."

# PR 4 — secret leak. Ground truth: hard-coded credential; must be redacted in traces.
git checkout -qb pr/04-secret-leak
cat > svc/settings.py <<'PY'
# TODO move to env
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
DATABASE_URL = "postgres://admin:hunter2@db.internal:5432/inventory"
PY
git add svc/settings.py && git commit -qm "chore: add settings"
mkpr pr/04-secret-leak "chore: settings module" "Planted: hard-coded AWS example keys and a DB password. Expected: blocking finding; the literal values must not appear in traces or evidence packets."

# PR 5 — lockfile only. Ground truth: ignored by default ignore_paths -> nothing to review.
git checkout -qb pr/05-lockfile-only
printf 'anyio==4.15.1\n' >> requirements.lock
git commit -qam "chore: lock anyio"
mkpr pr/05-lockfile-only "chore: lock anyio" "Lockfile only. Expected: 'nothing to review' path, exit 0, no approval claimed."

# PR 6 — large diff (coverage / truncation behaviour).
git checkout -qb pr/06-large-diff
mkdir -p svc/gen
for i in $(seq 1 40); do
  python3 - "$i" <<'PY'
import sys; i=int(sys.argv[1])
body="\n".join(f"def f{i}_{j}(x):\n    return x + {j}\n" for j in range(60))
open(f"svc/gen/mod{i:02d}.py","w").write(body)
PY
done
git add svc/gen && git commit -qm "feat: generated helpers"
mkpr pr/06-large-diff "feat: generated helpers" "~2400 added functions across 40 files. Expected: review completes within budget; evidence packet coverage section reports truncation honestly if any."

# PR 7 — mixed: lockfile + real bug (ignore_paths must not hide the bug).
git checkout -qb pr/07-mixed-ignored
printf 'certifi==2026.1.1\n' >> requirements.lock
python3 - <<'PY'
p="svc/db.py"; s=open(p).read()
s=s.replace("def list_items(conn, limit: int = 50):","def list_items(conn, limit: int = 50):\n    limit = int(limit) * 1000  # oops")
open(p,"w").write(s)
PY
git commit -qam "chore: bump certifi; tweak list limit"
mkpr pr/07-mixed-ignored "chore: bump certifi" "Lockfile change plus a planted limit multiplier. Expected: lockfile listed as ignored, db.py still reviewed with a finding."

# PR 8 — rename + modify.
git checkout -qb pr/08-rename
git mv svc/pricing.py svc/price_rules.py
sed -i 's/from svc.pricing import/from svc.price_rules import/' tests/test_pricing.py
printf '\n\ndef discount_code(code: str) -> Decimal:\n    return Decimal(code)  # accepts any string\n' >> svc/price_rules.py
git commit -qam "refactor: rename pricing module"
mkpr pr/08-rename "refactor: rename pricing" "Rename with an added unsafe Decimal(code) parse. Expected: rename handled (both paths), finding on the new function."

# PR 9 — binary + non-UTF8 file.
git checkout -qb pr/09-binary
head -c 20000 /dev/urandom > assets.bin
printf '\xff\xfe\x00bad utf8\n' > notes.txt
git add assets.bin notes.txt && git commit -qm "chore: add assets"
mkpr pr/09-binary "chore: add assets" "Binary and non-UTF-8 content. Expected: no crash; files reported as not reviewable."

# PR 10 — a PR whose head branch will be deleted (stale ref) is created last by the agent if needed.
echo "Done. Repo: https://github.com/$OWNER/$REPO"
gh pr list --repo "$OWNER/$REPO" --json number,headRefName,title
```

After running it, fill `TESTBED_REPO` and `TESTBED_CLONE_DIR` in `test-cli.env`. The PR
numbers are 1–9 in creation order; the agent re-reads them with `gh pr list` rather than
assuming.

### 1.5 Hand-off

Give the agent: the mergeCraft checkout, `test-cli.env`, and this file. Tell it which
sections to run if you want less than everything (default: all of Section 5).

---

## 2. Agent ground rules

1. **Load the env once per shell.** `set -a; source test-cli.env; set +a`. Never `cat`
   the file, never echo a variable whose name ends in `_KEY`, `_TOKEN`, `_JSON`. When a
   command prints a credential-looking value, record `REDACTED` and flag it as a finding
   (that is itself a bug in the CLI).
2. **Run the CLI from the checkout**: `uv run mergecraft …`. Prefix every command with
   `timeout "${TEST_REVIEW_TIMEOUT_MIN}m"` for live reviews and `timeout 120` for the rest.
   Always set `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1`.
3. **Work in a fresh clone of the testbed per section** (`git clone` into
   `$TESTBED_CLONE_DIR/<section>`), so `.env`, `.mergecraft/config.local.yaml` and the
   workflow edits of one section cannot leak into the next. Point `MERGECRAFT_ENV` at a
   per-section copy of `test-cli.env` when a test expects the CLI to *write* credentials
   (`auth`, `provider auth --scope local`); otherwise leave it unset so the CLI reads the
   clone's own `.env`.
4. **Never touch `alexhawat/mergeCraft` on GitHub.** All `--repo`, `gh secret set`,
   `findings carryover --apply`, workflow edits and pushes go to `$TESTBED_REPO` only.
5. **Budget.** Keep a running estimate: each live review on a cheap model is roughly
   USD 0.02–0.30; the large-diff PR can be USD 1–3 on a frontier model. Stop starting
   live reviews when the estimate reaches `TEST_MAX_SPEND_USD` and mark the rest
   `SKIPPED (budget)`.
6. **Record everything** in `results/<YYYY-MM-DD>/` inside the mergeCraft checkout (git
   ignored by you: add it to `.git/info/exclude`). One directory per test id with
   `cmd.txt`, `exit_code.txt`, `stdout.txt`, `stderr.txt`, `duration_s.txt`, plus any
   `--json`/`--evidence-packet` outputs. The final report is Section 7.
7. **Exit codes have meaning** (`docs/EXIT-CODES.md`): 0 pass, 10 non-blocking findings,
   11 blocking findings, 12 failed, 20 inconclusive, 30 configuration error, 40 infra /
   credential error, 50 timeout, 2 usage error. A traceback on stderr is always a FAIL
   regardless of exit code.
8. **Judge, don't just run.** For each review test compare the findings with the PR's
   planted defect (Section 1.4) and record: planted defect found? (yes/partial/no),
   false positives count, finding has file+line?, severity reasonable?

Helper used throughout:

```bash
run () { # run <test-id> <cmd...>   — records everything under results/
  local id="$1"; shift
  local dir="results/$(date +%F)/$id"; mkdir -p "$dir"
  printf '%q ' "$@" > "$dir/cmd.txt"
  local start=$(date +%s)
  ( "$@" ) >"$dir/stdout.txt" 2>"$dir/stderr.txt"; local rc=$?
  echo $rc > "$dir/exit_code.txt"; echo $(( $(date +%s) - start )) > "$dir/duration_s.txt"
  if grep -q "Traceback (most recent call last)" "$dir/stderr.txt"; then echo "TRACEBACK" > "$dir/FAIL"; fi
  echo "[$id] rc=$rc $(cat "$dir/duration_s.txt")s"
  return 0
}
mc () { _TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1 uv run mergecraft "$@"; }
```

---

## 3. Provider matrix

The CLI has five harnesses. Each provider below maps to exactly one harness; the harness
binary must be on `PATH` (1.2). "Setup" is what the agent runs in the clone before the
first review with that provider; everything else comes from the env.

| ID | Provider / slug env | Harness | Credential env read at run time | Setup in clone |
|----|---------------------|---------|----------------------------------|----------------|
| P1 | `$SLUG_ANTHROPIC` | claude | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` | none (built-in) |
| P2 | `$SLUG_OPENAI` | codex | `OPENAI_API_KEY` or `CODEX_AUTH_JSON` | none |
| P3 | `$SLUG_GOOGLE` | gemini | `GEMINI_API_KEY` | none |
| P4 | `$SLUG_CURSOR` | cursor | `CURSOR_API_KEY` | none; needs `cursor-agent` binary |
| P5 | `$SLUG_OPENCODE_GO` | opencode | `OPENCODE_GO_API_KEY` (or `LLM_PROVIDER_<n>_API_KEY`) | `mc provider add --label opencode-go --harness opencode` then `mc provider auth opencode-go --scope local --api-key "$OPENCODE_GO_API_KEY"` |
| P6 | `$SLUG_OPENCODE` | opencode | `OPENCODE_API_KEY` or `OPENCODE_AUTH_JSON` | none |
| P7 | `$SLUG_OPENROUTER` | opencode | `LLM_PROVIDER_<n>_API_KEY` | `mc provider add --label openrouter --url https://openrouter.ai/api/v1 --harness opencode`; `mc provider auth openrouter --scope local --api-key "$OPENROUTER_API_KEY"` |
| P8 | `$SLUG_DEEPSEEK` | opencode | `LLM_PROVIDER_<n>_API_KEY` | `mc provider add --label deepseek --url https://api.deepseek.com/v1 --harness opencode`; `mc provider auth deepseek --scope local --api-key "$DEEPSEEK_API_KEY"` |
| P9 | `$SLUG_TOKENHUB` | opencode | `TOKENHUB_API_KEY` | `mc provider add --label tokenhub --url https://tokenhub-intl.tencentcloudmaas.com/v1 --harness opencode`; `mc provider auth tokenhub --scope local --api-key "$TOKENHUB_API_KEY"`. (`mc auth tokenhub` still exists but prints a deprecation warning.) |
| P10 | `$SLUG_MINIMAX` | opencode | `LLM_PROVIDER_<n>_API_KEY` (new layout) or `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` + `_BASE_URL` (legacy) | `mc provider add --label minimax --url "$MINIMAX_BASE_URL" --harness opencode`; `mc provider auth minimax --scope local --api-key "$MINIMAX_API_KEY"`. Test the legacy pair once too (`mc auth minimax`, deprecated) and record whether both layouts are honoured. |

Before the matrix, run `mc models list` and `mc provider status` in the clone and record
which rows show a detected credential. Any provider whose key is set in the env but shows
`no` in `models list` is a plumbing bug: record it and still attempt the review.

Selecting the model for a run, in order of preference (test all three in 5.C.3):

1. `mc agent-local assign-model reviewer p0 <slug>` (writes `.mergecraft/config.local.yaml`; the intended local path)
2. `MERGECRAFT_MODEL=<slug> mc review …`
3. `mc review --model <slug> …`

---

## 4. Testbed PR map

Re-read with `gh pr list --repo "$TESTBED_REPO" --json number,headRefName,title`. Expected
outcome per PR (used in 5.C and 5.D):

| Branch | Planted defect | Expected exit | Expected finding |
|--------|----------------|---------------|------------------|
| `pr/01-docs-only` | none | 0 | none; may report fast-path prose skip if enabled |
| `pr/02-sql-injection` | f-string SQL, string concat SQL | 11 | blocking, `svc/db.py` lines of `execute(` |
| `pr/03-subtle-bug` | `>` vs `>=` tier boundary; bare `except` → 404 | 10 or 11 | at least the boundary bug, on `svc/pricing.py` |
| `pr/04-secret-leak` | AWS example keys, DB password | 11 | blocking; values redacted in every artifact |
| `pr/05-lockfile-only` | none | 0 | "nothing to review", no approval |
| `pr/06-large-diff` | none (volume) | 0 or 10 | completes; coverage section honest |
| `pr/07-mixed-ignored` | `limit * 1000` | 10 or 11 | lockfile ignored, db.py finding present |
| `pr/08-rename` | `Decimal(code)` on raw input | 10 or 11 | finding on `svc/price_rules.py`; no "file deleted" noise |
| `pr/09-binary` | none | 0 | no crash; binary/non-UTF-8 listed as not reviewable |

---

## 5. Test matrix

Each test has an id. Use it as the `run` helper's first argument.

### 5.A Install and offline smoke (no credentials needed)

| ID | Command | Pass when |
|----|---------|-----------|
| A1 | `mc --version`; `mc version --format json` | prints `0.1.0a4 (<sha>)`; JSON has `version` and `commit` |
| A2 | for every leaf in the command tree: `mc <path> --help` | exit 0, no traceback. Generate the tree with the Python snippet in `plans/cli-review-2026-11-03.md` §A, or walk `docs/cli.md` |
| A3 | `mc doctor` and `mc doctor --format json` | table and JSON agree; "provider" row says no credentials |
| A4 | `mc review --dry-run` in the testbed clone on `pr/02-sql-injection` checked out | prints the review prompt, exit 0, no provider call (check no network: run with `HTTPS_PROXY=http://127.0.0.1:9`) |
| A5 | `mc plan` in the clone | model chain, toolset, analyzers, token estimate printed |
| A6 | `mc capabilities`, `mc health run`, `mc lens list`, `mc analyzers list`, `mc pipeline explain`, `mc config validate`, `mc config show prApproveEnabled`, `mc trust show`, `mc jev status`, `mc cache info`, `mc eval list`, `mc eval gate`, `mc policy lint`, `mc memory validate`, `mc learnings active` | all exit 0, no traceback |
| A7 | `echo | mc provider` (stdin not a TTY) | prints group help, does not open an interactive session, exits 0 |
| A8 | `mc review --diff /dev/null` ; `mc review --cwd /tmp/not-a-repo` ; `mc config show nonexistent.key` | clean, actionable error, exit 2 or 30, no traceback |
| A9 | `MERGECRAFT_TRACING=banana mc version` | exit 30 with a message naming `MERGECRAFT_TRACING`, no traceback |
| A10 | Known offline defects from the review (re-check they still reproduce): `mc agent show reviewer` with no credential; `mc traces show <id>`; `mc model add x` with stdin from `/dev/null`; `mc review` in a repo with no `models:` and no roster | each either fixed or reproduces exactly as described in `plans/cli-review-2026-11-03.md` §4.2 |
| A11 | After `mc init` in an empty repo: `cat .gitignore`; after `mc plan`: `git status --short` | `.env` is ignored (currently it is not); `.mergecraft/plan-review.diff` is not left untracked (currently it is) |
| A12 | `mc analyzers docs --cwd <clone>` from the testbed clone, then `git -C /path/to/mergeCraft status` | the mergeCraft checkout is untouched (currently `docs/ANALYZERS.md` there is rewritten) |

### 5.B Credential plumbing

Fresh clone `B`. For every provider in Section 3 whose env var is set:

| ID | Steps | Pass when |
|----|-------|-----------|
| B1 | Run the provider's "Setup in clone" column; then `mc provider list`, `mc provider status`, `mc models list`, `mc doctor` | provider shown; credential `detected`/`available`; doctor "provider" row ok |
| B2 | `cat .env | sed 's/=.*/=<redacted>/'` | only the expected key names were written; file mode is 0600 or the CLI warned |
| B3 | `mc provider disable <label>` then `mc provider status` then `mc provider enable <label> --scope local --api-key …` | disable clears, enable restores; status reflects each step |
| B4 | `mc provider auth <label> --scope github --api-key …` (testbed only) then `mc provider status --github` and `gh secret list --repo "$TESTBED_REPO"` | secret created with the indexed name; `--github` status reads it back; `gh secret delete` afterwards |
| B5 | Deprecated shims: `mc auth gemini --scope local` fed via stdin; `mc auth cursor --scope local`; `mc auth minimax --scope local`; `mc auth tokenhub --scope local` | each prints the "deprecated — use mergecraft provider auth" warning exactly once, still writes the documented key, and non-interactive input works or the command says it needs a TTY (record which) |
| B6 | `mc provider migrate --dry-run` (or without `--apply`) in a clone whose `.env` has only `OPENAI_API_KEY` | explains what it would migrate; no write without apply |
| B7 | `mc agent assign-model reviewer p0 <slug>` in the clone (committed path) without a workflow file | refuses or warns about unwired provider; with `--allow-unwired` it writes `.mergecraft/config.yaml`; `mc workflow sync --check` exits non-zero |
| B8 | `mc init` in an empty git repo, then `mc workflow sync --apply`, then `mc workflow list` | scaffolds config + workflow; sync wires the roster provider; list shows it; `git diff` of the workflow is readable YAML |

### 5.C Live review, each provider as primary

Fresh clone `C`. For each provider Px with a credential (serially):

| ID | Steps | Pass when |
|----|-------|-----------|
| C.Px.1 | `mc agent-local assign-model reviewer p0 "$SLUG"`; `git checkout pr/02-sql-injection`; `run C.Px.1 mc review --base origin/main --json out.json --evidence-packet packet.json` | exit 11; `out.json` has ≥1 finding on `svc/db.py` with a line number; packet has `coverage.complete: true`; stderr text names the model actually used |
| C.Px.2 | same on `pr/01-docs-only` | exit 0; zero code findings |
| C.Px.3 | same PR 02 selected three ways: `agent-local`, `MERGECRAFT_MODEL`, `--model` | all three use the same model (check the run record / `mc run inspect`) and precedence matches the help text (`--model` > env > config) |
| C.Px.4 | `run C.Px.4 mc review --repo "$TESTBED_REPO" --head pull/<N>/head --base main --token "$GH_TOKEN"` for PR 03 | clones privately, reviews, finds the boundary bug or the swallowed exception |
| C.Px.5 | `mc review --diff <(gh pr diff <N> --repo "$TESTBED_REPO")` for PR 07 | lockfile listed as ignored; db.py finding present |
| C.Px.6 | PR 04 with `--tracing --tracing-to local_files --trace-dir traces/`; then `grep -r "AKIAIOSFODNN7EXAMPLE\|hunter2" traces/ out.json packet.json` | grep finds nothing; finding still reported |
| C.Px.7 | PR 06 (large) with `run` and the timeout | completes under `TEST_REVIEW_TIMEOUT_MIN`, or exits 50 cleanly with a timeout message; never a traceback; packet coverage section states uncovered ranges |
| C.Px.8 | PR 05, PR 08, PR 09 | per Section 4 expectations |
| C.Px.9 | Re-run C.Px.1 with `--use-cache` twice | second run reports a cache hit, is fast, same findings; `mc cache info` usage increased |
| C.Px.10 | Record per provider: wall time, tokens/cost if printed, finding count, planted-defect hit rate, false positives | table in Section 7 |

Run the cheapest provider (P5/P7/P8) through all ten; for the rest, C.Px.1, C.Px.2 and
C.Px.6 are mandatory, the remainder budget-permitting.

### 5.D Fallback: each provider as backup

The roster chain walks `modelChain` left to right on *credential miss* or *retryable*
failure (`docs/agent-roster.md`). The workflow-level cascade in `mergecraft.yml` is a
different mechanism and is covered in 5.M. Here we test the in-process chain.

Fresh clone `D`. Pick a working backup provider B (cheapest). For each primary provider P
(including ones you have no key for, for the "missing" case):

| ID | Primary state | Setup | Pass when |
|----|---------------|-------|-----------|
| D.P.1 missing | P's credential **unset** | `mc agent-local assign-model reviewer p0 "$SLUG_P"`; `mc agent-local assign-model reviewer p1 "$SLUG_B"`; unset P's env var; review PR 02 | review completes via B; exit 11; stderr/run record says p0 skipped for missing credential and names B as the reviewer; `mc provider status` beforehand predicted the same skip |
| D.P.2 invalid key | P's credential = `$BAD_API_KEY` | same roster | record whether a 401/403 is treated as retryable (falls to B) or terminal (exit 40). Either is acceptable **if** the message is explicit; a hang or traceback is a FAIL. Note the observed behaviour per harness: they differ |
| D.P.3 dead endpoint | for opencode-harness providers: `mc provider edit <label> --url "$BAD_BASE_URL"` | same roster | transport failure is retryable → B reviews; connection error message names the provider, not the key |
| D.P.4 timeout | `MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES=1` (or the smallest accepted) with P valid on PR 06 | same roster | p0 times out, B runs or run exits 50; the record attributes the timeout to p0 |
| D.P.5 both broken | P and B both invalid | exit 40, message lists both slots and the env names to fix |
| D.P.6 `add-model` tail | `mc agent-local add-model reviewer "$SLUG_B"` twice | second call is a no-op with a message; `mc agent-local show reviewer` lists the chain once |
| D.P.7 committed vs local | put P in `.mergecraft/config.yaml` (via `agent assign-model --allow-unwired`) and B in `config.local.yaml` p0 | local wins for the CLI; `mc agent list` vs `mc agent-local list` show the difference; `GITHUB_ACTIONS=true mc agent-local list` ignores the local file |

Also run once: three-deep chain (P invalid → Q missing → B valid) and confirm the walk
reaches B.

### 5.E Output formats and stored-run inspection

Using one cheap provider on PR 02, in clone `E`:

| ID | Command | Pass when |
|----|---------|-----------|
| E1 | `mc review --output-format json --output r.json` | valid JSON; same finding set as `--json` |
| E2 | `mc review --output-format jsonl --output r.jsonl` | one JSON object per line |
| E3 | `mc review --output-format sarif --output r.sarif.json` | validates against SARIF 2.1.0 (`jq '.version, .runs[0].results | length'`); upload accepted by `gh api repos/$TESTBED_REPO/code-scanning/sarifs` is optional |
| E4 | `mc review --output-format hunk` and `--hunk-file-findings first-changed-line` | stdout is the Hunk comment JSON; file-level findings dropped vs anchored |
| E5 | `mc review --agent > agent.jsonl` | stdout is pure JSONL protocol; human text on stderr only |
| E6 | `mc review 2> review.md` | `review.md` holds the markdown; stdout empty |
| E7 | `mc --format json review` (root format) | selects json as the help promises |
| E8 | `mc run inspect` (list) then `mc run inspect <id>`; `mc run diff <id1> <id2>` between a PR 01 and a PR 02 run | ids listed; diff shows event-kind differences |
| E9 | `mc replay <run-id>`; `mc traces show <run-id>`; `mc traces <run-id>` | both `traces` spellings work (or one is clearly unsupported) |
| E10 | `mc evidence show <finding-id>`; `mc evidence verify <finding-id>`; `mc explain <finding-id>`; `mc findings _by_review_id --review-id <id>` | finding ids from `out.json` resolve; verify never says "approved" |
| E11 | `mc describe` on the PR 02 checkout | title/summary/walkthrough printed; note whether it needed a model call and which provider |
| E12 | `mc audit export`; `mc audit verify <file>`; `mc support-bundle write --output sb.tgz` then `tar tzf sb.tgz` and grep for key values | hash chain verifies; bundle contains no credential values |

### 5.F Diff selection

Clone `F`, cheap provider, dry-run where a live call adds nothing:

| ID | Command | Pass when |
|----|---------|-----------|
| F1 | edit a file; `mc review --unstaged --dry-run`; `git add`; `mc review --staged --dry-run` | prompt contains only the right hunks |
| F2 | `mc review --range origin/main..pr/03-subtle-bug --dry-run` | both commits' hunks |
| F3 | `mc review --base origin/main --head pr/08-rename --dry-run` | rename shown as rename |
| F4 | `git worktree add ../wt pr/02-sql-injection`; `mc review --cwd ../wt --base origin/main --dry-run` | works from a linked worktree |
| F5 | `mc review --repo https://github.com/$TESTBED_REPO --head pull/2/head --base main --dry-run` with and without `--token` | private clone needs token; error without it is clear |
| F6 | no upstream, no `origin/main` (clone with `--single-branch -b pr/02-sql-injection`): `mc review --dry-run` | tells the user to pass `--base`; exit 2/30 |

### 5.G Trust, shell permission, analyzers

Clone `G`, PR 02 + PR 03:

| ID | Command | Pass when |
|----|---------|-----------|
| G1 | `mc analyzers list`; `mc analyzers detect`; `mc analyzers explain ruff` | ruff/bandit listed; detect names them for `.py` changes; note that at `--shell disabled` they are "withheld" |
| G2 | `mc review --shell disabled` vs `--shell restricted` vs `--shell enabled` on PR 02 | analyzer findings (bandit B608 for SQL) appear only at the level the help promises; the run record states the shell level |
| G3 | `mc analyzers run ruff`; `mc analyzers export bandit --output b.sarif` | run locally; SARIF written |
| G4 | `mc analyzers lock` then `git status` | `.mergecraft/analyzers.lock` written; re-run is idempotent |
| G5 | `mc review --with-coverage --shell enabled` on PR 03 | either runs the tests and emits CRAP findings, or refuses with the documented reason (no sandbox wrap). Record which |
| G6 | `mc review --trust untrusted --shell enabled` | shell is capped/refused for untrusted; message explains |
| G7 | `mc trust set-self-review full`; `mc trust set-agent-sandbox same-repo`; `mc trust show` | config written; show reflects source |

### 5.H Config, roster and policy surfaces

Clone `H` (no live calls):

| ID | Command | Pass when |
|----|---------|-----------|
| H1 | `mc config validate`; add `bogusKey: 1` to `.mergecraft/config.yaml`; `mc config validate` | second run fails naming `bogusKey`; exit 30 |
| H2 | `mc config set prApproveEnabled false`; `mc config show prApproveEnabled`; `mc config explain prApproveEnabled`; `MERGECRAFT_PR_APPROVE_ENABLED=true mc config show prApproveEnabled` (if such an env exists per `config explain`) | precedence layer named correctly each time |
| H3 | `mc agent create reviewer2 --role reviewer --after reviewer`; `mc agent set-after reviewer2 reviewer`; `mc agent list`; `mc agent show reviewer2`; `mc agent remove-model reviewer2 p0`; `mc agent delete reviewer2`; `mc agent delete reviewer` | last `delete reviewer` refuses (required role) |
| H4 | `mc agents list`; `mc agents show reviewer`; `mc agents setmodel --role reviewer --model <slug>`; `mc agents addbackupmodel --role reviewer --model <slug2>`; then `mc agent list` | determine whether `agents` and `agent` write the same `agents:` block; if they disagree, that is a **duplicate-surface bug**, record the two YAML shapes |
| H5 | `mc models set "<slug1>,<slug2>"`; `mc models show`; then `mc agent list` | determine whether `models:` and the roster chain agree; record which one `mc plan` honours |
| H6 | `mc model add <slug> --provider <label>`; `mc model list`; `mc model delete <label> <slug>` | round-trips in `providers[].models` |
| H7 | `mc jev enable` with `TYPESAFE_API_KEY` set; `mc jev set <param> <value>`; `mc jev status`; `mc jev disable` | config written and validated; status shows credential presence without the value |
| H8 | create `.mergecraft/policy/rules.yaml` with one blocking rule for `svc/**`; `mc policy lint`; `mc policy test`; `mc policy explain svc/db.py`; `mc policy effective`; then a live review of PR 02 | policy finding appears and the verdict is not approve |
| H9 | `mc memory feedback <fingerprint> --state dismissed`; `mc memory list`; `mc memory show <id>`; `mc memory export`; `mc memory import`; `mc memory forget <id>`; `mc learnings active/staging/influence` | round-trip; determine whether `memory` and `learnings` read the same file |
| H10 | `mc profile recommend --risk high`; `mc requirements inspect`; `mc context inspect`; `mc xrepo explain <id>`; `mc lens show security`; `mc lens test security --diff <file>`; `mc pipeline lint`; `mc pipeline show --diff <file>` | exit 0 or a clear "nothing configured" message; no traceback |

### 5.I Tracing

| ID | Command | Pass when |
|----|---------|-----------|
| I1 | `mc config tracing`; `mc review --tracing --tracing-to local_files --trace-dir t/ …` then `mc traces show <run-id>` | JSONL written; secrets redacted; show re-renders |
| I2 | with `MERGECRAFT_LOGFIRE_TOKEN` set: `mc auth logfire --scope local`; `mc review --tracing-to logfire …` | spans visible in Logfire within 2 minutes (Alex confirms, or use the Logfire API); `--tracing-content metadata` sends no bodies |
| I3 | `mc tracing logfire enable --scope local`; `mc tracing logfire wire-workflow`; `git diff .github/workflows/mergecraft.yml`; `mc tracing logfire unwire-workflow`; `mc tracing logfire disable --scope local` | symmetric; workflow diff is clean YAML; note the overlap with `auth logfire` |
| I4 | `make test-otlp-collector` from the mergeCraft checkout | passes (local OTLP collector) |

### 5.J GitHub-facing read commands (testbed only)

| ID | Command | Pass when |
|----|---------|-----------|
| J1 | `timeout 60 mc watch "$TESTBED_REPO" --pr <N>` while you post a comment with `gh pr comment` | one JSON line per new event |
| J2 | `mc findings export --pr <N> --repo "$TESTBED_REPO"`; `mc findings ledger --pr <N> --repo "$TESTBED_REPO"` | reads mergeCraft review comments if any (there are none unless 5.M ran); otherwise empty with a clear message |
| J3 | `mc findings carryover --pr <N> --repo "$TESTBED_REPO"` (dry run) then `--apply` once | dry run lists issues it would file; apply files them; close them afterwards with `gh issue close` |
| J4 | `mc gha token` | fails with a clear "App credentials missing" message, exit 30/40 |

### 5.K MCP and integrations

| ID | Command | Pass when |
|----|---------|-----------|
| K1 | `mc mcp list --role reviewer` | tool names printed; matches `docs/mcp-tools.md` |
| K2 | `mc mcp serve --stdio --role public --workspace .` fed a JSON-RPC `initialize` then `tools/list` on stdin | valid responses; server exits on EOF |
| K3 | `mc mcp serve --port 0 …` in background, `curl` the health endpoint, `kill` | starts, answers, stops |
| K4 | `mc opencode install --cwd .`; `mc opencode doctor` | files under `.opencode/` created; doctor green; `git status` lists only those |
| K5 | `mc verify-behavior --help`; a real run only if a target app can be started (`uvicorn svc.api:app`) | optional; record whether it can reach the local app |

### 5.L Eval surface (no provider)

| ID | Command | Pass when |
|----|---------|-----------|
| L1 | `mc eval list`; `mc eval gate`; `mc eval replay <case-id>` for one golden case | pass; no provider call |
| L2 | `mc eval score out.json <expected>` using a PR 02 result and a hand-written expected file | scores and exit codes documented in `docs/eval-bank.md` match |
| L3 | note every `eval` subcommand that needs a live provider or maintainer-only fixtures | list them in the report (they are candidates to move out of the shipped CLI) |

### 5.M Action parity (optional, needs Docker and a testbed workflow)

1. In the testbed, commit the workflow produced by `mc init` + `mc workflow sync --apply`,
   add the provider secret with `gh secret set`, open a new PR touching `svc/db.py`.
2. Watch the run: `gh run watch --repo "$TESTBED_REPO"`; after it finishes, compare the
   posted review with a CLI review of the same diff (`mc review --repo … --head pull/N/head`).
3. Fallback at workflow level: remove the primary secret, push an empty commit, confirm the
   next rung reviews (this is the `mergecraft.yml` cascade, not the in-process chain).
4. Record differences in findings, severity and wording between Action and CLI on the same
   diff. They share the review engine, so large differences are bugs.

### 5.N Robustness and negative cases

| ID | Scenario | Pass when |
|----|----------|-----------|
| N1 | Ctrl-C (SIGINT) 10 s into a live review | exits promptly, no orphan `opencode`/`codex` processes (`pgrep`), partial trace closed |
| N2 | two reviews of the same diff in parallel with `--use-cache` | no corrupted cache; `mc cache info` sane |
| N3 | `HOME` read-only / unset | commands that cache degrade with a message, not a traceback |
| N4 | `.mergecraft/config.yaml` with a PR-controlled `trust:` block | CLI never raises its own trust from repo config (help says operator flag only) |
| N5 | `--quiet` on five noisy commands | informational logs suppressed; findings still printed |
| N6 | `--color never` and `NO_COLOR=1` | no ANSI escapes in output |
| N7 | run the CLI from a subdirectory of the clone | `.env` and config found via git root |

---

## 6. Order of execution and stopping

1. 5.A, 5.B (no spend).
2. 5.C for the cheapest provider fully, then C.Px.1/2/6 for every other provider.
3. 5.D with the cheapest backup.
4. 5.E, 5.F, 5.G, 5.H, 5.I, 5.J, 5.K, 5.L.
5. 5.M only if Docker and time allow.
6. 5.N last.

Stop immediately and report if: a credential value is printed anywhere, the CLI modifies
`alexhawat/mergeCraft` on GitHub, or the spend estimate exceeds `TEST_MAX_SPEND_USD`.

---

## 7. Report template

Write `results/<date>/REPORT.md`:

```markdown
# mergeCraft CLI test campaign — <date>

Commit tested: <sha>   Machine: <os / python / node>   Harness CLIs: claude x, codex y, gemini z, opencode w
Providers with credentials: …   Total spend estimate: USD …   Wall time: …

## 1. Scorecard
| Section | Tests | Pass | Fail | Skipped | Notes |

## 2. Provider matrix (primary)
| Provider | slug | review time PR02 | exit | planted bug found | false positives | tokens / cost | notes |

## 3. Fallback matrix
| Primary → Backup | missing | invalid key | dead endpoint | timeout | observed behaviour |

## 4. Failures (one block each)
### <test-id> — <one-line title>
Command: …   Exit: …   Expected: …   Observed: … (quote ≤10 lines of stderr)
Reproducible: yes/no   Severity: blocker / major / minor / cosmetic
Suspected area: <file or module if evident>

## 5. UX observations
Confusing output, misleading help, duplicate surfaces that disagree (H4/H5/H9), slow commands.

## 6. Leaks and safety
Any credential or planted-secret value found in stdout, traces, packets, bundles. "None" if none.

## 7. Recommendations
Top ten, ordered by impact, each with the test ids that motivate it.
```

Attach the `results/<date>/` directory as the raw evidence. Do not include
`test-cli.env` or any `.env` from the clones.
