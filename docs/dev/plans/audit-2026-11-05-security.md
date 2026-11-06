# GitHub Action, security, SCM and publication audit — 2026-11-05

Audited commit: `55cf88e33c318a8b03a251fb0f8b6dad9d999141`. This memo supplements the main audit, using only the separate November checkout. Source was not changed. No dependency installs, real provider calls, GitHub mutations, or credential inspection occurred. Open work was checked against `plans/audit-2026-11-05-open-work.json`; listed issues and PRs are assumed solved. Read the improve audit playbook sections 1, 2, 5 and finding format, SECURITY.md, relevant doctrine and trust/policy documentation.

**Assessment:** substantial trust hardening has landed since September, but commit identity is still inconsistent at the approval boundary. The completion check is bound to the reviewed checkout while the approval check can approve a later, unreviewed head. That is the highest priority residual here. New findings are a change-path parser omission that suppresses required policy rules, and broken GraphQL endpoint routing on GHES.

## Validation

The retained offline script is `plans/audit-2026-11-05-security-probes.py`. It ran successfully on the existing Python 3.14.6 interpreter, with local source imported through PYTHONPATH; no pytest was installed. The script uses a recording GitHub client, httpx MockTransport, in-memory patch seams, and an isolated disposable Git repository. It creates no source changes and cleans up its fixture repository.

Reproduce from this checkout:

```sh
make --no-print-directory -f - audit-readonly <<'AUDIT_MAKE'
audit-readonly:
	@PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -B plans/audit-2026-11-05-security-probes.py
AUDIT_MAKE
```

The assertions deliberately capture current incorrect behavior; passing these probes confirms the findings, not product correctness. This is not a full test suite, real Action execution, live GHES integration or model-quality test.

## New findings

### SEC-N1 — P2: no-hunk changes with spaces disappear from policy scope

- **Evidence:** `src/mergecraft/utils/diff_paths.py:13–18` restricts each unquoted header path to `\S+`; lines 101–103 silently skip unmatched headers. `changed_paths_from_diff`, lines 130–138, has no fallback for generic no-hunk paths. Its other parser emits hunk ranges and selected exception paths, not every file it sees.
- **Actual trigger:** Git itself emitted unquoted headers for `scripts/deploy job.sh` (mode change), `assets/private key.bin` (binary edit), and `legacy/old file.py -> modern/new file.py` (pure rename). All vanished. The unspaced mode-change control `scripts/control.sh` survived.
- **Observed impact:** `policy/review.py:1160–1163` uses this changed-path set. A required policy scoped to `scripts/deploy job.sh`, requiring `rollback_plan`, produced **zero policy rows** from the parser output; supplying the real path produced a **Major** row for missing proof. Thus valid changes can bypass an otherwise applicable required rule. Blast-radius/trajectory inputs also use the incomplete set at `evidence/run_packet.py:666–672`.
- **Artifact boundary:** `policy/evidence_producers.py:649–669` uses the same parser to prove the declared workflow is unchanged. A mode-only change to `.github/workflows/deploy proof.yml` was accepted as untouched. This demonstrates the provenance predicate's incomplete change set; it does **not** establish changed workflow content executing or a complete artifact forgery.
- **Why tests miss it:** `tests/utils/test_diff_paths.py:25–92` covers no-hunk rename, binary and mode changes only without spaces. `tests/analyzers/test_scope.py:285–340` covers a space-bearing rename with a hunk, which does not expose this omission.
- **Fix:** use one Git path decoder for all path discovery, preserve both rename images, and prefer structured `--name-status -z`/SCM path data when available. Never treat an unparseable changed-file header as proof that no protected path changed.
- **Validation:** generated Git fixtures for mode-only, binary, pure rename, mixed quoted/unquoted and Unicode paths; require the policy row and artifact untouched check to see every real path.
- **Confidence:** high; actual Git and real policy evaluator reproduced. **Effort:** S–M. **Fix risk:** MED because the helper feeds policy, coverage and verifier confinement.
- **Classification:** new; not the unknown lane/scope or declared-scope work in #1056/PR1160.

