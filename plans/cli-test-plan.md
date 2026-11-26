# mergeCraft CLI — real-world test plan and agent run-book

Written 2026-11-03 against commit `3000d1c` (version `0.1.0a4`). Revised 2026-11-24
(`f61bc558`) and **2026-11-26 against `main` at `14c0d6fb`** (version `0.1.0a8.dev0`);
Section 0 lists what changed each time.
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

## 0. Revision log

**Always test the current tip of `main`, not a commit named here.** Record the sha in
the report and run the Section 8 check first; it takes under a minute and lists every
command or flag in this file that the live CLI no longer accepts.

### 0.1 Revision 2026-11-26 (`f61bc558` → `14c0d6fb`)

| Measure | Value |
|---------|-------|
| Commits on `main` | 197 (126 non-merge) in two days |
| Files changed | 253 (+14,550 / −2,114 lines) |
| Commits touching `src/mergecraft/cli/` | 9 (9 files, +280 / −108) |
| Releases | `v0.1.0a7`; `main` is `0.1.0a8.dev0` |
| Command tree | unchanged: no command or flag added, removed, hidden or renamed; `docs/cli.md` identical |

The Section 8 check passes unchanged. Everything that moved is behaviour:

| Change on `main` | Effect here |
|------------------|-------------|
| `config show` / `config explain` on an unknown key exit 2 (usage) instead of 30, message printed once | A8, H2 |
| A bad `MERGECRAFT_TRACING` exits 30 with "invalid value for environment variable MERGECRAFT_TRACING" on `review` and `config tracing` (was 2) | A9 |
| A repo with no model chain exits 30 with one line (a configuration error) | A10 |
| `config show models` prints the whole chain joined with ", "; `config show model` prints one slug | H5 |
| Provider registry: a deleted provider's env index is never reused (`providersEnvIndexHighWater`); a non-numeric, missing or null `envIndex` exits 30 with nothing written; a failed `provider add` restores `.env` byte for byte | B9, B10, B11 added |
| Legacy `auth <vendor>` commands read the provider registry from the checkout root, from any subdirectory | B5 |
| Budget exhaustion stops further paid dispatch, records skipped reviewers as not dispatched, and maps to inconclusive (20), never to infra error (40) | rule 10; C.Px.11 added |
| Exit 40 now also covers a failure to write the findings file; the run's cost is still reported | E15 added |
| Every diff walker splits on newline only (carriage returns, form feeds and Unicode line separators inside a line no longer split it) | F8 added |
| Harness pins: claude-code 2.1.330, codex 0.171.0, gemini-cli 0.70.0, `@opencode/cli` 2.3.2 | 1.2 (re-run `npm ci`) |

Unchanged since 2026-11-24 and still open: the `agent show reviewer` traceback (A10), exit
12 for a chain with no credential at all (D.P.5), `analyzers docs` writing into the
package's checkout (A12), `doctor` ignoring a bad `MERGECRAFT_TRACING` (A9), and no
`cursor/*` row in `models list`.

### 0.2 Revision 2026-11-24 (`3000d1c` → `f61bc558`)

| Measure | Value |
|---------|-------|
| Commits on `main` | 1030 (672 non-merge) |
| Files changed | 1719 (+157,349 / −37,967 lines) |
| Commits touching `src/mergecraft/cli/` | 56 (48 files, +2,432 / −1,503) |
| Releases | `v0.1.0a5`, `v0.1.0a6`; `main` is `0.1.0a7.dev0` |
| Command tree | 48 top-level entries (46 visible), 156 leaf commands (136 visible) |

Changes that altered tests in this file:

| Change on `main` | Effect here |
|------------------|-------------|
| `pipeline` group deleted | removed from A6 and H10 |
| `eval` group and `analyzers docs` hidden (still callable from a source checkout) | 5.L and A12 reworded; removed from A6 |
| New `report`, `findings brief`, `findings brief-schema`, `findings outcomes` | added as E13, E14, J5 |
| `review --head REF` / `--range` now require the checkout to sit on the reviewed endpoint with a clean tree (no untracked, non-ignored files) | rule 9; F2, F3 rewritten; F7 added; outputs must be written outside the clone (rule 6) |
| Default working-tree review includes untracked, non-ignored files | a stray `out.json` in the clone would be reviewed; rule 6 |
| `MERGECRAFT_COST_BUDGET_USD` default dropped from 50 to 3 | rule 10; C.Px.7 sets it explicitly |
| Root `--format json` is honoured or rejected (exit 2) per command | E7 |
| `init` gitignores `.env`; `plan` leaves no file behind; `traces show <id>` resolves; four of the five tracebacks are gone | A10, A11 now regression checks |
| `update` installs the latest release | review item 8 closed |
| Flag renames: `agents setmodel/addbackupmodel --agent` (was `--role`), `memory feedback --outcome` (was `--state`), `mcp serve --transport stdio --cwd` (was `--stdio --workspace`), `opencode install --target` (was `--cwd`); `provider migrate` has no `--dry-run` (dry run is the default); `provider enable` takes no `--api-key` | B3, B6, H4, H9, K2, K4 |
| PR #1125 merged 2026-11-04 and closed #1009 (expired Codex login now fails over) | 5.D tests the post-fix chain; D.P.8 added |
| `cursor/auto` is not a catalog slug; the documented one is `cursor/cloud-agent` | `SLUG_CURSOR` |
| Harness pins moved (claude-code 2.1.325, codex 0.169.0, gemini-cli 0.68.0, `@opencode/cli` 2.3.0) | 1.2 |
| Typer now vendors click and loads commands lazily | the tree-dump snippet in the review no longer works; use Section 8 |

