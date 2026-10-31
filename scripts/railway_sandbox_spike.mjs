#!/usr/bin/env node
// SPDX-License-Identifier: MIT
//
// Railway sandbox spike for mergeCraft review + tests (#896).
//
//   create from checkpoint -> check out a PR SHA -> run a review and the tests ->
//   emit a JSON + markdown summary -> destroy the sandbox
//
// OPERATOR-RUN. Creating a sandbox needs a Railway account and RAILWAY_API_TOKEN /
// RAILWAY_ENVIRONMENT_ID, and it costs money. Nothing in this repository runs this
// script. `--dry-run` prints the plan, imports nothing from `railway`, reads no
// credential and touches no network; it is what the tests exercise.
//
// What is and is not verified: the call names below (Sandbox.create, exec, files.read,
// checkpoint, destroy) and the result shape (exitCode, stdout, stderr, timedOut) come
// from docs.railway.com/sandboxes and /guides/code-execution-sandboxes. The npm package
// name ("railway") is inferred from the documented import and is NOT stated there. How
// to pass secrets at create time is not documented, so provider credentials ride on the
// per-command `env` option of exec and never touch the repository or the checkpoint.
//
// Usage:
//   node scripts/railway_sandbox_spike.mjs --sha <commit> [--repo owner/name]
//        [--checkpoint <name>] [--capture-checkpoint <name>] [--out-dir <dir>] [--dry-run]
//   Provider credentials are read from the environment by NAME via --pass-env NAME
//   (repeatable); the value is forwarded to the review command only.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";

// Documented Railway sandbox rates (docs.railway.com/sandboxes, pricing section).
const RATES = { vcpuSecond: 0.00001929, memoryMbSecond: 0.00000001929, egressGb: 0.05 };
const WORKSPACE = "/root/workspace";

const { values } = parseArgs({
  options: {
    sha: { type: "string" },
    repo: { type: "string", default: "alexhawat/mergeCraft" },
    checkpoint: { type: "string" },
    "capture-checkpoint": { type: "string" },
    "test-cmd": { type: "string", default: "uv run --extra dev pytest tests/ci -q -n2" },
    "out-dir": { type: "string", default: "railway-spike-out" },
    "pass-env": { type: "string", multiple: true, default: [] },
    "dry-run": { type: "boolean", default: false },
  },
});

function fail(message) {
  process.stderr.write(`error: ${message}\n`);
  process.exit(2);
}

// Full SHA: `git fetch origin <sha>` cannot resolve an abbreviation against GitHub.
if (!values.sha || !/^[0-9a-f]{40}$/.test(values.sha)) fail("--sha must be a full 40-hex commit SHA");
if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(values.repo)) fail("--repo must be owner/name");
for (const name of values["pass-env"]) {
  if (!/^[A-Z][A-Z0-9_]*$/.test(name)) fail(`--pass-env takes a variable NAME, got ${name}`);
}

// The plan is data, so the dry run and the real run cannot drift apart.
function plan() {
  const checkedOut = Boolean(values.checkpoint);
  const steps = [
    { name: "create", detail: values.checkpoint ? `Sandbox.create(${values.checkpoint})` : "Sandbox.create()" },
  ];
  if (!checkedOut) {
    steps.push({
      name: "clone",
      cmd: `git clone --filter=blob:none https://github.com/${values.repo}.git ${WORKSPACE}/repo`,
    });
  }
  steps.push(
    { name: "checkout", cmd: `cd ${WORKSPACE}/repo && git fetch origin ${values.sha} && git checkout --detach ${values.sha}` },
    { name: "deps", cmd: `cd ${WORKSPACE}/repo && uv sync --extra dev` },
    { name: "tests", cmd: `cd ${WORKSPACE}/repo && ${values["test-cmd"]}` },
    {
      name: "review",
      cmd: `cd ${WORKSPACE}/repo && uv run mergecraft review --base ${values.sha}~1 --head ${values.sha} --json ${WORKSPACE}/review.json`,
      env: values["pass-env"],
    },
  );
  if (values["capture-checkpoint"]) {
    steps.push({ name: "checkpoint", detail: `sandbox.checkpoint(${values["capture-checkpoint"]})` });
  }
  steps.push(
    { name: "read-artifact", detail: `sandbox.files.read(${WORKSPACE}/review.json)` },
    { name: "destroy", detail: "sandbox.destroy() — always, including after a failed step" },
  );
  return steps;
}

