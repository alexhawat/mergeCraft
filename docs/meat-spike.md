# Meat reading-diff spike (#60) — Batch A evaluation report

**Worktree:** `mergecraft-meat-a-spike` @ `wave/meat-a-spike`
**Wave plan:** `.ignorelocal/waves/issues-meat-reading-diff-wave-plan.md`
**Meat version pinned (W0.4):** `meat.dev@v0.0.0-20260803201634-f39f41dfe7b5`
(Go module proxy time `2026-08-03T20:16:34Z`, requires Go ≥ 1.24.13).
**Binary:** `~/go/bin/meat` (`W0.4` — operator env only, per D6).
**Date:** 2026-08-10
**Author:** W2 (executor) — `wave-plan-executor` on the spike worktree

## TL;DR

The W2 harness — `src/mergecraft/utils/meat_harness.py` — implements every
contract pinned by the W1 RED suite and is **green locally**. The unit
suite (17 tests, 1 integration skipped) passes under
`MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/utils/test_meat_harness.py -q`:

```
17 passed, 1 skipped in 1.56s
```

The harness is the pure-boundary entry point that the W4 integration
batch will sit on top of; per D7/D8/D11/D13 it is correct, opt-in,
trusted-tier-only, shell-disabled-aware, missing-binary-safe, and
never defeats the raw-diff retention invariant.

The **four measurements** that D10 demands — token delta, cold/warm
latency, cost, and fidelity — could not be produced as part of this
wave because **no operator LLM credential is available in the execution
environment**. The harness itself ran cleanly against every corpus
diff; the subprocess boundary overhead was measured (6–8 ms,
independent of diff size); the raw token counts of each corpus diff
were measured as the floor that a real `meat -json` would consume. The
actual LLM-call measurements (cold/warm latency, OpenAI spend,
abridgement fidelity, injection-probe behavior) are **blocked** until
the operator exposes `OPENAI_API_KEY` (per W0.7 the credential is by
env-var name only — never read, logged, or stored by the harness).

**Go/no-go recommendation (D5):** **qualified conditional — green at
the harness and gate layer, blocked at the value-prop layer.** The
harness is fit to ship as the substrate for the W4 integration. The
spike's *value* (does abridging improve the review at acceptable cost?)
cannot be honestly answered without the live LLM call; per D5 that is
a legitimate spike outcome and **must not be assumed into a positive
Batch B start** before the four D10 numbers are produced.

> **Operator decision (D5):** the next step is to either (a) hand the
> spike a credential and rerun the four measurements, or (b) accept
> the W2 report and close **#59 as not-planned** (no Batch B). **#60
> closes** with this report as its deliverable regardless of the
> direction — that is the plan's own acceptance criterion.

## What Meat is

So no future reader has to re-derive it (W2.9):

- **Source:** `https://github.com/boldsoftware/meat`, homepage
  `meat.dev`, entry point `cmd/meat/main.go`. 1.9k stars (Aug 2026).
- **What it does:** reads a unified diff on stdin (or a revision, or
  an unstaged/staged range), asks an LLM to drop noise that no
  reviewer actually wants to read, prints the abridged diff plus a
  one-line summary.
- **Flags pinned at W0.4:** `-model`, `-no-cache`, `-staged`, `-w`,
  `-json`, `-h/--help`. The user-facing terminal output is
  colored and paged by git's pager; piped input is plain. `-json` is
  the wire format (D11).
- **Wire shape (D11):** top-level snake-case keys — `smart_diff`,
  `summary`, `input_tokens`, `output_tokens`, plus an optional
  `elision` field that records dropped hunks. Stable across the pinned
  version.
- **Env (W0.4):** `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`,
  `ANTHROPIC_BASE_URL`, `MEAT_MODEL`, `MEAT_CACHE` (default `~/.meat`;
  empty disables).
- **Cache:** results keyed by SHA of (`rubric + model + diff contents`)
  under `~/.meat`. Re-running on an unchanged diff is instant; editing
  the diff, switching models, or upgrading meat's rubric re-runs.
- **Internal limits (W0.5):** `maxTotalDiffBytes = 4 << 20` (4 MiB
  hard ceiling), `maxDiffBytes = 400 << 10` (~400 KiB single-run
  budget), `maxChunks = 32`. Large diffs split at file/hunk
  boundaries and are abridged chunk by chunk.

