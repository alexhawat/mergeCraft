# Check catalog by category

## Table of contents

1. [Functional Correctness](#1-code-correctness)
2. [Data Integrity & Atomicity](#2-data-integrity--atomicity)
3. [Security & Privacy](#3-security--privacy)
4. [Stability & Availability](#4-stability--availability)
5. [Performance & Scalability](#5-performance--scalability)
6. [Maintainability & Code Quality](#6-maintainability--code-quality)
7. [Mechanical evidence](#7-mechanical-evidence)
8. [Pull request hygiene](#8-pull-request-hygiene)

Pick the category by where the **consequence** lands, not what the code looks like.
Use the failure-class primers below as recall hooks — they are not an exhaustive menu.

## 1. Code correctness

**Category: Functional Correctness** — does the change do what it claims, on happy
paths and edge cases?

**Recall primers:** off-by-one bounds; wrong operator or comparison direction;
stale references after rename/removal; copy that no longer matches behavior;
state-machine boundary violations; error paths that swallow or mis-report failures;
feature flags and defaults that change runtime behavior silently.

**Investigate when:** control flow, parsing, validation, API contracts, or user-visible
behavior changes. Docs-only diffs usually need none of this unless the doc asserts
behavior the code contradicts.

**Evidence:** failing tests, gate output, or a cited hunk showing the wrong branch
taken. Speculation without a line anchor is a question, not a finding.

## 2. Data Integrity & Atomicity

Does persistent state stay consistent if the operation fails halfway or retries?

**Recall primers:** partial writes without atomicity; non-idempotent retries;
ordering bugs (record before confirm); migration without rollback; cache/DB drift;
lost updates under concurrency.

**Investigate when:** the diff writes databases, files, ledgers, caches, config, or
any durable artifact. A PR that touches persistence with no Data Integrity finding
deserves one more pass.

**Evidence:** show the ordering or missing transaction boundary on a cited line.

## 3. Security & Privacy

Could an attacker abuse this change to read, write, or execute what they should not?

**Recall primers:** SQL injection; SSRF; insecure deserialization; path traversal;
missing authz on new endpoints; secret leakage; replay/CSRF; cross-tenant isolation;
privilege-drop ordering (files created before ownership is fixed for the dropped user).

**Investigate when:** new surfaces, auth, input handling, secrets, network calls, or
sandbox boundaries move.

**Evidence:** cite the missing check or reachable sink; name the enforcing analyzer
when one fired.

## 4. Stability & Availability

Will this change take production down, wedge a worker, or amplify failures?

**Recall primers:** resource leaks (handles, connections, tasks); unbounded queues;
missing timeouts; crash loops on bad input; startup ordering; fatal errors on
optional dependencies; race conditions on shared mutable state.

**Investigate when:** lifecycle hooks, retries, shutdown paths, background work, or
error propagation change.

**Evidence:** cite the leak or missing guard; tie severity to blast radius if shipped.

## 5. Performance & Scalability

Does this change add work proportional to load?

**Recall primers:** N+1 queries; unbounded queries or fan-out; hot-path allocation;
missing indexes; accidental O(n²) loops; synchronous I/O on request paths.

**Investigate when:** hot paths, data access layers, caching, or batching change.

**Evidence:** cite the loop or query pattern; quantify when possible from the diff.

## 6. Maintainability & Code Quality

Does the change make the codebase harder to change safely later?

**Recall primers:** duplicated logic; leaky abstractions; missing types; bypassing
project conventions; dead code left behind; tests that assert tautologies; comments
restating obvious code; drive-by refactors outside the stated scope.

**Investigate when:** structure, naming, tests, or docs around the change degrade
clarity. Prefer repo gates (`make lint`, `make typecheck`) over personal style.

**Evidence:** gate failure output or a cited hunk showing the regression.

## 7. Mechanical evidence

Repo gates and catalog analyzers are findings you do not have to argue.

| Source | Tool | Finding when |
| --- | --- | --- |
| Repo gates | `mcp__mergecraft__run_static_checks` | status `failed` only |
| Catalog | `mcp__mergecraft__run_analyzers` | verified analyzer rows |
| CI intelligence | `mcp__mergecraft__analyze_ci_failures` | clustered root causes on red CI |

`unavailable`, `declared-but-cannot-run`, `timed_out`, and `ran: false` are honest
skips — never findings. Never run your own toolchain to substitute a missing gate.

## 8. Pull request hygiene

Assertions about the PR itself — title, description, linked issues, scope — belong
in the pre-merge checks table, not as duplicate inline code comments. Exception: a
failing mechanical gate is both a table row and an inline finding.

Flag when the title omits the main change, the body promises work the diff does not
contain, linked issues are not satisfied, or the diff includes undeclared scope.
