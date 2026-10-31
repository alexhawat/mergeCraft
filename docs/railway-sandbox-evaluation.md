# Railway sandboxes as ephemeral runners — evaluation kit

**Audience:** contributor

An evaluation kit for one question: could Railway **Sandboxes** (ephemeral Linux VMs
driven from a CLI or SDK) serve as an optional, disposable runner farm for mergeCraft
review and test jobs? This page holds the method, the measurement template and the
go/no-go criteria. **No run has happened.** The paid run needs a Railway account,
credentials and money, so it is the maintainer's to do; nothing in this repository
creates a sandbox.

## Scope and non-goals

In scope: a runner for (1) a mergeCraft review plus the test suite against a pull
request SHA, and (2) short coding-agent tasks, one sandbox per task.

Not in scope, and not decided here: replacing GitHub Actions as the primary CI system,
auto-merge or production deploys from a sandbox, and production secrets or private
network databases inside a sandbox. Cursor Cloud Agents stay the default ship path;
sandboxes would sit beside them for parallel, disposable compute.

## What the Railway documentation says

Taken from the pages linked under [References](#references); the **Not documented**
column is what the spike has to find out or work around.

| Topic | Documented | Not documented |
| --- | --- | --- |
| Lifecycle | `Sandbox.create()` boots one; `sandbox.destroy()` (or `await using`) ends it; `railway sandbox destroy` from the CLI | — |
| Checkpoints | `sandbox.checkpoint(name)` captures a running sandbox's disk; `Sandbox.create(name)` boots a copy (files persist, processes do not); list, rename, delete | Exact CLI checkpoint syntax; checkpoint storage price; behaviour when the environment is deleted |
| Running commands | `sandbox.exec(cmd, { cwd, env, timeoutSec })` returns `exitCode`, `stdout`, `stderr`, `truncated`, `timedOut`; a non-zero exit does not throw | Full CLI `exec` syntax |
| Getting output out | `sandbox.files.read(path, { format: "bytes" })` | A CLI copy-out command |
| Auth | `RAILWAY_API_TOKEN` and `RAILWAY_ENVIRONMENT_ID` | — |
| Secrets at create time | — | How to pass them; the spike passes provider credentials on the per-command `env` option instead |
| Size and idle timeout | Free 2 vCPU / 2 GB, Hobby up to 8/8, Pro up to 32/32; idle timeout 30 min default on Hobby/Pro (1–120, 0 disables), 5 min on Trial/Free | How to set either from `Sandbox.create` |
| Concurrency | Per environment: Trial and Free 10, Hobby 50, Pro 100; only `CREATING` and `RUNNING` count | — |
| Billing | Per second at VM rates: vCPU about $0.00001929 per second, memory about $0.00000001929 per MB-second, egress $0.05/GB; usage draws from the plan's included usage | Whether capturing a checkpoint is charged |
| npm package | The documented import is `import { Sandbox } from "railway"` | The package name and install command are never stated |

## The spike

`scripts/railway_sandbox_spike.mjs` runs the loop end to end:

1. create a sandbox (from a checkpoint when `--checkpoint` is given);
2. check out the pull request SHA (a full 40-hex SHA);
3. install dependencies, run the tests, run `mergecraft review`;
4. write `summary.json`, `summary.md` and the review artifact locally;
5. destroy the sandbox, in a `finally` block, even after a failed step.

`--dry-run` prints the plan and needs nothing: no account, no credential, no network.
Always read the dry run first.

```bash
node scripts/railway_sandbox_spike.mjs --sha <full-sha> --dry-run
```

A real run, by the maintainer, from a machine that has the SDK installed
(`npm install railway` is an assumption: see the table above):

```bash
export RAILWAY_API_TOKEN=...        # a scoped token for a throwaway project
export RAILWAY_ENVIRONMENT_ID=...
node scripts/railway_sandbox_spike.mjs --sha <full-sha> \
  --pass-env OPENCODE_GO_API_KEY \
  --capture-checkpoint after-deps       # first run: cold boot, captures the checkpoint
node scripts/railway_sandbox_spike.mjs --sha <full-sha> \
  --checkpoint after-deps \
  --pass-env OPENCODE_GO_API_KEY        # second run: boots from the checkpoint
```

Provider credentials are passed by **name** with `--pass-env` and forwarded to the
review step only; the value is read from the environment at run time and is never
written to the script, the checkpoint or the summary. Use a key with a spend cap.

## Measurement template

Run each configuration on the same pull request SHA at least three times and record the
median. Copy this table into the follow-up issue.

| Measure | Cold (no checkpoint) | From checkpoint | Notes |
| --- | --- | --- | --- |
| Boot (`create` seconds) | | | |
| Clone and checkout seconds | | | skipped when the checkpoint holds the clone |
| Dependency install seconds | | | |
| Test suite seconds and exit code | | | |
| Review seconds and exit code | | | |
| Wall time, create to destroy | | | |
| Compute estimate (script) | | | assumes the size you set in `SPIKE_VCPU` / `SPIKE_MEMORY_MB` |
| Billed cost (Railway usage page) | | | the number that counts; compare with the estimate |
| Sandboxes still running after the run | | | must be 0 |
| Plan and size used | | | the Free 2 vCPU / 2 GB headroom matters for a review run |

## Go / no-go criteria

A **go** for a follow-up implementation issue needs all of these:

1. The loop completes with the sandbox destroyed and **zero sandboxes left running**
   afterwards, including when the test step fails.
2. A checkpoint boot plus checkout is at least 3x faster than a cold start for the
   dependency-heavy path, or the cold start is already acceptable on its own.
3. The billed compute cost of one typical review plus test run is below what the same
   run costs on a GitHub-hosted runner, or below an amount the maintainer names up front.
4. Provider credentials reach the review step only and appear in no artifact, log
   excerpt or checkpoint (check the summary and the review artifact for the key).
5. The plan's concurrency cap (Hobby 50, Pro 100) covers the expected number of
   simultaneous pull requests with room to spare, and the idle timeout cannot kill a
   run mid-review.
6. The documented gaps that matter are closed or worked around in the script: how to
   set size and idle timeout, and whether checkpoint capture is billed.

Any of these failing is a **no-go**, or a go only with a stated workaround. The result
is a recommendation, not a decision to adopt.

## How it sits next to the other runners

- **GitHub Actions** stays the primary CI. A sandbox would be a complementary runner for
  work that wants disposable compute, not a replacement.
- **Cursor Cloud Agents** stay the default ship path. Prefer sandboxes for short tasks;
  long interactive sessions belong on a persistent VM.

## References

- <https://docs.railway.com/sandboxes>
- <https://docs.railway.com/guides/code-execution-sandboxes>
- <https://docs.railway.com/cloud-agents>