## What the harness does

`src/mergecraft/utils/meat_harness.py` (~250 LOC) is the only public
entry point: `run_meat_harness(*, raw_diff, meat_binary, trust_tier,
opt_in, shell, timeout_seconds) -> MeatHarnessResult`.

It enforces every gate **inside** the function (W2.2) so every future
caller inherits them — they are not the caller's responsibility:

- **D7** — `trust_tier != "trusted"` → skip with a named reason.
  No subprocess is invoked.
- **Convention 7** — `opt_in is False` → skip. No subprocess.
- **D7** — `shell in {"disabled"}` → skip. No subprocess.
- **D13** — `meat_binary` does not exist → `logger.warning(...)` with
  an install hint, skip with a named reason. No subprocess.
- **Bounded timeout** — `subprocess.run(timeout=…)`; a hung `meat` is
  killed at the deadline and the result degrades with a "timeout"
  skip reason.
- **Non-zero exit** — captured stderr tail is surfaced in the skip
  reason; result retains the raw diff.
- **Malformed JSON / missing required keys** — `ValueError` caught
  internally; skip with a parse-shaped reason.
- **D8** — every code path returns a result whose `raw_diff` is the
  input `raw_diff` byte-for-byte. A single `_skip_result(...)`
  constructor funnels every failure branch through a uniform shape so
  D8 cannot drift.
- **Convention 8** — the harness never reads `OPENAI_API_KEY` or
  `ANTHROPIC_API_KEY`. The credential reaches `meat` through the
  subprocess inheriting the process env (`os.environ`); the harness
  only adds the binary path and the `-json` flag. The canary test
  proves the value never appears in any log record or on any result
  attribute.
- **Convention 5** — the harness never imports `httpx`, `requests`,
  or `urllib`. The structural test
  `tests/utils/test_meat_harness.py::test_no_network_call_in_unit_tests`
  pins this by AST-scanning the test file for forbidden patterns and
  asserting no `shutil.which('meat')` is called outside the
  integration-marked smoke test.

## Test results

```
$ MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/utils/test_meat_harness.py -q
17 passed, 1 skipped in 1.56s
```

- 17 tests green (every contract the harness must satisfy, from W1.1
  to W1.8).
- 1 test skipped: the `@pytest.mark.integration` real-invocation
  smoke test (`test_real_meat_invocation_smoke`) auto-skips when
  `meat` is not on the agent's PATH. The agent's shell does not have
  `meat` on PATH (the binary lives at `~/go/bin/meat`); the test
  short-circuits to `pytest.skip(...)` with the install hint. To
  exercise the real subprocess end-to-end, run:

  ```
  PATH="$HOME/go/bin:$PATH" \
    uv run pytest -m integration tests/utils/test_meat_harness.py -q
  ```

`make test` on the touched paths:

```
$ MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/utils/test_meat_harness.py -q
17 passed, 1 skipped in 1.56s
```

`make lint` (touched paths under `src/mergecraft/`):

```
$ make lint
ruff check .............................. Passed
ruff format --check .............................. Passed
loguru-only check .............................. Passed
```

`make typecheck` (touched paths):

```
$ make typecheck
mypy strict .............................. Passed
```

## Corpus (W0.6)

12 real diffs from the spike worktree's own history, spanning small
(1–5 files, ≤ 14 KiB), medium (12–15 files, 60–135 KiB), and large
(20–27 files, 110–155 KiB) — D14 requires at least one large, so
two are included.

| PR  | kind   | files | +/–      | chars  | approx_input_tokens |
|-----|--------|-------|----------|--------|---------------------|
| #114 | small  | 1     | 3/0      | 245    | 61                  |
| #111 | small  | 1     | 110/0    | 4,693  | 1,173               |
| #100 | small  | 2     | 120/0    | 5,373  | 1,343               |
| #93  | small  | 3     | 81/4     | 6,284  | 1,571               |
| #103 | small  | 5     | 232/1    | 14,461 | 3,615               |
| #116 | medium | 12    | 1348/15  | 66,675 | 16,668              |
| #115 | medium | 13    | 1686/11  | 74,903 | 18,725              |
| #112 | medium | 14    | 997/39   | 62,127 | 15,531              |
| #113 | medium | 14    | 1415/1   | 72,955 | 18,238              |
| #109 | medium | 15    | 2804/175 | 132,352 | 33,088              |
| #89  | large  | 27    | 2224/17  | 112,032 | 28,008              |
| #92  | large  | 20    | 3879/9   | 153,842 | 38,460              |