const steps = plan();

if (values["dry-run"]) {
  process.stdout.write("DRY RUN — no sandbox is created, no credential is read, nothing is billed.\n");
  for (const step of steps) {
    const what = step.cmd ?? step.detail;
    const env = step.env && step.env.length ? ` [env forwarded by name: ${step.env.join(", ")}]` : "";
    process.stdout.write(`${step.name}: ${what}${env}\n`);
  }
  process.exit(0);
}

for (const name of ["RAILWAY_API_TOKEN", "RAILWAY_ENVIRONMENT_ID"]) {
  if (!process.env[name]) fail(`${name} is not set; this script is operator-run`);
}

const { Sandbox } = await import("railway");

const timings = [];
const started = Date.now();
let sandbox;
let status = "failed";
const results = {};

async function timed(name, fn) {
  const t0 = Date.now();
  try {
    return await fn();
  } finally {
    timings.push({ step: name, seconds: (Date.now() - t0) / 1000 });
  }
}

async function run(step) {
  const env = Object.fromEntries((step.env ?? []).map((n) => [n, process.env[n] ?? ""]));
  const result = await timed(step.name, () =>
    sandbox.exec(`bash -lc '${step.cmd.replaceAll("'", "'\\''")}'`, { timeoutSec: 1800, env }),
  );
  results[step.name] = { exitCode: result.exitCode, timedOut: result.timedOut, truncated: result.truncated };
  return result;
}

try {
  sandbox = await timed("create", () =>
    values.checkpoint ? Sandbox.create(values.checkpoint) : Sandbox.create(),
  );
  for (const step of steps) {
    if (step.name === "create" || step.name === "read-artifact" || step.name === "destroy") continue;
    if (step.name === "checkpoint") {
      await timed("checkpoint", () => sandbox.checkpoint(values["capture-checkpoint"]));
      continue;
    }
    const result = await run(step);
    // The tests may fail without stopping the review: a red suite is data, not an abort.
    if (result.exitCode !== 0 && !["tests", "review"].includes(step.name)) {
      throw new Error(`${step.name} exited ${result.exitCode}: ${(result.stderr ?? "").slice(-500)}`);
    }
  }
  const bytes = await timed("read-artifact", () =>
    sandbox.files.read(`${WORKSPACE}/review.json`, { format: "bytes" }),
  );
  mkdirSync(values["out-dir"], { recursive: true });
  writeFileSync(join(values["out-dir"], "review.json"), bytes);
  status = results.review?.exitCode === 0 && results.tests?.exitCode === 0 ? "ok" : "completed-with-failures";
} catch (error) {
  results.error = String(error?.message ?? error);
} finally {
  if (sandbox) {
    await timed("destroy", () => sandbox.destroy()).catch((e) => {
      results.destroyError = String(e?.message ?? e);
      status = "destroy-failed";
    });
  }
}

const wallSeconds = (Date.now() - started) / 1000;
// A lower bound: it assumes the sandbox size actually used, supplied by the operator,
// because the documented SDK shows no way to read it back.
const vcpu = Number(process.env.SPIKE_VCPU ?? 2);
const memoryMb = Number(process.env.SPIKE_MEMORY_MB ?? 2048);
const estimateUsd = wallSeconds * (vcpu * RATES.vcpuSecond + memoryMb * RATES.memoryMbSecond);

const summary = { sha: values.sha, repo: values.repo, status, wallSeconds, timings, results, estimateUsd, assumed: { vcpu, memoryMb } };
mkdirSync(values["out-dir"], { recursive: true });
writeFileSync(join(values["out-dir"], "summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
writeFileSync(
  join(values["out-dir"], "summary.md"),
  [
    `# Railway sandbox spike — ${values.repo}@${values.sha.slice(0, 12)}`,
    "",
    `Status: **${status}** · wall time ${wallSeconds.toFixed(1)}s · compute estimate $${estimateUsd.toFixed(4)} (assumes ${vcpu} vCPU / ${memoryMb} MB, egress excluded)`,
    "",
    "| Step | Seconds |",
    "| --- | --- |",
    ...timings.map((t) => `| ${t.step} | ${t.seconds.toFixed(1)} |`),
    "",
  ].join("\n"),
);
process.stdout.write(`${status}: summary written to ${values["out-dir"]}\n`);
process.exit(status === "ok" || status === "completed-with-failures" ? 0 : 1);