### SEC-N2 — P2: GHES GraphQL requests use the REST path

- **Evidence:** `utils/github.py:197–204` explicitly accepts the GHES REST base from `GITHUB_API_URL`; `graphql`, lines 394–403, calls `self.post("/graphql")` using that same HTTP client's base URL.
- **Observed trigger:** with base `https://ghe.example/api/v3`, MockTransport recorded the REST URL correctly as `https://ghe.example/api/v3/repos/acme/demo`, then GraphQL as **`https://ghe.example/api/v3/graphql`**.
- **Expected:** GitHub's [GHES GraphQL endpoint documentation](https://docs.github.com/en/enterprise-server@3.20/graphql/guides/forming-calls-with-graphql#the-graphql-endpoint) specifies `https://HOSTNAME/api/graphql`. The source and tests claim GHES environment support; this is not just a feature request for a new SCM.
- **Impact:** GraphQL-backed operations fail on GHES. The new closing-issue requirement producer goes through `utils/github.py:433–436`; the failure is correctly fail-closed in `main.py:1315–1340`, so requirements remain unavailable and required rules cannot be cleared. Thread/GraphQL operations are also affected. This is an availability/compatibility finding, not evidence of secret disclosure.
- **Why tests miss it:** `tests/utils/test_github.py:30–40` checks only the base URL value; it does not send a GraphQL request through the real URL-composition boundary.
- **Fix:** derive a separate GraphQL endpoint, honoring the runner's `GITHUB_GRAPHQL_URL` or transforming a GHES REST base correctly. Keep mock/custom base compatibility explicit.
- **Validation:** MockTransport request-URL assertions for public GitHub, GHES REST+GraphQL, and explicit mock hosts.
- **Confidence:** high; actual HTTP client's request construction reproduced and primary documentation checked. **Effort:** S. **Fix risk:** LOW–MED.
- **Classification:** new; no matching current open issue/PR.

## Previously recorded findings still current

These are residual backlog, not newly discovered bugs. Current source and, where stated, current runtime probes revalidated them.

### SEC-R1 — P1: approval check can approve an unreviewed newer commit

- **Evidence:** `utils/status_checks.py:324–340` rereads the current PR head but separately computes completion SHA from `checkout_sha`. The normal approval post at lines 491–499 uses the newly fetched `head_sha`, not the checkout or packet identity. The sink-failure and missing-packet branches also use the current head (409 and 435).
- **Trigger:** review commit A; a contributor pushes B before final status reporting; the packet still says success for A.
- **Observed:** retained recording-client probe posted `mergecraft: success` on A, then **`mergecraft-approval: success` on B**, with no review of B. It tests the publishing boundary with a predecided packet; it does not assert that an empty finding set should produce approval.
- **Impact:** an approval-only required check can be green on unreviewed code. At minimum the published approval claim refers to the wrong revision. If the completion check is also required, its absence on B may prevent merge, but that does not repair the approval check's truthfulness.
- **Test problem:** `tests/utils/test_status_checks.py:155–172` explicitly expects approval to anchor to the current head despite a different reviewed SHA; this encodes the wrong invariant.
- **Fix/validation:** bind both checks to one immutable reviewed SHA; if current head differs, do not carry forward success. Add head-moves-between-review-and-finalize tests for success, failure and neutral packet branches.
- **Confidence:** high. **Effort:** S. **Fix risk:** LOW–MED. **Classification:** old, unresolved.

### SEC-R2 — P1/P2: checkout hydration replaces operator budgets with head YAML

- **Evidence:** `mcp/review_context.py:42–49` loads settings from the checked-out working tree and replaces `ctx.budget_tracker.bounds`. It ignores `ctx.repo_settings_snapshot`, even when that snapshot is operator-owned. Checkout invokes hydration after materializing the head at `mcp/checkout.py:1519–1523` (and in API-only fallback at1263).
- **Observed:** untrusted context, operator snapshot token budget100, mocked head YAML budget1,000,000: after hydration the live budget was1,000,000 while snapshot remained100.
- **Impact:** a PR can change cost/token/tool-call limits that were meant to constrain its review; it can also artificially tighten them to force an inconclusive run. Environment overrides may constrain some fields, but ordinary YAML limits do not survive.
- **Fix/validation:** resolve run bounds from the pinned settings, then apply the intended round multiplier. Test head config raising and lowering each limit with an immutable operator snapshot.
- **Confidence:** high. **Effort:** S. **Fix risk:** LOW. **Classification:** old, unresolved. Priority depends on whether PR jobs hold spendable provider credentials.