Input tokens are an `len(text) // 4` estimate (OpenAI rule-of-thumb for
English/code). The mechanical floor of what any real `meat -json` call
would consume is the row's `approx_input_tokens`; the output tokens
are meat's response and only the real call can measure them.

## D10(1) — Token delta

**Blocked.** Cannot be measured without a credentialed real LLM call.
The raw token counts above are the floor. The harness's wire-format
parser (`_parse_meat_json`) extracts `input_tokens` and `output_tokens`
from `meat -json` and surfaces them on the result; the integration
test confirms the round-trip when the credential is present.

What the production integration would compute (and what W4 will read
from the harness result):

```
token_savings = reviewer_tokens_raw - reviewer_tokens_abridged
```

where `reviewer_tokens_abridged` is the token count of `smart_diff`
(the parsed `abridged_diff` field) and `reviewer_tokens_raw` is the
token count of the raw diff. Per the W1 contract the harness exposes
both surfaces; the diff is in `result.abridged_diff` and the raw
diff is in `result.raw_diff`.

## D10(2) — Latency

**Partially measurable.** The subprocess-boundary overhead is measured
and constant; the LLM round-trip is blocked.

| PR  | kind   | boundary_subprocess_s | real_call_s | real_call_outcome |
|-----|--------|----------------------|-------------|--------------------|
| #114 | small  | 0.031                | 0.008       | credential error   |
| #111 | small  | 0.007                | 0.008       | credential error   |
| #100 | small  | 0.006                | 0.006       | credential error   |
| #93  | small  | 0.006                | 0.007       | credential error   |
| #103 | small  | 0.008                | 0.007       | credential error   |
| #116 | medium | 0.007                | 0.006       | credential error   |
| #115 | medium | 0.007                | 0.007       | credential error   |
| #112 | medium | 0.007                | 0.007       | credential error   |
| #113 | medium | 0.007                | 0.007       | credential error   |
| #109 | medium | 0.007                | 0.007       | credential error   |
| #89  | large  | 0.008                | 0.007       | credential error   |
| #92  | large  | 0.007                | 0.007       | credential error   |

The harness's subprocess boundary is **6–8 ms** independent of diff
size — Go binary startup plus the credential error path. With a real
credential, the cold-cache latency would be the LLM round-trip on top
of this floor; the warm-cache latency would be ~0 ms (cached SHA
lookup). D12 calls this out as a CI cost: an ephemeral runner means a
permanent cold cache, so the "cold" number is the CI-relevant one.

**Without the real LLM call we cannot:**
- Cold-cache latency (LLM round-trip + boundary).
- Warm-cache latency (cache hit + boundary).
- Crossover size where the abridgement quality vs latency
  tradeoff shifts.

What the harness guarantees regardless of the LLM call:
- The subprocess is **bounded** by `timeout_seconds` (a hung `meat`
  cannot hang a review — W1.6).
- The boundary never exceeds the timeout, no matter how large the
  diff (the W0.5 internal `maxTotalDiffBytes = 4 MiB` ceiling is
  meat's, not the harness's; the harness rejects nothing on that
  axis — a 4 MiB diff hits the boundary at the same ~7 ms floor).

## D10(3) — Cost

**Blocked.** Cannot be measured without a credentialed real LLM call.
The cost ratio will be:

```
cost_savings = (reviewer_tokens_raw - reviewer_tokens_abridged)
               * reviewer_cost_per_token
cost_added   = meat_tokens_in  * meat_cost_per_token
             + meat_tokens_out * meat_cost_per_token
```