### 0.3 State of the human setup on 2026-11-26

- 1.1 prerequisites: all pass on Alex's Mac (checked 2026-11-04).
- 1.4 testbed: **exists**. `alexhawat/mergecraft-cli-testbed`, private, PRs 1–9 open.
- Campaign checkout: git worktree `mc-cli-test` beside the main checkout, branch
  `cli-test-campaign`, fast-forwarded to `main` at `14c0d6fb`, harness CLIs reinstalled at
  the current pins.
- 1.3 `test-cli.env`: template present in the campaign checkout, **credentials not yet
  filled**. This is the only step still blocking live tests (5.A and most of 5.B, 5.F,
  5.H, 5.K need none).

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

The pins move with `main`. Re-run `npm ci` every time the checkout is updated: a stale
`node_modules` leaves `claude` and `opencode` unable to start ("native binary not
installed", "postinstall script was not run"). Run the `export PATH` line in every shell,
otherwise globally installed CLIs at other versions are used instead.

### 1.3 Create `test-cli.env`

Create the file at the root of the campaign checkout as `test-cli.env`, mode `600`. The
tracked `.gitignore` does **not** cover it (only `.env` and `.env.*`), so first add
`test-cli.env` and `results/` to `.git/info/exclude`. **Never** commit it, paste it into an issue, or let the agent print it.
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
MC_CHECKOUT=                  # absolute path of the mergeCraft checkout under test (used by the helpers in Section 2)

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
SLUG_CURSOR=cursor/cloud-agent
SLUG_OPENCODE_GO=opencode-go/deepseek-v4.1-flash
SLUG_OPENCODE=opencode/gpt-5-nano
SLUG_OPENROUTER=openrouter/deepseek-flash
SLUG_DEEPSEEK=deepseek/deepseek-flash
SLUG_TOKENHUB=tokenhub/hy3
SLUG_MINIMAX=minimax/MiniMax-M3
# ===================== end =====================
```

Notes for Alex:

- Subscription credentials need a browser, so the agent cannot mint them.
  `CLAUDE_CODE_OAUTH_TOKEN`: run `claude setup-token` and paste the printed token.
  `CODEX_AUTH_JSON`: the one-line form of a current `auth.json`, for example
  `jq -c . ~/.codex/auth.json`, or run `mergecraft auth codex --scope local` in a scratch
  clone (it drives `codex login --device-auth` in an isolated `CODEX_HOME`) and copy the
  value out of that clone's `.env`.
- A `gh` login with the classic `repo` scope is enough for `GH_TOKEN` (`gh auth token`).
- `GH_TOKEN` is used both by `gh` and by `mergecraft review --repo owner/repo` for private
  clones. A fine-grained token scoped to the testbed with Contents: read, Pull requests:
  read/write, Secrets: write, Issues: write (for `findings carryover --apply`) is enough.
- Cheap models are chosen on purpose. The point is plumbing, not review quality.

### 1.4 Create the testbed repository

**Done on 2026-11-04.** `alexhawat/mergecraft-cli-testbed` exists, private, with PRs 1–9
open in the order below and every planted defect verified on its branch. Skip this step
unless the testbed has to be rebuilt. The script is safe to re-run: it clones an existing
repo instead of creating it, skips branches that already have a PR, and retries the
network calls (the first run was cut twice by connection resets). Do not pipe it through
`tail` or `tee` without `pipefail`; that hides a failing exit code.

The script (needs `gh` logged in as the owner) creates a private repo with a small Python
service, plants bugs on branches, and opens one PR per scenario. Every PR targets `main`. The planted defects are listed so the agent
can judge findings against ground truth.

```bash
#!/usr/bin/env bash
# create-testbed.sh — run from anywhere; needs gh, git, python3
set -euo pipefail
OWNER="${1:?usage: create-testbed.sh <github-owner>}"
REPO="mergecraft-cli-testbed"
WORK="$(mktemp -d)"
cd "$WORK"
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  SEEDED=1                                       # resume: repo exists, only fill in missing PRs
  gh repo clone "$OWNER/$REPO" -- -q
  cd "$REPO"
  git checkout -q main
else
  SEEDED=0
  gh repo create "$OWNER/$REPO" --private --description "mergeCraft CLI testbed (planted bugs)" --clone
  cd "$REPO"
  git checkout -b main 2>/dev/null || git checkout main
fi

if [ "$SEEDED" = 0 ]; then
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
fi

mkpr () { # name, title, body — idempotent; retries push and PR creation on network errors
  local n
  if [ "$(gh pr list --head "$1" --state all --json number --jq 'length' 2>/dev/null || echo 0)" != "0" ]; then
    echo "PR exists, skipping: $1"; git checkout -q main; return 0
  fi
  for n in 1 2 3 4; do
    if git push -u origin "$1" >/dev/null 2>&1 \
       && gh pr create --base main --head "$1" --title "$2" --body "$3" >/dev/null; then
      echo "PR created: $1"; git checkout -q main; return 0
    fi
    if [ "$(gh pr list --head "$1" --json number --jq 'length' 2>/dev/null || echo 0)" = "1" ]; then
      echo "PR created (verified after retry): $1"; git checkout -q main; return 0
    fi
    echo "retry $n for $1" >&2; sleep 8
  done
  echo "FAILED to create PR for $1" >&2; return 1
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
sed -i.bak 's/from svc.pricing import/from svc.price_rules import/' tests/test_pricing.py && rm tests/test_pricing.py.bak  # portable across GNU and BSD sed
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

Give the agent: the campaign checkout (a clean worktree of current `main`, never a
developer's working checkout with local edits), `test-cli.env`, and this file. Tell it which
sections to run if you want less than everything (default: all of Section 5).

---

## 2. Agent ground rules

1. **Load the env once per shell.** `set -a; source test-cli.env; set +a`. Never `cat`
   the file, never echo a variable whose name ends in `_KEY`, `_TOKEN`, `_JSON`. When a
   command prints a credential-looking value, record `REDACTED` and flag it as a finding
   (that is itself a bug in the CLI).
2. **Run the checkout's CLI inside the testbed clone**:
   `uv run --project "$MC_CHECKOUT" mergecraft …`. A bare `uv run mergecraft` inside a
   clone resolves the testbed's own `pyproject.toml` and finds no such command. Prefix every command with
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
   **Every output path must be absolute and outside the testbed clone**: `--json`,
   `--output`, `--evidence-packet`, `--trace-dir`. Use `"$(rd <test-id>)/out.json"`. Short
   names such as `out.json` in Section 5 are shorthand for that. A file written into the
   clone is untracked source: the next working-tree review includes it in the diff, and a
   `--head`/`--range` review refuses to start.
7. **Exit codes have meaning** (`docs/EXIT-CODES.md`): 0 pass, 10 non-blocking findings,
   11 blocking findings, 12 failed, 20 inconclusive, 30 configuration error, 40 infra /
   credential error, 50 timeout, 2 usage error. A traceback on stderr is always a FAIL
   regardless of exit code.
8. **Judge, don't just run.** For each review test compare the findings with the PR's
   planted defect (Section 1.4) and record: planted defect found? (yes/partial/no),
   false positives count, finding has file+line?, severity reasonable?
9. **Check out what you review.** A local `review --head REF` or `--range A..B` requires
   the clone to sit on the reviewed endpoint with no staged, unstaged or untracked
   non-ignored files. Use `git checkout <branch>` first, or a `git worktree` per branch.
   `--repo <URL>` and `--diff <file>` are not affected. A remote `--repo` review does not
   load the cloned repo's `.env`; credentials come from the process environment.
10. **Know the per-run budget.** `MERGECRAFT_COST_BUDGET_USD` defaults to `3.0`; running
    out maps to exit 20 (inconclusive), not a failure and never exit 40. Once it is spent
    no further paid dispatch starts: queued file groups and remaining roster reviewers are
    recorded as not dispatched, in-flight ones finish and are charged once.
    `MERGECRAFT_TOKEN_BUDGET` is advisory only. Leave the default except where a test says otherwise, and never raise
    it above what remains of `TEST_MAX_SPEND_USD`.

Helper used throughout:

```bash
rd () { echo "$MC_CHECKOUT/results/$(date +%F)/$1"; }   # absolute results dir of a test id
run () { # run <test-id> <cmd...>   — records everything under $MC_CHECKOUT/results/
  local id="$1"; shift
  local dir; dir="$(rd "$id")"; mkdir -p "$dir"
  printf '%q ' "$@" > "$dir/cmd.txt"
  local start=$(date +%s)
  ( "$@" ) >"$dir/stdout.txt" 2>"$dir/stderr.txt"; local rc=$?
  echo $rc > "$dir/exit_code.txt"; echo $(( $(date +%s) - start )) > "$dir/duration_s.txt"
  if grep -q "Traceback (most recent call last)" "$dir/stderr.txt"; then echo "TRACEBACK" > "$dir/FAIL"; fi
  echo "[$id] rc=$rc $(cat "$dir/duration_s.txt")s"
  return 0
}
mc () { _TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1 uv run --project "$MC_CHECKOUT" mergecraft "$@"; }
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
`models list` shows no `cursor/*` row at `14c0d6fb`; `docs/authentication.md` names
`cursor/cloud-agent` as the slug for the `cursor` harness. Record whether it resolves.

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
| A1 | `mc --version`; `mc version --format json` | prints `<version> (<sha>)` matching `pyproject.toml` and `git -C "$MC_CHECKOUT" rev-parse --short HEAD` (`0.1.0a8.dev0 (14c0d6f)` on 2026-11-26); JSON has `version` and `commit` |
| A2 | for every leaf in the command tree: `mc <path> --help` | exit 0, no traceback. Generate the tree with the Section 8 walker (the snippet in the review predates Typer's vendored click and returns nothing), or walk `docs/cli.md`. Include the hidden entries: `eval …`, `analyzers docs`, `diff-review` |
| A3 | `mc doctor` and `mc doctor --format json` | table and JSON agree; "provider" row says no credentials |
| A4 | `mc review --dry-run` in the testbed clone on `pr/02-sql-injection` checked out | prints the review prompt, exit 0, no provider call (check no network: run with `HTTPS_PROXY=http://127.0.0.1:9`) |
| A5 | `mc plan` in the clone | model chain, toolset, analyzers, token estimate printed |
| A6 | `mc capabilities`, `mc health run`, `mc lens list`, `mc analyzers list`, `mc findings brief-schema`, `mc config validate`, `mc config show prApproveEnabled`, `mc trust show`, `mc jev status`, `mc cache info`, `mc policy lint`, `mc memory validate`, `mc learnings active` | all exit 0, no traceback |
| A7 | `echo | mc provider` (stdin not a TTY) | prints group help, does not open an interactive session, exits 0 |
| A8 | `mc review --diff /dev/null` ; `mc review --cwd /tmp/not-a-repo` ; `mc config show nonexistent.key` | `--diff /dev/null` exits 0 with "no changes to review"; `--cwd /tmp/not-a-repo` exits 30; `config show nonexistent.key` exits 2 (usage, since 2026-11-25) with the message printed once and not wrapped in a second pair of quotes; one line each, no traceback |
| A9 | `MERGECRAFT_TRACING=banana mc review --dry-run`; `MERGECRAFT_TRACING=banana mc config tracing` | exit 30 with "invalid value for environment variable MERGECRAFT_TRACING", no traceback (observed at `14c0d6fb`; it was exit 2 two days earlier). `mc version`, `mc doctor` and `mc plan` ignore the bad value and exit 0; record whether `doctor` should flag it |
| A10 | Offline defects from the review §4.2, status at `14c0d6fb`. **Still open:** `mc agent show reviewer` with no credential → traceback (`RuntimeError: no runnable model slug in chain`), exit 1. **Fixed, keep as regression checks:** `mc traces show <id>` (resolves; "No traces found" when empty); `mc model add x </dev/null` (one-line error, exit 1); `mc auth gemini --scope local </dev/null` ("canceled", exit 0); `mc lens test bogus --diff f` (exit 2); `mc review` with no credential (no traceback, walks the chain, exit 12); `mc review` in a repo whose config has no `models:` and no roster (one line, exit 30) | the open one is fixed or reproduces as described; none of the fixed ones regresses. Record whether exit 12 is right for "no credential at all" (the exit-code table suggests 40) and whether `model add` should exit 2 |
| A11 | After `mc init` in an empty repo: `cat .gitignore`; after `mc plan`: `git status --short`; then `git add -f .env` and re-run `mc init` | `.env` is in `.gitignore`; `plan` leaves nothing untracked (both fixed since 2026-11-12); a tracked `.env` is refused with a clear message |
| A12 | `mc analyzers docs` (hidden since 0.1.0a5, takes no options) from the testbed clone; compare `stat -f %m "$MC_CHECKOUT/docs/ANALYZERS.md"` before and after | the checkout that hosts the package is untouched, or the command refuses outside a source checkout. At `14c0d6fb` it still rewrites `$MC_CHECKOUT/docs/ANALYZERS.md` (same content, so `git status` stays clean; the mtime shows it) |

### 5.B Credential plumbing

Fresh clone `B`. For every provider in Section 3 whose env var is set:

| ID | Steps | Pass when |
|----|-------|-----------|
| B1 | Run the provider's "Setup in clone" column; then `mc provider list`, `mc provider status`, `mc models list`, `mc doctor` | provider shown; credential `detected`/`available`; doctor "provider" row ok |
| B2 | `cat .env | sed 's/=.*/=<redacted>/'` | only the expected key names were written; file mode is 0600 or the CLI warned |
| B3 | `mc provider disable <label> --scope local` then `mc provider status` then `mc provider enable <label> --scope local` | disable clears, enable restores; status reflects each step. `enable` takes no `--api-key` (it re-runs the `provider auth` flow): record whether it works without a TTY; if not, restore with `mc provider auth <label> --scope local --api-key-stdin` |
| B4 | `mc provider auth <label> --scope github --api-key …` (testbed only) then `mc provider status --github` and `gh secret list --repo "$TESTBED_REPO"` | secret created with the indexed name; `--github` status reads it back; `gh secret delete` afterwards |
| B5 | Deprecated shims: `mc auth gemini --scope local` fed via stdin; `mc auth cursor --scope local`; `mc auth minimax --scope local`; `mc auth tokenhub --scope local` | each prints the "deprecated — use mergecraft provider auth" warning exactly once, still writes the documented key, and non-interactive input works or the command says it needs a TTY (record which). Run one of them from a subdirectory (`cd svc`): it writes the checkout-root `.env` and, when that provider is registered, the indexed `LLM_PROVIDER_<N>_…` key instead of the flat secret |
| B6 | `mc provider migrate` (dry run is the default; there is no `--dry-run` flag), then `mc provider migrate --apply`, in a clone whose `.env` has only `OPENAI_API_KEY` | the first call explains what it would migrate and writes nothing; `--apply` writes the indexed layout and a second `--apply` is a no-op |
| B7 | `mc agent assign-model reviewer p0 <slug>` in the clone (committed path) without a workflow file | refuses or warns about unwired provider; with `--allow-unwired` it writes `.mergecraft/config.yaml`; `mc workflow sync --check` exits non-zero |
| B8 | `mc init` in an empty git repo, then `mc workflow sync --apply`, then `mc workflow list` | scaffolds config + workflow; sync wires the roster provider; list shows it; `git diff` of the workflow is readable YAML |
| B9 | `mc provider add --label one --url https://example.invalid/v1 --harness opencode`; same for `two`; note both env indices (`mc provider list`); `mc provider delete two`; add `three` | `three` gets an index above the one `two` had; `.mergecraft/config.yaml` carries `providersEnvIndexHighWater` set to `two`'s index; no `LLM_PROVIDER_<N>` key of `two` is reused. Verified at `14c0d6fb` (15, 16, then 17). `provider delete` leaves `two`'s `LLM_PROVIDER_<N>` label line in `.env`: record whether that is intended |
| B10 | In `.mergecraft/config.yaml` set one provider row's `envIndex` to `abc`, then to `null`, then delete the key. After each: `mc provider status`; `mc provider add --label x --url https://example.invalid/v1 --harness opencode`; `mc workflow provider add` for the broken label | every call exits 30 naming the provider and `envIndex` and pointing at `provider delete`, no traceback; `git status --short` and `.env` show nothing was written. Verified at `14c0d6fb` for the non-numeric case |
| B11 | No `.env` in the clone; `chmod 555 .mergecraft` (the directory: the config is replaced atomically, so a read-only file alone does not block the write); `mc provider add --label y --url https://example.invalid/v1 --harness opencode`; then `chmod 755 .mergecraft` and repeat the command twice. Repeat the whole test with an existing `.env` | first call exits 30 saying `y` was not registered and leaves no `.env` behind (with an existing `.env`: byte-identical, compare `shasum`); the repeat registers `y` once; the third call exits 30 as a duplicate label. Verified at `14c0d6fb` |

### 5.C Live review, each provider as primary

Fresh clone `C`. For each provider Px with a credential (serially):

| ID | Steps | Pass when |
|----|-------|-----------|
| C.Px.1 | `mc agent-local assign-model reviewer p0 "$SLUG"`; `git checkout pr/02-sql-injection`; `run C.Px.1 mc review --base origin/main --json "$(rd C.Px.1)/out.json" --evidence-packet "$(rd C.Px.1)/packet.json"` | exit 11; `out.json` has ≥1 finding on `svc/db.py` with a line number; packet has `coverage.complete: true`; stderr text names the model actually used |
| C.Px.2 | same on `pr/01-docs-only` | exit 0; zero code findings |
| C.Px.3 | same PR 02 selected three ways: `agent-local`, `MERGECRAFT_MODEL`, `--model` | all three use the same model (check the run record / `mc run inspect`) and precedence matches the help text (`--model` > env > config) |
| C.Px.4 | `run C.Px.4 mc review --repo "$TESTBED_REPO" --head pull/<N>/head --base main --token "$GH_TOKEN"` for PR 03 | clones privately, reviews, finds the boundary bug or the swallowed exception. The cloned repo's `.env` is not loaded for a remote `--repo`: the credential must be in the process environment |
| C.Px.5 | `mc review --diff <(gh pr diff <N> --repo "$TESTBED_REPO")` for PR 07 | lockfile listed as ignored; db.py finding present |
| C.Px.6 | PR 04 with `--tracing --tracing-to local_files --trace-dir "$(rd C.Px.6)/traces"`; then `grep -r "AKIAIOSFODNN7EXAMPLE\|hunter2" "$(rd C.Px.6)"` | grep finds nothing; finding still reported |
| C.Px.7 | PR 06 (large) with `run` and the timeout, once at the default budget and, on the cheapest provider only, once with `MERGECRAFT_COST_BUDGET_USD=5` | completes under `TEST_REVIEW_TIMEOUT_MIN`, or exits 50 (timeout) or 20 (budget exhausted, default is USD 3) with a message that says which; never a traceback; packet coverage section states uncovered ranges |
| C.Px.8 | PR 05, PR 08, PR 09 | per Section 4 expectations |
| C.Px.9 | Re-run C.Px.1 with `--use-cache` twice | second run reports a cache hit, is fast, same findings; `mc cache info` usage increased |
| C.Px.11 | Cheapest provider only: `MERGECRAFT_COST_BUDGET_USD=0.01` on PR 06 | exit 20, never 40; the run record lists a usage row for each dispatch that ran, charged once, and names the reviewers and file groups left undispatched; no "produced no findings" row for a skipped group |
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
| D.P.5 both broken | P and B both invalid; repeat with both credentials unset | same roster | exit 40, message lists both slots and the env names to fix. At `14c0d6fb` an all-missing chain still exits 12 with a `require_human_review` shadow record: record the code for each variant and flag a mismatch with `docs/EXIT-CODES.md` |
| D.P.8 expired subscription (optional) | `CODEX_AUTH_JSON` holds a login whose refresh token is revoked (sign out of that Codex session elsewhere first) | P = `$SLUG_OPENAI` at p0, B at p1 | the chain moves on to B and names the expired login as the reason. This is the case fixed on 2026-11-04 (issue #1009, PR #1125); before that the chain stopped |
| D.P.6 `add-model` tail | P valid | `mc agent-local add-model reviewer "$SLUG_B"` twice | second call is a no-op with a message; `mc agent-local show reviewer` lists the chain once |
| D.P.7 committed vs local | P valid | put P in `.mergecraft/config.yaml` (via `agent assign-model --allow-unwired`) and B in `config.local.yaml` p0 | local wins for the CLI; `mc agent list` vs `mc agent-local list` show the difference; `GITHUB_ACTIONS=true mc agent-local list` ignores the local file |

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
| E7 | `mc --format json review --dry-run`; `mc --format json doctor`; `mc --format json watch …` | every command either emits JSON or exits 2 with one line naming itself ("has no JSON output: drop the root --format json"). No command silently prints text. List which commands accept it |
| E8 | `mc run inspect` (list) then `mc run inspect <id>`; `mc run diff <id1> <id2>` between a PR 01 and a PR 02 run | ids listed; diff shows event-kind differences |
| E9 | `mc replay <run-id>`; `mc traces show <run-id>`; `mc traces <run-id>` | `traces show <run-id>` re-renders the run (fixed since the review); the bare `traces <run-id>` spelling works or fails with a usage error that names `show` |
| E10 | `mc evidence show <finding-id>`; `mc evidence verify <finding-id>`; `mc explain <finding-id>` | finding ids from `out.json` resolve; verify never says "approved". (`findings _by_review_id` is a hidden internal helper that takes no id; it is covered by A2 only) |
| E11 | `mc describe` on the PR 02 checkout | title/summary/walkthrough printed; note whether it needed a model call and which provider |
| E12 | `mc audit export`; `mc audit verify <file>`; `mc support-bundle write --output sb.tgz` then `tar tzf sb.tgz` and grep for key values | hash chain verifies; export is a versioned JSON object with an `events` array; bundle contains no credential values |
| E13 | Collect the evidence packets from 5.C into one directory; `mc report <dir> --output "$(rd E13)/report.json"`; run it a second time with the same `--output` | JSON has `acceptance_rate`, `cost_per_pr_usd`, `time_to_review_seconds`, each with a sample count; runs without cost data leave the cost `null` instead of zero; the second run refuses because the output exists; no provider call |
| E15 | `mkdir ro && chmod 555 ro`, outside the clone; `mc review --json ro/out.json` on PR 02 | refused before any provider call (exit 2 or 30), or, if the write fails after the review, exit 40 with the cost and findings still printed. Record which; a silent exit 0 with no file is a FAIL |
| E14 | `mc findings brief-schema`; `mc findings brief <source>` on the PR 02 result (see `--help` for accepted sources); `--expect-head <wrong-sha>` | schema is valid JSON Schema; the brief validates against it; no file is written and no agent is invoked; a wrong expected head is refused |

### 5.F Diff selection

Clone `F`, cheap provider, dry-run where a live call adds nothing:

| ID | Command | Pass when |
|----|---------|-----------|
| F1 | edit a file; `mc review --unstaged --dry-run`; `git add`; `mc review --staged --dry-run` | prompt contains only the right hunks. Also `mc review --staged --unstaged --dry-run`: reviews the union of both |
| F2 | `git checkout pr/03-subtle-bug` (clean tree); `mc review --range origin/main..pr/03-subtle-bug --dry-run` | the branch's hunks against `origin/main` |
| F3 | `git checkout pr/08-rename` (clean tree); `mc review --base origin/main --head pr/08-rename --dry-run` | rename shown as rename |
| F4 | `git worktree add ../wt pr/02-sql-injection`; `mc review --cwd ../wt --base origin/main --dry-run` | works from a linked worktree |
| F5 | `mc review --repo https://github.com/$TESTBED_REPO --head pull/2/head --base main --dry-run` with and without `--token` | private clone needs token; error without it is clear |
| F6 | no upstream, no `origin/main` (clone with `--single-branch -b pr/02-sql-injection`): `mc review --dry-run` | tells the user to pass `--base`; exit 2/30 |
| F8 | Add a line containing a carriage return, a form feed and U+2028 in its middle (`printf 'x = "a\rb\fc\342\200\250d"\n' >> svc/db.py`); `mc review --unstaged --dry-run`; `mc analyzers detect`; `mc lens test security --diff <(git diff)` | the prompt, the analyzer scope and the lens all see one added line at the same line number; no phantom extra lines |
| F7 | On `main`: `mc review --base origin/main --head pr/08-rename --dry-run`. Then on `pr/08-rename` with `touch notes.txt`: the same command. Then with only an ignored file and a `.mergecraft/reviews/` directory present | first two are refused, naming the mismatch or the untracked file and suggesting commit, stash or a worktree; the third runs. Exit 2 or 30, no traceback |

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
| H1 | `mc config validate`; add `bogusKey: 1` to `.mergecraft/config.yaml`; `mc config validate` | second run fails naming `bogusKey` on one line; exit 30. Also break the YAML (unclosed quote, duplicate key): exit 30, one line, no traceback |
| H2 | `mc config set prApproveEnabled false`; `mc config show prApproveEnabled`; `mc config explain prApproveEnabled`; `MERGECRAFT_PR_APPROVE_ENABLED=true mc config show prApproveEnabled` (if such an env exists per `config explain`) | precedence layer named correctly each time. `mc config show nonexistent.key` and `mc config explain nonexistent.key` exit 2; `mc config set bogusKey 1` exits 30 and lists the supported keys |
| H3 | `mc agent create reviewer2 --role reviewer --after reviewer`; `mc agent set-after reviewer2 reviewer`; `mc agent list`; `mc agent show reviewer2`; `mc agent remove-model reviewer2 p0`; `mc agent delete reviewer2`; `mc agent delete reviewer` | last `delete reviewer` refuses (required role) |
| H4 | `mc agents list`; `mc agents show reviewer`; `mc agents setmodel --agent reviewer --model <slug>`; `mc agents addbackupmodel --agent reviewer --model <slug2>`; then `mc agent list` | determine whether `agents` and `agent` write the same `agents:` block; if they disagree, that is a **duplicate-surface bug**, record the two YAML shapes |
| H5 | `mc models set "<slug1>,<slug2>"`; `mc models show`; then `mc agent list` | determine whether `models:` and the roster chain agree; record which one `mc plan` honours. `mc config show models` prints the whole chain in fallback order joined with ", "; `mc config show model` prints one slug |
| H6 | `mc model add <slug> --provider <label>`; `mc model list`; `mc model delete <label> <slug>` | round-trips in `providers[].models` |
| H7 | `mc jev enable` with `TYPESAFE_API_KEY` set; `mc jev set <param> <value>`; `mc jev status`; `mc jev disable` | config written and validated; status shows credential presence without the value |
| H8 | create `.mergecraft/policy/rules.yaml` with one blocking rule for `svc/**`; `mc policy lint`; `mc policy test`; `mc policy explain svc/db.py`; `mc policy effective`; then a live review of PR 02 | policy finding appears and the verdict is not approve |
| H9 | `mc memory feedback <fingerprint> --outcome dismissed` (also `accepted`, `disputed`); `mc memory list`; `mc memory show <id>`; `mc memory export`; `mc memory import`; `mc memory forget <id>`; `mc learnings active/staging/influence` | round-trip; determine whether `memory` and `learnings` read the same file |
| H10 | `mc profile recommend --risk high`; `mc requirements inspect`; `mc context inspect`; `mc xrepo explain <id>`; `mc lens show security`; `mc lens test security --diff <file>` | exit 0 or a clear "nothing configured" message; no traceback |

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
| J5 | `mc findings outcomes --pr <N> --repo "$TESTBED_REPO" --json` after 5.M posted a review and you resolved one thread and replied to another | advisory outcomes per published finding; empty with a clear message when the PR has no mergeCraft review |

### 5.K MCP and integrations

| ID | Command | Pass when |
|----|---------|-----------|
| K1 | `mc mcp list --role reviewer` | tool names printed; matches `docs/mcp-tools.md` |
| K2 | `mc mcp serve --transport stdio --role public --cwd .` fed a JSON-RPC `initialize` then `tools/list` on stdin | valid responses; server exits on EOF. `--transport stdio --role reviewer` is refused (stdio is public-role only) |
| K3 | `mc mcp serve --port 0 …` in background, `curl` the health endpoint, `kill` | starts, answers, stops |
| K4 | `mc opencode install --target .`; `mc opencode doctor --target .` | files under `.opencode/` created; doctor green; `git status` lists only those |
| K5 | `mc verify-behavior --help`; a real run only if a target app can be started (`uvicorn svc.api:app`) | optional; record whether it can reach the local app |

### 5.L Eval surface (hidden, no provider)

Since 0.1.0a5 the `eval` group is hidden: it is absent from `mc --help` and
`docs/cli.md`, and it only registers when `mergecraft.cli.eval_cmd` is importable. It
still runs from a source checkout. Run these with the campaign checkout as the working
directory (the bank lives in its `evals/` tree; in a testbed clone they report an empty
bank).

| ID | Command | Pass when |
|----|---------|-----------|
| L1 | `mc eval list`; `mc eval gate`; `mc eval replay <case-id>` for one golden case | pass; no provider call |
| L2 | `mc eval score out.json <expected>` using a PR 02 result and a hand-written expected file | scores and exit codes documented in `docs/eval-bank.md` match |
| L3 | `mc --help` and `grep -c 'mergecraft eval' "$MC_CHECKOUT/docs/cli.md"`; then `uv tool run --from mergecraft-action mergecraft eval --help` against the published wheel | `eval` is not advertised in either place; record whether the published wheel (`0.1.0a7` on 2026-11-26) ships the group at all |

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

0. Section 8 check against the tip of `main`; fix this file first if it reports anything.
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

---

## 8. Re-validating this plan against `main`

Run this before every campaign. It dumps the live command tree and checks each `mc …`
invocation in this file: unknown command paths, hidden commands, and flags the command
does not accept. An empty report means the plan still matches the CLI surface. It does
not check behaviour, defaults or exit codes; for those read the `src/mergecraft/cli/`
log since the sha in Section 0 (`git log --oneline <sha>..origin/main -- src/mergecraft/cli/`)
and the diff of `docs/cli.md`.

```bash
cd "$MC_CHECKOUT" && uv run python - plans/cli-test-plan.md <<'PY'
import re, sys, typer
from typer import _click as click          # Typer vendors click; plain `import click` sees nothing
from mergecraft.cli.app import app

root = typer.main.get_command(app); tree = {}
def opts(c): return {o for p in c.params for o in getattr(p, "opts", []) if o.startswith("--")}
def walk(cmd, path, ctx):
    for name in cmd.list_commands(ctx):
        sub = cmd.get_command(ctx, name)   # resolves the lazily loaded command
        if sub is None: continue
        key = " ".join(path + [name]); group = hasattr(sub, "list_commands")
        tree[key] = (group, bool(getattr(sub, "hidden", False)), opts(sub))
        if group: walk(sub, path + [name], click.Context(sub, info_name=name, parent=ctx))
walk(root, [], click.Context(root, info_name="mergecraft"))
root_opts = opts(root); word = re.compile(r"[a-z_][a-z0-9_-]*")
print(f"{len(tree)} nodes, {sum(' ' not in k for k in tree)} top-level")
for ln, line in enumerate(open(sys.argv[1]), 1):
    for m in re.finditer(r"(?<![\w-])mc ([^`|;]+)", line):
        toks = m.group(1).replace('"', " ").split(); i = 0; path = []
        while i < len(toks) and toks[i].startswith("--"):
            i += 2 if toks[i] in ("--format", "--color", "--log-level") else 1
        while i < len(toks) and word.fullmatch(toks[i]) and " ".join(path + [toks[i]]) in tree:
            path.append(toks[i]); i += 1
        key, rest = " ".join(path), toks[i:]
        if not path:
            if toks and word.fullmatch(toks[0]): print(f"L{ln}: unknown command: mc {toks[0]}")
            continue
        group, hidden, accepted = tree[key]
        if group and rest and word.fullmatch(rest[0]): print(f"L{ln}: unknown subcommand: mc {key} {rest[0]}")
        if hidden or tree[path[0]][1]: print(f"L{ln}: hidden: mc {key}")
        for t in rest:
            f = t.split("=")[0].rstrip(",.;:)")
            if f.startswith("--") and f not in accepted | root_opts | {"--help"}:
                print(f"L{ln}: mc {key} does not accept {f}")
PY
```

Expected output on a matching plan: the node count line, plus `hidden:` lines only for the
`eval` commands in 5.L and `analyzers docs` in A12. This file is not on `main`; copy it
into the campaign checkout (or pass its absolute path) before running the check.