### SEC-R3 — P2: Git show cache ignores repository and resolved object identity

- **Evidence:** `mcp/git.py:214–220` keys and names artifacts only by raw `rev + path`. Cache hit at690–699 occurs before the invocation at709; the accepted `-C`, `--git-dir`, `--work-tree` context is not part of the key. Storage at714–718 uses the same key.
- **Trigger:** read `HEAD:README.md` in primary and then a permitted secondary repository, or read it again after a controlled checkout moves HEAD.
- **Impact:** the second call can silently return another repository's or another revision's source as if current. That contaminates review evidence rather than executing code.
- **Fix/validation:** cache by canonical repository/object database plus resolved blob/object SHA and relevant output options; clear invalidated entries at checkout boundaries. Test two permitted repos with different files, then a moving symbolic ref.
- **Confidence:** high from current control flow; not rerun as a retained November runtime probe. **Effort:** S–M. **Fix risk:** LOW–MED. **Classification:** old, unresolved.

### SEC-R4 — P2: every internal PR in a repository that is itself a fork is treated as external

- **Evidence:** `config/trust_policy.py:150–170` returns `bool(head.repo.fork)` instead of comparing head and base repository identities. Checkout repeats the predicate at `mcp/checkout.py:1164–1172`.
- **Observed:** head and base both `acme/fork`, both repository ID42, with `fork: true`, still returned true.
- **Impact:** normal branch-to-branch PRs inside forked repositories are incorrectly floored/refused, including provider-credential refusal. This is fail-closed overblocking, not escalation.
- **Fix/validation:** compare reliable head/base repository IDs (or normalized full names as fallback); continue failing closed on unknown identity. Cover external fork, same nonfork repo, same fork repo, missing/deleted head repo and comment/dispatch binding.
- **Confidence:** high. **Effort:** S. **Fix risk:** MED because the predicate is a security boundary. **Classification:** old, unresolved.

### SEC-R5 — P1/P2: API head and materialized checkout can race

- **Evidence:** `mcp/checkout.py:1158–1163` reads API headSHA. Lines1193–1198 fetch the moving PR ref through `_fetch_head_with_retry`; line1275 checks out the fetched branch. Line1302 assigns `state.checkout_sha = head_sha or rev-parse HEAD`, so it does not check the actual local object when API supplied a SHA.
- **Trigger:** PR head changes between the API read and fetch.
- **Impact:** the run's claimed immutable commit identity can differ from the source actually reviewed, affecting review publication and evidence binding. This is a different race from SEC-R1: this happens before review; R1 happens at final publication.
- **Fix/validation:** fetch/check out the advertised object or compare actual HEAD against the bound SHA and refetch/rebind safely; a deterministic recording SCM/Git race test should assert there is never a mismatched registered checkout.
- **Confidence:** high from current control flow; not reproduced as a full checkout in retained November probes. **Effort:** M. **Fix risk:** MED. **Classification:** old, unresolved.

### SEC-R6 — P1/P2: scope-union dedup still loses a later stronger finding