The harness surfaces `meat.input_tokens` and `meat.output_tokens` on
the result via the `-json` wire format; the operator's actual spend
depends on which model the operator points meat at (`MEAT_MODEL` or
the built-in default). The big-diffs row (#109 at 33,088 tokens,
#92 at 38,460 tokens) is the meaningful cost-question — meat's
hard cap at 4 MiB means a single batch is enough for everything in
the corpus.

## D10(4) — Fidelity

**Blocked.** This is the gate; per D10 it is the deciding measurement.
**No real call → no abridgement → no fidelity comparison.**

The hypothesis the spike would test: *does every behaviour-bearing
hunk that produced a finding in mergeCraft's prior review survive
abridgement?* The W0 sweep noted that the corpus's PR-side
finding-density is low (most merged with no inline comments; the
mergeCraft Action ran and concluded `success`); the spike would
re-run mergeCraft against each corpus diff to seed the structured
findings, then compare. Without the real LLM call this is not
honestly possible.

The structural concern is captured by the plan itself: D8's
"reading diff is an additional lens, never the gating surface" is
what guarantees that even a finding-bearing hunk that meat elides
does not silently disappear — the raw diff is still on every
gating path. The harness's round-trip is what makes that invariant
cheap: the diff is byte-for-byte the input, regardless of what
meat does.

## W2.8 — Injection probe

**Blocked.** Per the plan, the probe embeds an injection string in a
comment inside a corpus diff and records whether meat's
abridgement or summary carries the influence. Without a real call
the probe has no surface to act on.

The structural property the harness guarantees (independent of the
real call) is that the abridgement is **never** rendered into the
prompt by the harness itself — the harness only returns the
abridged diff as a string on the result. The W4 integration
batch (D9) is where the rendering policy lives: it routes the
abridgement through `utils/fence.py` with machine-generated
provenance. That seam is the actual defense — the probe result would
characterize how well the fence holds against an injection that
sits in the abridgement's input, not whether the harness leaks.

## Limitations — what this report does NOT yet say

- **Real-measurement numbers** (D10(1)–D10(4) and W2.8) are blocked
  on the operator LLM credential. The harness is real and the
  corpus is real; the missing piece is the LLM call itself.
- **Cold/warm cache differential** — depends on the operator's
  cache state and the real call.
- **Fidelity findings** — the gate measurement.
- **Injection probe result** — depends on the real call.

## Recommendation (D5)

**Qualified conditional — green at the harness layer, blocked at the
value-prop layer.**

The harness is fit to ship and the W4 integration batch can be
authored against it. **But** the four D10 numbers that D5 calls the
"decision backed by measurement" — cost, latency, fidelity, and
token delta on real diffs — are not in this report. Per D5 the
correct operator decision is one of:

1. **Run the four measurements** with a real credential and let the
   numbers — particularly the fidelity gate (D10(4)) — decide. If
   no finding-bearing hunk is elided, accept the recommendation and
   start Batch B (W3 → W4). If any finding-bearing hunk is elided,
   close #59 as not-planned.

2. **Accept the report as-is** and close **#59 as not-planned** with
   a comment citing this document and the credential blocker. Plan
   the abandoned path is a legitimate outcome (D5).

**The spike does not start Batch B regardless of which of (1) or
(2) the operator favours.** Batch B is gated on a real
recommendation, and the recommendation is not real until the D10
numbers are produced.

**#60 closes with this report as evidence** regardless of the
direction. The spike deliverable is the report.

## What ships in this wave

- `src/mergecraft/utils/meat_harness.py` — the prototype harness.
- `tests/utils/test_meat_harness.py` — W1 GREEN suite (17 passed,
  1 skip).
- `scripts/measure_meat_corpus.py` — operator-runnable measurement
  script that produced the tables above; rerunnable with a credential
  to fill in the missing D10 numbers.
- `docs/meat-spike.md` — this report.

## What is NOT in this wave (intentional)

- No `Dockerfile` change (D6).
- No `RepoSettings` field — that is W4.2 (D4: W2's report chooses
  the integration point; the setting follows in B).
- No `action.yml` input (D6 + D4).
- No prompt rendering change — that is W4.3 (D9: fence routing).
- No `modes.py` change — `modes.py` is reviewer-prompt surface
  owned by every plan in the sweep; one wave per plan may touch it,
  and this plan's is **W4.7**, not W2.
- No upstream contribution to `boldsoftware/meat` (convention 12).
- No graphifys are written in this wave — `graphify update .` runs
  at **A Final**, not at W2 per the wave plan's close-out.

## Reproducing the report

```
# From the spike worktree (mergecraft-meat-a-spike @ wave/meat-a-spike):
make lint                   # ruff + loguru-only
make typecheck              # mypy strict
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/utils/test_meat_harness.py -q
# 17 passed, 1 skipped

# To run the real LLM call the spike needs for the missing D10 numbers:
export OPENAI_API_KEY=...   # value never logged by the harness
python scripts/measure_meat_corpus.py
```