- **Evidence:** `mcp/analyzers.py:127–134` skips every later row sharing an earlier fingerprint, regardless of severity. Scope-segment replacement at205–222 repairs whole-run overwrites but routes retained scopes through this first-wins union. The same pattern applies to inline and deferred rows at135–148.
- **Observed:** retained probe calls the real `_store_run_state` twice with valid `make_finding` rows from distinct synthetic analyzer/rule IDs, same message/path/line, both introduced by the PR: first Minor over `[a.py]`, then Major over `[a.py,b.py]`. The final analyzer evidence contains only **Minor**. Fingerprint construction at `analyzers/finding.py:128–129` uses path/body, so distinct rules sharing diagnostic text can collide without manually forging a fingerprint.
- **Impact:** a later blocker from an overlapping analyzer scope can disappear before packet/gate processing. This supplements the main audit's stronger clustering/introduced-by-PR residual; count them under severity-preservation backlog rather than as unrelated fixes.
- **Fix/validation:** apply strongest-severity preservation plus compatible provenance/introduced-by-PR aggregation at every union boundary, including retained scopes and deferred rows. Test both orderings, overlapping scopes, same fingerprints from different rules and differing introduced flags.
- **Confidence:** high for the state-loss boundary; provider/analyzer frequency is not measured. **Effort:** S–M. **Fix risk:** MED. **Classification:** residual of the previously recorded severity-preservation issue, newly checked code location; not a claim that the repaired catalog dedup function itself still drops severity.

## September findings now fixed or materially addressed

- **Indexed OAuth/subscription credentials escaping fork detection:** fixed by canonical credential names and suffixes in `action/inputs.py:390–429`, including arbitrary indexed provider slots, and settings passed by `main.py:1194`.
- **A partial analyzer rerun erasing another scope's evidence wholesale:** fixed by retained scope-keyed segments and union in `mcp/analyzers.py:97–181,184–222`. An unavailable rerun no longer supersedes available evidence. This does not establish every union/dedup severity corner case is solved.
- **get_commit_info replacing the whole-PR diff with one commit:** fixed at `mcp/commit_info.py:33–47`; the artifact is now inspection-only and validation does not register it as canonical scope.
- **Unknown comment/dispatch PR identity granted trust:** substantially fixed in `main.py:1157–1194`: bind the composed dispatch prompt, fetch the target PR before trust derivation, floor failed binding, then enforce the credential invariant. Checkout also rejects a different bound PR at `mcp/checkout.py:1143–1156` and a fork while holding trusted execution/authority at1169–1182. The separate repository-itself-is-a-fork false positive remains.

## Security strengths and boundaries checked

- A formal review is tied to the bound PR/checkout in `mcp/review.py:819–875`. Receipt recovery and inline-publication handling are substantially stronger; this protection does not automatically cover the status-check layer in SEC-R1.
- Policy declarations are read from an operator snapshot or the base commit. Check-run evidence requires the exact head, name, trusted App and successful completed run; `github-actions` is explicitly refused as an App source.
- Declared artifact provenance checks exact workflow path, same repository, exact head and successful run; workflow changes in ignored or unreviewable path lists and truncated listings are rejected. Archive metadata and downloaded length are bounded to1MiB; the decompressed proof-document read is bounded to64KiB+1. The spaced path bug is the specific remaining parser exception demonstrated here.
- The policy evidence docs explicitly disclose that requirements are filename/keyword traceability, not independent verification. Do not present this new producer as proving behavioral acceptance criteria.
- The docs explicitly disclose that an unchanged workflow can call head-controlled scripts, local actions or reusable workflows. Keeping proof creation inline reduces some paths but is not independent validation of every preceding step. This is a documented trust limitation, not a newly proven complete forgery.
- SECURITY.md explicitly discloses unrestricted outbound egress and readable Codex subscription credentials, while the credential broker covers only the OpenAI API-key path. The Git MCP subprocess's inherited environment is also explicitly disclosed. These are product/security limitations, not newly discovered defects.
- GHES remains partial beyond SEC-N2: `mcp/xrepo.py:126` constructs github.com clone URLs. Without an end-to-end GHES support commitment, treat that as a compatibility limitation rather than an additional separately counted finding.

## Exclusions and remaining uncertainty

Excluded the current pin issue#1169, OS advisory/security sweep#1162, unknown lane/scope and fail-then-pass work#1056, declared-scope PR1160, and all other open work recorded in the snapshot. New fanout is owned by the main audit. No new security issue should be inferred from these exclusions.

No full container/action launch, provider calls, real token permissions, live artifact download, subscription credential attack, or real GHES instance was exercised. Main uses the existing local interpreter rather than a freshly installed exact lockfile environment. Only statements supported by current code or the described probes are treated as findings.

