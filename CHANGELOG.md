# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0a5] — 2026-11-08

### Added

#### Ci

- Automate the manifest-to-pin cycle with an App token by @alexhawat in [#1218](https://github.com/alexhawat/mergeCraft/pull/1218)
- Fail-then-pass receipts gate fix pull requests by @alexhawat and @claude in [#1170](https://github.com/alexhawat/mergeCraft/pull/1170)

#### Classify

- Declared scope paths drive the scope gate by @alexhawat and @claude in [#1160](https://github.com/alexhawat/mergeCraft/pull/1160)
- Coded lane reasons and a true/false/unknown checklist by @alexhawat and @claude in [#1149](https://github.com/alexhawat/mergeCraft/pull/1149)

#### Policy

- In-run producers for required-rule evidence keys by @alexhawat and @claude in [#1158](https://github.com/alexhawat/mergeCraft/pull/1158)
- Enforce the repository rules file in review by @alexhawat in [#1116](https://github.com/alexhawat/mergeCraft/pull/1116)

#### Review

- Wire bounded file-group fan-out into roster dispatch by @alexhawat and @claude in [#1157](https://github.com/alexhawat/mergeCraft/pull/1157)
- Ignore_paths and eval-methodology budget by @alexhawat and @claude in [#1123](https://github.com/alexhawat/mergeCraft/pull/1123)

#### Other

- Embed mergeCraft review via OpenAI Agents SDK by @alexhawat in [#1161](https://github.com/alexhawat/mergeCraft/pull/1161)
- Publish from the workflow with PyPI OIDC by @alexhawat in [#1220](https://github.com/alexhawat/mergeCraft/pull/1220)
- Lite review tier and a comment-only recognizer by @alexhawat and @claude in [#1156](https://github.com/alexhawat/mergeCraft/pull/1156)
- Incident evals, rescore delta, finding outcomes, review round cap (#1163–#1166) by @alexhawat in [#1167](https://github.com/alexhawat/mergeCraft/pull/1167)

### Fixed

#### Agents

- Stop the stall report blaming the kill's own socket error by @alexhawat and @claude in [#1147](https://github.com/alexhawat/mergeCraft/pull/1147)
- Cascade failover and gate unknowns by @alexhawat and @claude in [#1125](https://github.com/alexhawat/mergeCraft/pull/1125)

#### Ci

- Place a lone earlier-rung packet downloaded flat by @alexhawat and @claude in [#1135](https://github.com/alexhawat/mergeCraft/pull/1135)
- Docs-only pytest uses bootstrap venv by @alexhawat in [#1108](https://github.com/alexhawat/mergeCraft/pull/1108)
- Run docs-only pytest in bootstrap venv by @alexhawat in [#1139](https://github.com/alexhawat/mergeCraft/pull/1139)
- Give the live smoke a token budget that fits one turn by @alexhawat and @claude in [#1101](https://github.com/alexhawat/mergeCraft/pull/1101)

#### Mcp

- Record refused tool calls and honest run timing by @alexhawat and @Copilot in [#1085](https://github.com/alexhawat/mergeCraft/pull/1085)
- Allowlist merge-base and treat grep no-match as success by @alexhawat in [#1091](https://github.com/alexhawat/mergeCraft/pull/1091)

#### Opencode

- Estimate missing Go costs from published token rates by @alexhawat in [#1111](https://github.com/alexhawat/mergeCraft/pull/1111)
- Record token usage from the 2.x stream by @alexhawat in [#1099](https://github.com/alexhawat/mergeCraft/pull/1099)

#### Review

- Strip internal metadata at the GitHub HTTP boundary by @alexhawat in [#1150](https://github.com/alexhawat/mergeCraft/pull/1150)
- Make the run record describe the run by @alexhawat and @claude in [#1013](https://github.com/alexhawat/mergeCraft/pull/1013)
- Send only GitHub-accepted fields in inline comments by @alexhawat and @claude in [#1104](https://github.com/alexhawat/mergeCraft/pull/1104)
- Publish neutral non-terminal rungs to sticky only by @alexhawat in [#1094](https://github.com/alexhawat/mergeCraft/pull/1094)

#### Other

- Serialize managed pip provisioning by @alexhawat in [#1100](https://github.com/alexhawat/mergeCraft/pull/1100)
- Stop run-bound checkpoint 404 and httpx hint leak by @alexhawat and @Copilot in [#1092](https://github.com/alexhawat/mergeCraft/pull/1092)
- Record platform sandbox capability loss honestly by @alexhawat in [#1093](https://github.com/alexhawat/mergeCraft/pull/1093)
- Pin apt 2.6.2 for CVE-2026-109518 in both images by @alexhawat and @claude in [#1159](https://github.com/alexhawat/mergeCraft/pull/1159)
- Run-health and trajectory correctness by @alexhawat and @claude in [#1124](https://github.com/alexhawat/mergeCraft/pull/1124)
- Name a rename's source in the triage diff by @alexhawat and @claude in [#1146](https://github.com/alexhawat/mergeCraft/pull/1146)
- Attest clean reviews via terminal verdict + read coverage by @alexhawat and @Copilot in [#1086](https://github.com/alexhawat/mergeCraft/pull/1086)
- Let an accepted verdict outrank the driver's exit status by @alexhawat and @claude in [#1148](https://github.com/alexhawat/mergeCraft/pull/1148)
- Fail closed when the review diff cannot show a workflow untouched by @alexhawat and @claude in [#1168](https://github.com/alexhawat/mergeCraft/pull/1168)
- Upload only the wheel and sdist by @alexhawat in [#1223](https://github.com/alexhawat/mergeCraft/pull/1223)
- Actionlint action-manifest false blockers and honest refused-verdict records by @sevn-one in [#1212](https://github.com/alexhawat/mergeCraft/pull/1212)
- Make CLI source, workspace and output behavior consistent by @alexhawat in [#1198](https://github.com/alexhawat/mergeCraft/pull/1198)
- Bind Action reviews to trusted repository and revision identities by @alexhawat in [#1197](https://github.com/alexhawat/mergeCraft/pull/1197)
- Preserve finding identity and prove safe triage skips by @alexhawat in [#1199](https://github.com/alexhawat/mergeCraft/pull/1199)

### Changed

- Read every setting through one typed model by @alexhawat in [#1127](https://github.com/alexhawat/mergeCraft/pull/1127)
- Consolidate root files into existing directories by @alexhawat in [#1202](https://github.com/alexhawat/mergeCraft/pull/1202)

### Docs

- Lead provider examples with OpenCode by @alexhawat in [#1219](https://github.com/alexhawat/mergeCraft/pull/1219)
- Document the published mergecraft-action 0.1.0a4 by @alexhawat in [#1096](https://github.com/alexhawat/mergeCraft/pull/1096)
- Publish audit remediation and accurate consumer support contracts by @alexhawat in [#1201](https://github.com/alexhawat/mergeCraft/pull/1201)

### Internal

#### Action

- Pin self-review to verified manifest ee042005 by @alexhawat in [#1214](https://github.com/alexhawat/mergeCraft/pull/1214)
- Prepare verified image manifest 965c7346 by @alexhawat in [#1213](https://github.com/alexhawat/mergeCraft/pull/1213)
- Pin self-review to verified manifest c6a97521 by @alexhawat in [#1155](https://github.com/alexhawat/mergeCraft/pull/1155)
- Prepare verified image manifest bf82fb33 by @alexhawat in [#1153](https://github.com/alexhawat/mergeCraft/pull/1153)
- Pin self-review to verified manifest f312aa81 by @alexhawat in [#1144](https://github.com/alexhawat/mergeCraft/pull/1144)
- Prepare verified image manifest 37b3b068 by @alexhawat in [#1143](https://github.com/alexhawat/mergeCraft/pull/1143)
- Pin self-review to verified manifest 9e4318a8 by @alexhawat in [#1122](https://github.com/alexhawat/mergeCraft/pull/1122)
- Prepare verified image manifest d103e90c by @alexhawat in [#1121](https://github.com/alexhawat/mergeCraft/pull/1121)
- Pin self-review to verified manifest 3971cbee by @alexhawat in [#1115](https://github.com/alexhawat/mergeCraft/pull/1115)
- Prepare verified image manifest 4417257a by @alexhawat in [#1113](https://github.com/alexhawat/mergeCraft/pull/1113)
- Pin self-review to verified manifest 60176a83 by @alexhawat in [#1107](https://github.com/alexhawat/mergeCraft/pull/1107)
- Prepare verified image manifest 5aaef7c3 by @alexhawat in [#1106](https://github.com/alexhawat/mergeCraft/pull/1106)
- Prepare verified image manifest b98d66b1 by @alexhawat and @claude in [#1102](https://github.com/alexhawat/mergeCraft/pull/1102)
- Pin self-review to the released image 7e2707ab by @alexhawat in [#1089](https://github.com/alexhawat/mergeCraft/pull/1089)
- Prepare verified image manifest 7080e962 by @alexhawat in [#1088](https://github.com/alexhawat/mergeCraft/pull/1088)

#### Deps

- Bump getsentry/craft from 2.35.1 to 3.9.0 by @dependabot in [#1206](https://github.com/alexhawat/mergeCraft/pull/1206)
- Bump getsentry/craft/.github/workflows/changelog-preview.yml from 2.35.1 to 3.9.0 by @dependabot in [#1205](https://github.com/alexhawat/mergeCraft/pull/1205)
- Bump @anthropic-ai/claude-code from 2.1.316 to 2.1.317 in /docker/agent-clis in the agent-clis-patch-minor group by @dependabot in [#1204](https://github.com/alexhawat/mergeCraft/pull/1204)
- Bump docker/login-action from 4.6.0 to 4.7.0 in the github-actions-patch-minor group across 1 directory by @dependabot in [#1064](https://github.com/alexhawat/mergeCraft/pull/1064)
- Bump the agent-clis-patch-minor group across 1 directory with 4 updates by @dependabot in [#1062](https://github.com/alexhawat/mergeCraft/pull/1062)
- Bump golang from `972b411` to `d9b6a1b` by @dependabot in [#1134](https://github.com/alexhawat/mergeCraft/pull/1134)
- Bump litellm from 1.95.1 to 1.100.4 by @dependabot in [#1080](https://github.com/alexhawat/mergeCraft/pull/1080)

#### Integrations

- D47 drop swallowed kwargs from CursorCloudClient by @alexhawat and @claude in [#1154](https://github.com/alexhawat/mergeCraft/pull/1154)
- D48 drop unused CursorCloudClient package re-export by @alexhawat in [#1203](https://github.com/alexhawat/mergeCraft/pull/1203)

#### Other

- D39 drop test-only review_includes_path by @alexhawat in [#1053](https://github.com/alexhawat/mergeCraft/pull/1053)
- D38 drop unused diff_coverage helpers by @alexhawat in [#1044](https://github.com/alexhawat/mergeCraft/pull/1044)
- D43 drop test-only \_analyze_log re-export by @alexhawat in [#1095](https://github.com/alexhawat/mergeCraft/pull/1095)
- D42 drop private names from python.py \__all__ by @alexhawat in [#1079](https://github.com/alexhawat/mergeCraft/pull/1079)
- D32 drop unused RequirementSource by @alexhawat in [#968](https://github.com/alexhawat/mergeCraft/pull/968)
- Raise the self-review token budget to 8M by @alexhawat and @claude in [#1130](https://github.com/alexhawat/mergeCraft/pull/1130)
- D45 drop test-only worktree index_contracts by @alexhawat in [#1118](https://github.com/alexhawat/mergeCraft/pull/1118)
- D44 drop dead range_n and unused OpOptions.max_items by @alexhawat in [#1117](https://github.com/alexhawat/mergeCraft/pull/1117)
- Strengthen mutation, packaging and Action acceptance gates by @alexhawat in [#1200](https://github.com/alexhawat/mergeCraft/pull/1200)
- Write the refreshed Codex login back to CODEX_AUTH_JSON by @alexhawat and @claude in [#1128](https://github.com/alexhawat/mergeCraft/pull/1128)
- D46 drop unused short_commit re-export by @alexhawat in [#1136](https://github.com/alexhawat/mergeCraft/pull/1136)
- Workflows, scheduled advisories, flaky lanes by @alexhawat and @claude in [#1126](https://github.com/alexhawat/mergeCraft/pull/1126)
- Parallelize coverage and release gates and cache mypy by @alexhawat in [#1110](https://github.com/alexhawat/mergeCraft/pull/1110)
- Faster PR gates via coverage reuse, sharding, and path skips by @alexhawat in [#1105](https://github.com/alexhawat/mergeCraft/pull/1105)

### Other

- Integrate audit remediation for Action, CLI, findings, testing, and docs by @alexhawat in [#1209](https://github.com/alexhawat/mergeCraft/pull/1209)
- deps: bump litellm to 1.106.4, keep filelock 4.x by @alexhawat and @claude in [#1141](https://github.com/alexhawat/mergeCraft/pull/1141)
- coverage: count OpenCode native reads as read evidence by @alexhawat and @claude in [#1145](https://github.com/alexhawat/mergeCraft/pull/1145)

## [Unreleased]

### Added

- `mergecraft findings outcomes` aggregates several pull requests (repeat `--pr`)
  and runs a known-clean false-positive check: `--known-clean N` fetches a PR known
  to need no findings (for example a golden `clean` case) and counts every finding
  published on it as a false positive. The merge state is now read from GitHub
  unless `--merged/--not-merged` overrides it. Advisory only; it never moves a
  verdict (#1165).

- Incident-derived eval cases: ``mergecraft eval add-incident`` seeds the structural
  bank from an incident PR plus revert/fix-forward PR with a confirmed bug location
  and mandatory provenance (fail-closed without either) (#1163).
- Advisory base-vs-head structural replay delta: ``mergecraft eval rescore-delta``,
  ``make eval-rescore-delta``, and a CI job on PRs that touch the reviewer surface
  (#1164). Not live detection scores; nothing added to the landing README (RD4).
- Deterministic human outcome tracking for published mergeCraft findings
  (fixed/rejected/intentional/ignored) via ``mergecraft findings outcomes`` — advisory
  only, never moves the verdict (#1165).
- Configurable review round cap ``review.maxReviewRounds`` (default 3): after the cap,
  mergeCraft injects one Major finding asking the author to reconsider the approach;
  the cap never auto-approves (#1166).

- `review.fileGroupFanout` splits a large pull request into bounded read-only
  file groups and has mergeCraft dispatch one reviewer per group, so one
  reviewer does not have to read a 20-file or 800-line diff serially (#1031).
  It is off by default and pending live validation on a large pull request.
  When enabled, a diff with at least `minFiles` changed files or
  `minDiffLines` added lines is split into at most `maxGroups` groups (default
  6), run one after another unless `concurrency` is raised, each capped at
  `perGroupTimeoutS` (1–900 seconds); the whole fan-out spends at most
  `budgetShare` (default 0.5) of the remaining run budget so the secondary
  roster keeps the rest, and an incremental review fans out over the
  incremental diff only. The groups run after the primary
  reviewer has published, so their findings reach the evidence packet and the
  checks the way secondary roster findings do, not the posted review; each such
  row's packet evidence names its group (`reviewer: file-group/<group-id>
  (<model>)`). A failed group is one run-scoped `Minor` row under `run_health`,
  never a failed review, and a smaller diff keeps the single-reviewer path
  unchanged. Keys are documented in `docs/agent-roster.md`.

- `review.fastPath.lite` adds a `lite` triage tier for the two cases a skip
  leaves out: a recognizer that matched but is not in `skipLlm`, and a pin bump
  whose verifying checks have not passed from a trusted App. Instead of the full
  agent review, the run makes one non-streaming call to an operator-registered
  OpenAI-compatible provider with the diff inlined, and posts the findings as a
  review comment. The `tokenCap` (default 50,000) is checked before the call; a
  diff over it, a missing credential or an unregistered provider gets the full
  review, and no diff is truncated. The packet's `triage` section records the
  cap, the tokens used and the prompt version (schema `1.19.0`). A `lite` run
  never grants `mergecraft-approval`: the `mergecraft` check is `neutral`, or
  `failure` on a Critical or Major finding, and usage over the cap or a
  malformed answer is `inconclusive`. Off by default (#1010).

- `review.fastPath.reapproval` carries a trusted mergeCraft pass over to a new
  head whose only PR-authored change since the review is changelog prose — a
  one-line `CHANGELOG.md` fix, or a merge of the base branch whose only conflict
  resolution was the changelog — with zero LLM calls and no repeated full-diff
  reads, agents, analyzers or static checks. The prior pass must be the newest
  `mergecraft-approval` success on the reviewed head from an App in
  `reapproval.trustedCheckApps` (never `github-actions`), for the same pull
  request, target branch and review policy (a digest of `.mergecraft`, the
  workflow file and the mergeCraft version, stamped on every approval check while
  the option is on). Every path changed since the review must be a qualifying
  prose edit or inherited from the base untouched by the pull request, every
  other PR-authored change must equal the reviewed one, and file modes must match;
  anything else, or any read failure, is the normal review. Both checks name the
  prior review, the compared SHAs, the qualifying path, what ran, what was reused
  and what was skipped; other required checks are not reused. The packet records
  it in `triage.reapproval` (schema `1.20.0`). Off by default (#1284).

- A `commentOnly` fast-path recognizer matches diffs that only edit `//` line
  comments in `.ts .go .java .kt .c .h .cc .cpp .hpp .cs .swift` files. JavaScript
  (`.js`, which can hold JSX), `.jsx` / `.tsx`, Rust, `Package.swift`, Go
  `_test.go` files and Go files marked `DO NOT EDIT` are never recognised, and a
  Java unicode escape or a C-family `??` refuses the file. Each changed line must
  be `//`, one space and a plain word, and the head-side text proves it is a
  comment. Non-ASCII text, backticks, raw-string markers, block comments, Swift
  `#/` regex literals, a quote left open at the end of a line, a removal-only edit and every `#`-comment
  language are refused. A recognised edit proves no runtime change; comments that
  carry tool directives (lint, coverage, fallthrough, generator pragmas) are
  refused on a best-effort word list. Opt in through `skipLlm` like the other recognizers
  (#1010).
- A fix pull request now has to prove the fix with a fail-then-pass receipt
  before it can reach the `eligible` lane (#1056). Declare the receipt in
  `ciEvidence.redGreen` (`artifact`, and the `workflow` that uploads it; read
  only from the pull request base): a JSON receipt (`mergecraft.red-green/1`, at
  most 1 MB and 2 000 tests) listing each test's result on the base and on the
  head. The review reads it only from a successful run of that workflow in the
  reviewed repository (never a fork) on the head SHA, only when the pull request
  leaves that workflow untouched, accepts it only for the pull request's exact
  base and head SHAs, and never runs a test itself. A pull
  request is a fix when its title has a conventional `fix` type or it carries a
  label in the new `review.fixLabels` (default `bug`, `fix`; honoured only from
  the pull request base, so a pull request cannot drop its own labels). A new `fix_proof`
  checklist gate passes for a non-fix (`fix.not-required`) or a `proven`
  receipt (`fix.proven`); a fix whose receipt is missing, undeclared, unproven,
  malformed or for other commits keeps the lane at least `medium` with its own
  `fix.*` reason. The receipt is written by the head's own test run, so it
  proves what that run reported and is no defence against an author with push
  access to the workflows. See `docs/red-green-receipts.md`.
  - A base whose config cannot be read, does not validate, or whose commit is
    unknown now says the base config "could not be read" instead of reporting
    that it declares no receipt; the base-side `review.fixLabels` is also
    resolved when a setup-script failure skips the agent.
  - The pull request's title and labels are read once at run start when the event
    does not carry them (a review started from a comment on the pull request or
    from a `workflow_dispatch` naming it), so a `fix:`-titled or `bug`-labelled fix
    is still asked for its receipt on those triggers; a failed read falls back to
    what the event carries. The
    artifact provenance checks the receipt shares with the policy proofs
    (declared workflow untouched, same-repository successful run, bounded
    download) now live in one module used by both.

- A `required` policy rule can now clear on evidence the review collects
  itself, instead of sitting at `Major` until it is waived (#1114). The rule's
  keys come from sources the pull request cannot write. `requirements`
  keyword-matches the acceptance criteria of the issues the pull request closes
  against the diff, never the pull request body, and names each issue's author:
  it proves traceability, not independent review. `xrepo` needs every linked repository the base
  manifest declares to be reviewed, with none omitted. `health_check`,
  `rollback_plan` and `contract_schema` read a proof declared under the new
  `policy.evidence.<key>` setting in the base-side configuration (the
  operator-owned snapshot, or the base commit's `.mergecraft/config.yaml`; never
  the pull request's own copy): either a successful check run on the head commit
  from a trusted GitHub App (`github-actions` is refused), or a
  `policy-evidence.json` of at most 64 KiB uploaded for that commit by a
  successful run of the declared `artifact.workflow` file, from this repository
  rather than a fork, when the pull request does not change that file. Producers run only
  when a triggered rule requires evidence. The row lists each present key with
  its source and gives the reason for each missing one. See
  `docs/policy-evidence.md`.

- The self-review's Codex rung writes the refreshed ChatGPT-subscription login
  back to the `CODEX_AUTH_JSON` repository secret after each run, so the
  rotated refresh token is never left spent (#970). The Codex driver exports
  the refreshed `auth.json` to `MERGECRAFT_CODEX_AUTH_EXPORT` only when the
  refresh token changed; `scripts/codex_auth_writeback.py` compares it with the
  stored secret and runs `gh secret set` under an App token minted with only
  `secrets: write`. A missing, unparsable or token-less file, an unchanged
  token, a login that does not name the stored secret's `tokens.account_id`,
  or a rung that reported the login expired each end in a notice and no write. Operators grant the reviewer App *Secrets:
  Read and write*; `OPENAI_API_KEY` remains the alternative that never expires.

- The `ignore_paths` Action input and `review.ignorePaths` keep changed files
  matching a glob (newline- or comma-separated, `**` crosses directories) out of
  the diff the reviewer reads, so eval data, changelogs and lockfiles no longer
  cost review time on a mixed pull request. The review lists them under "Not
  reviewed (ignored by config)" and the changed-line coverage gate treats them as
  out of scope. `**/CHANGELOG.md`, `**/*.lock`, `**/package-lock.json` and
  generated or minified files are ignored by default; set
  `review.ignorePathDefaults: false` to review them. A pull request whose every
  changed file is ignored passes with "nothing to review" and approval left to a
  human, including a comment-driven review or one whose file listing failed; an
  all-ignored scope is never approved. The repo config is read from the base side only, so a pull request
  cannot ignore its own files (#1109).

- A daily security sweep (`security-sweep.yml`, also on `workflow_dispatch`) runs
  `make lockcheck`, `make security` and a Trivy scan of the published `:latest` and
  `:analyzers` images on `main`, and keeps one tracking issue listing each package,
  installed version, fixed version and advisory ID. A run with the same findings
  updates that issue and a clean run closes it, so an advisory is seen between
  releases instead of on the next PR; no PR check is added (#1069).

- The integration workflow's privileged lane runs the analyzer UID-drop proofs
  (`make test-uid-drop-privileged`), which need root on Linux and self-skip
  everywhere else; in that lane a missing precondition fails rather than skips (#1015).

- A deterministic triage tier, off by default (`review.fastPath.enabled`), decides
  before the agent exists whether a diff needs an LLM review. Recognizers for a
  verified pin substitution, prose, whitespace-only changes and regenerated
  lockfiles skip the review when you opt them in with `skipLlm`; a mixed or
  unproven diff gets a full review, and the prose recognizer never treats a
  dependency manifest, lockfile or agent-instruction file as prose. A skipped run
  posts the `mergecraft` check
  stating `Tier: skip (pinBump) — no LLM review ran`, never grants
  `mergecraft-approval`, and records the tier in the evidence packet and the shadow
  log. It only honours the base-side config of a `pull_request_target` run, and a
  pin bump needs its `pinBump.requireChecks` to have passed on the head SHA from a
  GitHub App named in `pinBump.trustedCheckApps`, because a check-run name alone is
  set by whoever created it (#890).
- The evidence packet carries a `coverage` section (schema `1.17.0`): how many
  changed hunks and lines reached the reviewer, each uncovered range with its cause
  (`diff_truncated`, `no_inline_patch`, `excluded_generated`, `not_delivered`,
  `not_observed`), and whether coverage was `complete`. The `mergecraft` and
  `mergecraft-approval` checks and the run record state it, for example
  `Coverage: 41/44 hunks, 3 uncovered → inconclusive` (#940). The packet also
  carries a `triage` section (schema `1.17.0`).
- `get_review_comments` and the findings sweep report `incomplete` when a pull
  request has more review threads or comments than the page cap, instead of
  silently dropping the rest (#902).
- Review now enforces `.mergecraft/policy/rules.yaml`: a blocking rule on the
  base ref becomes a policy finding that turns an `approve` into
  `request_changes` and fails `mergecraft-approval`, and the same row appears in
  the evidence packet. Rules are read only from a source the pull request cannot
  write — the base commit, or the snapshot taken before checkout on a
  `pull_request_target` run — so a pull request that edits, weakens, deletes or
  waives a rule is judged by the base rules and gets an advisory row saying so.
  An unreadable, oversized or unparseable rules file is a blocking row, and a
  repository without the file reviews exactly as before.

### Changed

- Local `mergecraft review --range` and `--head` revision reviews require a clean
  checkout at the reviewed endpoint, including no nonignored untracked source
  files. Commit or stash local work (including untracked files), or use a clean
  Git worktree. Default working-tree reviews still include local changes;
  ignored files and untracked mergeCraft runtime artifacts remain excluded.

- Consolidate container files under `docker/`, documentation and assets under `docs/`, community guidelines under `.github/`, and build/analyzer tooling under `scripts/`; preserve published Action and plugin paths (#1151).

- A pull request without a declared scope can no longer reach the `eligible`
  lane (#1056). End the pull request body, or an issue it closes, with a
  `Scope paths:` block listing the globs the change is expected to touch; the
  review checks every changed path, both sides of a rename included, against it
  through a new `scope` checklist gate. A path outside the globs is
  `scope.drift`, a block with no globs `scope.undeclared`, a block over the
  bounds (more than 64 globs, a glob over 200 characters, `..`, a leading `/`,
  or a match-everything glob such as `**`) `scope.invalid`, and no block at all
  `scope.unknown`: each keeps the lane at least `medium`. The approval check's
  own verdict does not change; with an unknown scope the gate is unmeasured, so
  the recorded gate action is no longer `auto_merge` and the pull request is
  left for human review. Only `scope.within` passes the gate; a declared scope
  never lowers any other gate. A block inside an HTML comment or a code fence
  is ignored. Plan mode now ends its plans with the block. A classification
  whose checklist misses a gate no longer selects either merge-shaped gate
  action.

- Review pipeline `changed_paths matches '<glob>'` predicates now let a `**`
  segment cross directories: `.github/**` matches `.github/workflows/ci.yml`,
  and `a/**/d.py` matches both `a/d.py` and `a/b/c/d.py`. Before, `**` matched
  a single directory only. Glob matching no longer uses regular expressions or
  `PurePath.match`, so a hostile glob such as `**/**/**/…` cannot stall a run.

- A blast-radius classification now says which signal set its lane and which
  checks it never measured, so an unknown can no longer read as a pass (#1056).
  The packet's `blast_radius` section gains `reasons` (a stable dotted code such
  as `deps.changed` or `signal.missing.diff`, the lane it forces, and a message
  that names any repository override or the small isolated-source carve-out) and
  a `checklist` of fixed gates whose `passed` is `true`, `false` or `null`. A
  result is `eligible` only when every gate is `true`; a `null` gate keeps it
  out. The run record prints the lane and its codes on one line. A repository
  override can no longer lower the `review_config` floor below `medium`, and the
  carve-out now lowers only the source and tests reasons, so a tiny edit to a
  package `__init__.py` stays `medium`. A generated sibling no longer hides an
  untested source change. The merge evidence packet schema moves to
  `1.18.0`; older packets without the fields still validate and decide as before.
- Change-scoped findings in the deterministic review record now read
  `` `path:line` — message `` (they named only the path), so each finding in the
  record points at the line it is about (#1010).

- The self-review's Codex rung runs in its own job, the only one holding the
  `codex-subscription-auth` concurrency group; OpenCode Go and the Claude backstop run
  in jobs outside it. A busy PR no longer has a third queued review cancel a pending
  one unless both actually fall back to Codex. Rung order and the recorded verdict
  are unchanged (#1026).

- The install line is `uv tool install mergecraft-action==0.1.0a4`. PyPI carries
  the pre-release distribution `mergecraft-action`; the git install stays
  documented for an unreleased commit.

- The merge evidence packet schema is `1.17.0`; the trajectory record schema is
  `1.2.0` (optional `diff_read_path`, `diff_read`, `duration_ms` on a tool-call
  row, all omitted while unset; `"refused"` joins the `failure_class`
  vocabulary).
- The IncrementalReview prompt no longer tells the agent to reply to and resolve
  threads, which a review session refuses; it says the run retires addressed
  threads itself, and defines a mergeCraft-originated thread by the
  expected-publisher rule rather than `author=mergecraft[bot]` (#904).
- The learnings-migration read of the old progress comment follows the
  run-bound-id-then-expected-publisher rule. With neither, the read is skipped and
  the run record says `Earlier progress comment not read` (#914).
- The carry-over sweep (`mergecraft findings carryover`) now treats a thread as
  mergeCraft's only when its root comment carries a mergeCraft marker **and** its
  author is an expected publisher (the configured reviewer App, or the app behind
  the `mergecraft-approval` check); the shared `github-actions[bot]` login never
  counts. A repository that publishes as `github-actions[bot]` and configures no
  reviewer App sweeps nothing and the sweep says why. **Fix:** configure the
  reviewer App (`MERGECRAFT_REVIEWER_BOT_LOGIN` / `reviewerBotLogin`) (#905).
- `mergecraft policy --help` and `mergecraft policy effective` now say that review
  enforces the repository's rules file; `policy effective` also says when it is
  showing the shipped example packs because the repository has no rules file.
- Environment settings for run budgets, timeouts, Action inputs and the
  operational knobs are read through one validated model: a malformed numeric
  value names the variable instead of failing with a bare parse error, an empty
  `MERGECRAFT_AGENT_TIMEOUT` fails instead of silently defaulting, and secrets
  read from the environment stay masked in diagnostics.

### Fixed

- GitHub permalinks stay readable in analyzer output, PR comments and traces.
  `blob`/`tree`/`commit` links with a 40- or 64-hex SHA, `actions/runs/<id>(/job/<id>)`
  and `pull`/`issues/<n>` links are exempt from the entropy pass, but only when
  the owner, repo and every path segment would survive redaction on their own;
  query strings and fragments are still redacted, and a token pasted into the path
  still blanks the link (#1281).
- The release publish step accepts Craft's unbracketed `## <version>` changelog
  heading as well as `## [<version>] — <date>`, so the GitHub release is no longer
  left half-done after PyPI publishes (#1226).
- Two URL-credential redaction canaries no longer trip TruffleHog's `URI` detector
  on a full-tree scan: the test assembles its synthetic userinfo at runtime and the
  changelog prose uses a `<password>` placeholder (#1217).

- MCP `shell` and the repository tools (`git`, `git_fetch`, `push_branch`, `push_tags`,
  `delete_branch`, `commit_changes`) no longer run blocking subprocess calls on the
  event loop (they run via `asyncio.to_thread`), so a slow command stops stalling every
  other tool call. A shell command that times out and then also fails the post-kill
  drain is now reaped and returns the output gathered so far instead of raising (#1243).
- An analyzer timeout now kills the analyzer's whole process group. The runner
  starts analyzers as session leaders and `killpg`s them on timeout, so grandchildren
  no longer outlive the gate (#1242).
- ruff diagnostics are no longer all blocking Major: ruff emits `severity: error`
  for every rule, so the parser now keeps Major only for bug-class rule codes
  (syntax errors, undefined names, bugbear, security, pylint errors, async) and
  maps style/import/unused-name rules to Minor (#1241).
- Sandbox harness startup failures (`unshare`/`bwrap`/`setpriv` refusing to create
  a namespace, fork `EAGAIN`, `uid_map` write denied) are now classified as
  `sandboxed: isolation unavailable` and reported `declared-but-cannot-run`
  instead of a blocking gate failure (#1240).
- Free-text secret redaction no longer leaks random credentials. The camelCase
  identifier exemption now requires word-shaped keys (``ruleId``,
  ``partialFingerprints``) instead of any lowercase-led blob with a capital, the
  entropy threshold is capped at 4.5 bits per character so long tokens cannot
  outgrow it, and fine-grained GitHub PATs (``github_pat_``), PyPI tokens and
  ``Bearer`` credentials are redacted by pattern (the ``Bearer`` word is kept)
  (#1232).
- `envAllowlist` can no longer pass credentials to subprocesses. A
  credential-shaped name (`*_TOKEN`, `*_KEY`, `*-TOKEN`, …) or one of
  `GITHUB_TOKEN`, `GH_TOKEN`, `GIT_ASKPASS` and the Actions OIDC request
  variables is now ignored with a warning instead of reaching the restricted
  MCP shell, trusted analyzers and analyzer fallback environments; the action's
  `INPUT_TOKEN` and hyphenated inputs such as `INPUT_LOGFIRE-TOKEN` count as
  credentials. Non-secret names are still added (#1233).
- One undecodable TruffleHog output line (a truncated write or a stray banner)
  no longer discards the whole secret scan: the line is skipped and the
  findings on every other line are kept. Output with no decodable line is still
  reported as unparsable rather than as a clean scan (#1234).
- Trace error text no longer carries URL credentials. A failed HTTP request's
  exception message quotes the raw URL, so `https://user:<password>@host` reached
  the span's `error` attribute even though `http.url` was redacted; the
  `error`, `exception.message` and `tool.error_message` attributes now get the
  same URL credential redaction before any sink sees them (#1235).
- Managed pip analyzer provisioning bounds `uv pip install` at 600 seconds. It
  runs while holding the shared cache lock, so a hung install used to block every
  other worker; a timeout now removes the staging tree and fails the install
  cleanly (#1261).
- Baseline suppression bounds the base-worktree `git worktree add` and `remove`
  calls. A timed-out or failed checkout now removes its temp tree and disables
  suppression for that run instead of raising (#1262).
- Contract base-ref probes (`git rev-parse` and `git show`) are bounded. A timeout
  reads as "base unavailable" and skips the contract check rather than hanging the
  review (#1263).
- A baked analyzer binary that is missing no longer falls back to a same-named
  binary on `PATH`. Callers skip lock and hash verification for a returned path,
  so the fallback could run an unpinned tool; the managed resolver provisions it
  instead (#1264).
- Malformed ast-grep rows (a missing or non-numeric line, a non-object entry) are
  skipped during change-impact declaration extraction instead of aborting the
  batch (#1265).
- The comment-preserving config patch (`patch_config_dict`) writes through the
  same temp-file and atomic `os.replace` path as the full rewrite, so a failure
  mid-write can no longer leave a truncated `config.yaml` (#1266).
- The temporary findings sink for `mergecraft review` no longer leaks a file
  descriptor per run (#1267).
- The egress bridge bounds its `/etc/hosts` bind mount at 10 seconds and removes
  its staging directory once the mount call returns, so one directory no longer
  leaks per run (#1268).
- Handing the isolated opencode data tree to the agent user no longer follows
  symlinks: a link planted in the tree cannot re-own or chmod a file outside it
  (#1269).
- Killed background shell processes are reaped after the kill, so they no longer
  linger as zombies until the MCP server exits (#1270).
- The JSONL trace file sink redacts and caps events before writing, as the memory
  and redacting sinks already did, so a credential in a span attribute no longer
  reaches disk (#1271).
- Removed an unreachable inner `try`/`except` from broker stream redaction; the
  latin-1 decode it guarded cannot fail (#1272).
- Removed the 2026-11-05 audit probe scripts from `docs/dev/plans`. They sat
  outside lint scope, had gone stale, and asserted the buggy behaviour the
  audit found, so they failed once those findings were fixed. The audit memos
  now point to their copies in git history (#1273).
- Config: the run-start integrity hash now covers the files the layered loader reads (the `MERGECRAFT_CONFIG` file when set), uses a stable sentinel when no config exists so a file appearing mid-run is detected, and fails closed if a contributing file cannot be hashed ([#1244](https://github.com/alexhawat/mergeCraft/issues/1244))
- MCP: `get_issue`, `get_issue_comments` and `get_issue_events` no longer rebind the run's issue number, so reading another issue cannot redirect progress comments or review scope ([#1245](https://github.com/alexhawat/mergeCraft/issues/1245))
- Jev: an unknown question pack now raises `JevError(invalid_pack)` instead of sending the caller's state unfiltered and unfenced ([#1246](https://github.com/alexhawat/mergeCraft/issues/1246))
- Sandbox: the `RLIMIT_NPROC` fallback when the privilege-drop probe cannot answer keeps the extra fork headroom the probed path adds ([#1247](https://github.com/alexhawat/mergeCraft/issues/1247))
- Hardening: `git_argv` adds `--no-ext-diff`/`--no-textconv` for `log -u`, `-U<n>`, `-W`, `-L`, `-c` and bundled forms such as `-uz` ([#1248](https://github.com/alexhawat/mergeCraft/issues/1248))

- `git_fetch` validates the whole refspec, not just its source. A refspec may
  name one branch on `origin` and store it only in that branch's own
  remote-tracking ref (`main:refs/remotes/origin/main`); destinations under
  `refs/heads/`, `refs/tags/` or another branch's tracking ref, forced (`+`)
  updates, empty sides and negative refspecs are refused, so the
  repository-read tool can no longer move local branches, tags or the base a
  review diffs against (#1236).
- The macOS `sandbox-exec` profile for the MCP shell no longer grants
  `(allow file-read*)` across the host. Reads are limited to the workspace and
  an allowlist of system and toolchain paths (`/usr`, `/System`, `/Library`,
  `/opt`, `/private/etc`, temp dirs, Xcode); the user's home directory is
  denied, with the workspace re-allowed when it lives under `$HOME`. Metadata
  reads stay global for path resolution. Common per-user toolchain directories
  stay readable after the home deny (`~/.cargo`, `~/.rustup`, `~/.pyenv`,
  `~/.nvm`, `~/go`, `~/.sdkman`, `~/.bun`, `~/.local/bin`, `~/.local/lib`,
  `~/.local/pipx`, `~/.local/share/uv`), except Cargo's credentials file;
  anything else under `$HOME` (`~/.ssh`, `~/.aws`, `~/.config`,
  `~/.local/share`) stays unreadable (#1237).
- Native GitHub Actions events now carry the triggering author's permission.
  `pull_request`, `issue_comment` and `pull_request_review_comment` runs derive
  it from `author_association` (`OWNER` / `MEMBER` / `COLLABORATOR` count as
  collaborators). `workflow_dispatch`, `push` and `schedule` runs, which only
  someone with write access can cause, count as collaborators too, as do local
  runs outside GitHub Actions. A collaborator's `shell: enabled` is therefore no
  longer always downgraded to `restricted`. `push` gains the same
  non-collaborator floor as `shell`: `enabled` becomes `restricted` when a pull
  request or comment author is not a collaborator, or when an event type
  mergeCraft does not model runs inside Actions (#1238).
- The `trust.agentSandbox` tier named in the Codex sandbox remedy and in the
  run manifest's `agent_sandbox_granting_tier` is now the tightest tier that
  would grant the override (`merged-only`, then `dispatch`, then `same-repo`),
  or the configured tier when it already grants. It was always `same-repo`,
  the loosest tier, for every non-fork head (#1239).
- actionlint now lints workflow files only. Action manifests (root `action.yml`
  and `.github/actions/**/action.yml`, composite or not) were linted against the
  workflow schema, producing false Major `syntax-check` blockers; zizmor still
  covers them (#1210).
- A terminal review verdict refused by validation (for example
  `approve_with_confirmed_blocker`) no longer reads as a completed review. The
  refused call is recorded on the trajectory as `ok: false`,
  `failure_class: refused` and is not a completion claim. The run publishes its
  deterministic record naming the rejection and the remaining blockers even
  when no mode was selected, and it classifies `inconclusive` instead of
  `passed` when the provider exits 0 (#1211).
- Audit remediation hardens revision-bound approvals, checkout recovery, fork
  trust, CLI workspace and cache identity, finding attribution and severity.
  Checkout retries also discard fail-then-pass evidence from the old revision;
  malformed diffs cannot establish artifact provenance. Includes regression
  coverage, real Action-image acceptance, pinned consumer installation docs and
  release-pin maintenance (#1197, #1198, #1199, #1200, #1201).


- A review whose verdict was accepted no longer ends `failed` with
  `provider_failure` and `action failed: opencode failed` when the agent CLI then
  exits non-zero — for example after the one-time diff-coverage nudge rejected
  its first submission. The run outcome follows the accepted verdict, the model
  chain keeps that attempt instead of spending another rung on a PR that has its
  verdict, and the action fails with the driver's error only when no verdict was
  accepted. A verdict that was accepted but never reached GitHub still ends
  `inconclusive` (#1132).

- The fast-path triage diff writes a renamed or copied file the way `git diff`
  does — `diff --git a/<old> b/<new>` with `rename from` / `rename to` (or
  `copy from` / `copy to`) — and lists the source path with the changed paths. A
  file renamed from code into prose is no longer read as a prose edit of its new
  name. Prose and generated-file recognizers check both names, keeping agent
  instructions and high-stakes prose moved into docs, and source or generator
  configuration moved into generated paths, in full review. Triage evaluates
  the complete diff without applying `ignore_paths` (#1137).

- A stall diagnostic names as the likely cause only a provider error seen before
  the no-output watchdog killed the attempt. An error that arrives after the kill,
  such as the closed-socket report the kill itself produces, is shown as an effect
  of the kill, and with no earlier error the report says the cause is not known
  instead of naming one. The report also names the last stream event and when it
  arrived, so a silent reviewer leaves a trace of what it was doing (#1138).

- A reviewer that read the diff with OpenCode's native `read` tool no longer ends
  `inconclusive` with `Coverage: 0/N hunks`. OpenCode `read` parts are now recorded on
  the trajectory, so a read of `diffPath` or of a source file counts, and a read of the
  diff attests a clean approve. On a driver that reports its reads (OpenCode's and
  Codex's CLI streams), a run with no observed read now gets the one-time pre-submit
  nudge naming every range, so the reviewer can read them instead of ending
  `inconclusive`. A run with no observed read still gates, and Claude's, Gemini's and
  Cursor's native reads are still not observed.

- The in-review trufflehog analyzer can now exempt one detector in one file,
  keyed on (path, detector) like the CI SARIF emitter's allowlist, instead of
  only exempting a whole file from every detector. The URI detector is allowed
  in `src/mergecraft/tracing/redaction.py`, whose redaction patterns spell
  `scheme://user:pass@host` on purpose, which ends the recurring "URI secret
  detected" self-review finding there. Any other detector still reports that
  file (#1008).

- A blast-radius classification that was missing its inputs no longer reads as
  safe. No changed paths, or no diff statistics, now adds a `signal_missing`
  category and puts the lane at `medium` (`assisted`) or higher instead of
  `low` / `eligible`, and no repository override can lower it. An
  unrecognised risk band ranks above `critical` in `risk_at_or_above` instead
  of as `low`. The approval gate's `low_risk_passing` and `clean_pass` rows
  (both map to `auto_merge`) also require the classification to have had
  inputs: changed paths on the packet and no `signal_missing` category
  (#1056, part 1).

- An expired Codex subscription login now hands the review to the next vendor
  instead of ending it. The Codex driver marks that failure
  `failover_eligible` (move on to the next vendor) while keeping it not
  `retryable` (no retry of the same login), the model chain advances on it but
  never re-runs the dead login at the tail, and the action exposes a
  `failover_eligible` output. The self-review cascade reads that output, so a
  `neutral` packet from the dead login no longer holds the Claude backstop back
  when OpenCode Go also failed without a verdict (#1009).

- The nightly live GitHub leg polls the commit-status list for up to 30 seconds
  before asserting a just-created status is visible, instead of failing on GitHub's
  eventually consistent read (#1018).

- `test_real_meat_invocation_smoke` skips when the `meat` binary has no OpenAI
  credentials, as it already did for a missing binary (#1016).

- OpenCode Go steps with missing or zero cost use published DeepSeek V4.1
  Flash / V4 Pro token rates when their timestamps are available, including
  weekday peak windows and cached input. Reported costs are preserved; the
  review labels Go usage value and estimated amounts separately from the
  subscription fee.

- Inline review comments are published again. Every review carrying inline
  comments was rejected with a 422 (`Variable $threads ... invalid value for
  N.fingerprint (Field is not defined on DraftPullRequestReviewThread)`): the
  publisher sent its internal `fingerprint` key inside `comments[]`, which
  GitHub maps onto the GraphQL review-thread input and refuses. The recovery
  ladder then fell back to a bare COMMENT review, so the verdict and summary
  posted but every inline comment was lost. The create-review request now
  carries only `path`, `body`, `line`, `side`, `start_line` and `start_side`
  per comment; the fingerprint still reaches GitHub as the hidden marker in
  each comment body, which dedup, carryover and thread resolution read.

- One logical review no longer appears as one formal review per fallback rung
  (#1078). When Codex is available, the OpenCode Go rung is non-terminal: a
  neutral decision now records its run in the sticky progress comment and posts
  no formal review, leaving the formal review to the rung that actually decides
  the run. `success` and `failure` still publish normally. The Codex fallback
  also skips a neutral verdict whose reason names the untrusted tier — that
  tier is structurally inert (D14), so a second review can only reproduce the
  same neutral at full cost.

- A Codex run whose platform sandbox cannot start no longer claims "No review
  ran" (#1083). The review does run — through mergeCraft MCP tools — so the
  hint now names the actual capability loss (Codex-native shell tools are
  unavailable), and only the true hard-failure path says no review ran. The
  loss is recorded as structured run-scope evidence: the trajectory row is
  stamped `failure_class="environment"` and run-health carries the
  `codex-platform-sandbox-unavailable` advisory finding, visible to the gate
  and fallback chain without parsing log prose. The sandbox refusal itself is
  unchanged.

- Run-bound checkpoint recovery no longer 404s on every `pull_request_target`
  run (#1082). The Actions API resolves `{workflow_id}` by numeric workflow id
  or workflow *file name* only, but `_list_mergecraft_workflow_runs` tried the
  repo-relative path spelling (`.github/workflows/mergecraft.yml`) first and
  let its 404 abort the listing before the working file-name spelling ran. The
  file name is now tried first and a 404 on either spelling falls through to
  the next; when every spelling 404s the warning names the real cause once —
  the workflow must exist on the repository's default branch and the run token
  needs `actions: read` — instead of failing silently per run. Checkpoint
  recovery stays fail-closed (unavailable, with the reason) when the listing
  cannot be fetched. The same warnings no longer leak httpx's
  "For more information check: https://developer.mozilla.org/…" docs hint into
  the job log; HTTP failures are described as
  `HTTP <status> <reason> for <method> <url>`.

- The `git` tool no longer spends a reviewer turn on two read-only operations
  the prompts teach (#1077). `merge-base` is now on the read-only allowlist with
  the same ref/path confinement and config-flag refusal as `rev-parse`, so the
  `git diff --merge-base` workflow the prompts describe actually runs. And
  `git grep` exit 1 with clean stderr is grep's "no lines selected" answer: the
  tool returns `{output: "", noMatches: true}` as success instead of
  `✗ failed (1)`, while exit 2+ and an exit 1 that wrote to stderr stay
  fail-closed. `merge-base` gets the same treatment: exit 1 with clean stderr is
  a negative answer (`--is-ancestor` false, or no common base), not a failure.
  This is the `git`-door instance of #1027's intent-aware outcome rule.

- The approval gate accepts terminal attestation for clean reviews, and the
  gate-action table routes complete packets honestly (#1072, #1076). A review
  that runs cleanly, reads the diff, and submits terminal `approve` with zero
  typed findings now decides `success` — the validated terminal verdict plus
  observed `trajectory.read_coverage` attest the review ran, so the fallback
  guard no longer reruns the whole review on the next provider (on PR #1068
  that cost 398,912 input tokens for a 161-line lockfile diff). The one-way
  `request_changes` ratchet, untrusted-tier inertness, failed-run `neutral`,
  and advisory-only `self_assessment` are unchanged, no synthetic findings are
  created, and the legacy list-only overload keeps its empty-list `neutral`
  behaviour. On the routing side, a new `clean_pass` rule maps a blocker-free
  packet with a trusted success verdict to `auto_merge` on any lane whose
  `auto_merge_lane` is not `forbidden` — clean medium-lane packets (any
  dependency bump) no longer fall into a catch-all labelled `schema_failure`
  → `block`, while forbidden (`high`) lanes and unclassified packets keep a
  human in the loop. The catch-all is re-scoped so `schema_failure` fires
  only on structurally absent evidence, and a complete packet with no
  automated route falls to the new `needs_human_review` →
  `require_human_review` (unknown is never green, #1056).

- Honest trajectory plumbing for the run record (#1073, #1074, #1075). A tool
  call a guard refuses (read-only allowlist, path confinement, config-flag or
  mode guard) now records `ok=False` with `failure_class="refused"` on the run
  trajectory — the typed `ToolRefusedError` crosses the
  `mcp/shared.py::execute` seam as a tagged error result, so the agent still
  sees an ordinary tool error while run-health stops reading refusals as
  successes. The merge evidence packet schema moves to `1.16.0` and the
  trajectory record schema to `1.2.0` for the new enum value. A run whose
  agent self-publishes via `create_pull_request_review` no longer gets a bogus
  `missing-completion-signal` finding: the packet renders inside the terminal
  call, before the call lands on the trajectory, so the audit now counts the
  in-flight terminal call as the completion signal. And the run record's
  **Review cost** row is honest on those self-published reviews: `agent`
  renders elapsed-so-far instead of `0s`, `publish` is omitted when the run
  has not stamped it yet (its stamp lands after the record renders), and
  sub-second phases render with one decimal (`0.1s`) — or `<0.1s` — instead of
  rounding to `0s`.
- A re-review after a change request now resumes from its checkpoint: the run-bound
  identity accepts completed `success` and `failure` runs that carry an evidence
  artefact, so the next review no longer starts from round 0 and reads the whole
  pull request again. Cancelled, skipped, unfinished and artefact-less runs are
  still ignored (#926).
- A post-run finalize failure is logged at `warning` with the exception type and
  the run record names it (`finalize_failed: <Type>`) instead of reading as a
  missing verdict; the run still fails closed (#903).
- A review thread whose comments were not all read is never auto-resolved (#902).
- Finding outcomes: an outdated but unresolved review thread is now `stale`, not
  `fixed`, so the advisory fixed rate is no longer inflated by lines that merely
  moved; resolved threads still count as fixed (#1251).
- The trace `attrs` cap now measures the whole payload as UTF-8 JSON bytes
  (64 KiB) instead of the character length of top-level strings, so multibyte,
  nested and many-small-value payloads are truncated too (#1252).
- Line-budget scope reduction and the offline diff summary read `diff --git`
  paths that contain spaces or quotes correctly instead of splitting on
  whitespace (#1253).
- A mid-battery skip in the Jev claim judge keeps the attestations collected for
  earlier claims and marks the result `partial` (#1254).
- Entropy redaction no longer turns absolute CI paths with ordinary segments
  (`/home/runner/work/repo/src/app/module.py:12`) into `<redacted>.py`; a
  segment that looks like a secret is still redacted (#1255). Word-shaped
  camelCase directory names such as `mergeCraft` count as ordinary segments
  again after the camelCase rule moved out of the identifier pattern (#1232).
- `mergecraft review` restores its telemetry, tracing and trust-tier environment
  overrides even when loading repository settings raises (#1256).
- The git tools that advertised an unused `repo` argument no longer do: the
  read-only `git` tool now honours it (registered checkouts only, unknown repo
  is an error) and the fetch, push, tag, delete-branch and commit tools drop it
  from their schemas and always act on the primary checkout (#1258).

### Security

- `establish_review_scope` only reads a `diff_path` that resolves, symlinks
  followed, under a registered checkout, the run tmpdir or
  `MERGECRAFT_TEMP_DIR` (#1257).
- The Action `cwd` input is confined to `GITHUB_WORKSPACE`: `../..` or an
  absolute path outside it is a configuration error (#1259).
- The git askpass helper writes the token single-quoted via `printf '%s\n'` and
  rejects tokens with control characters, so shell metacharacters in a token are
  never interpreted (#1260).

### Breaking

- A review run whose agent submitted a terminal verdict now ends `inconclusive` (a
  `neutral` `mergecraft` check) when any changed hunk never reached the reviewer —
  a files-API diff over the page cap, a file GitHub sent no patch for, or a hunk
  absent from the delivered diff — where it used to read `success`. A Critical or
  Major finding still makes `mergecraft-approval` conclude `failure`, and one
  pre-submit nudge names the unread ranges so the reviewer can read them and submit
  again. **Fix:** set `review.coverage.onIncomplete: warn` to keep the verdict and
  only report the gap (#940).

### Security

- Config: a config file that cannot be parsed now fails the run closed (`config parse error: <file> (<ErrorType>)`, no YAML values echoed) instead of warning and loading defaults ([#1249](https://github.com/alexhawat/mergeCraft/issues/1249))
- Config: duplicate mapping keys at any depth are rejected, naming the key and line, instead of silently keeping the last value ([#1250](https://github.com/alexhawat/mergeCraft/issues/1250))

## [0.1.0a4] — 2026-10-29

> **First published release.** Nothing before this version was ever uploaded:
> the package did not exist on PyPI, and `0.1.0a1` was an Action-only tag. This
> candidate also supersedes the withdrawn `0.1.0a3`, so everything recorded under
> that heading applies here too.

### Breaking — action required

- **The PyPI distribution is named `mergecraft-action`.** `merge-craft` cannot be
  registered: PyPI refuses a new project whose name differs from an existing one
  only by separators, and an unrelated `mergecraft` project already exists.
  **Fix:** install with `uv tool install mergecraft-action`, or the pinned git
  form. The CLI binary, the import package, the MCP server name, the Action name
  and the container image are all unchanged.

- **The withdrawn `0.1.0a3` changes ship here.** Every break recorded under
  [0.1.0a3] below also applies to this release: the removed Nous Portal provider,
  `trust.agentSandbox` validation, the `model_pin` default, fail-closed tracing
  values, the removed MCP webhook route and provider helpers, refused
  `dispatch: ensemble` / `shadow`, the `sarif_upload` default, progress-comment
  identity, the enterprise audit root, and the CLI exit-code table. **Fix:** read
  that block once; it is the upgrade path from `v0.1.0a1`.

- **Review prompts changed.** The reviewer is now told how long it has, runs
  analyzers before reading source, investigates the riskiest hunks first, and
  reads code by locating it with `grep -n` and then reading the range, instead of
  pulling function bodies through `git grep` context. The prompt version hash
  changes, so two reviews of the same diff can reach different verdicts than
  before. **Fix:** none for consumers; anything that pins a rendered prompt
  digest must be re-baselined.

- **Analyzer configuration no longer comes from the pull request being
  reviewed.** `analyzers.*` resolves from the operator-owned base snapshot or the
  base commit, and a head-side edit is reported as self-silencing instead of
  applied. **Fix:** land analyzer-config changes in their own pull request; they
  take effect from the next one.

- **`list_check_runs` returns a reduced shape:** id, name, status, conclusion,
  output title and `check_suite_id` only. **Fix:** call `get_check_suite_logs` for
  a run's output text.

- **`git grep` with more than ten lines of context returns matching lines
  only**, plus a note to read the file at that line, and options placed after the
  pattern are moved in front of it. **Fix:** read the file with the ranged read
  tool; context of ten lines or fewer is unchanged.

- **A typo in a tracing sink now fails configuration.** `tracing-to`,
  `MERGECRAFT_TRACING_TO` or `--tracing-to` with an unknown value ends the Action
  as `configuration_error` and exits with the configuration code on the CLI,
  naming the variable and the value. **Fix:** correct the value; with tracing off
  a typo is ignored with a warning.

- **Evidence packet schema `1.15.0`, trajectory schema `1.1.0`.** Both add
  optional fields only. **Fix:** accept the new fields if you parse the packet
  strictly.

- **The wheel no longer ships five checkout-only modules** (`scm.webhooks`,
  `evidence.shadow_compare`, `evals.human_batch`, `evals.skill`,
  `agents.catalog_docs`), which are reached only from Make targets, scripts and
  tests. **Fix:** import them from the repository rather than the installed
  distribution.

### Known limitations

- Evaluation is structural replay only, not live detection. No
  human-adjudicated, calibrated or benchmarked result ships in this release, and
  the notes below claim none.
- Bounded file-group fan-out is a planner only. It is not wired into
  server-side roster dispatch, so a large diff still runs as one reviewer.
- Datadog prices LLM spans only from its own model catalog, so an OpenCode Go
  review on `deepseek-v4.1-flash` shows no cost there even though mergeCraft
  records one.
- OpenCode's code-mode `fetch` can still read local files and the network
  regardless of `webfetch: deny`; no OpenCode setting turns it off while keeping
  MCP tools reachable.
- This is an alpha. The `:latest` and `:analyzers` image tags are promoted from
  the default branch only, so this release does not move them.

### Added

- OTLP traces read properly in Datadog LLM Observability. Every exported span
  carries `gen_ai.conversation.id` (the review's trace id), so each review is one
  session and pipeline spans (analyzers, phases, publish) are no longer dropped;
  OpenCode plugin spans join the same session. When the sink sends
  `dd-otlp-source: llmobs`, pipeline spans without a GenAI operation get
  `invoke_agent` (run root) or `execute_tool` and `gen_ai.provider.name=mergecraft`,
  which Datadog requires on every span; tool payloads move to
  `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result` so tool spans show their
  input and output; and the per-process `session_id` is renamed
  `mergecraft.session_id`. Other backends do not get these changes. Datadog prices
  LLM spans only from its own model catalog, so a model it does not list (such as
  `deepseek-v4.1-flash`) shows no cost there.
- OpenCode 2.x runs can trace the inside of the session: set
  `MERGECRAFT_OPENCODE_OTEL_PLUGIN` to an
  [opencode-plugin-otel-v2](https://github.com/alexhawat/opencode-plugin-otel-v2)
  checkout and, when tracing exports to `otel` or `logfire`, each run adds one span
  per LLM step (tokens, cost, finish reason) and per tool call, nested under the
  review's `mergecraft.agent.run` span. The plugin's prompt and tool bodies follow
  `tracing.content` and the untrusted-tier cap; its header values travel in env
  vars, never in the on-disk OpenCode config. Operator-only: repository config
  cannot enable it. Only a plugin whose runtime entry (the file `package.json`
  names, not unbuilt source) reads `captureContent` is loaded. Encoded OTLP env
  headers are decoded as the Python exporter decodes them, so the plugin
  authenticates with the same credential, and every forwarded credential is handed
  to the plugin's redactor so one echoed into a prompt or tool body is masked.
- Reviews now read the materialised diff first. Review and IncrementalReview
  render a shared hard instruction: `diffPath` (or `incrementalDiffPath`) is the
  authoritative review scope, `git diff` / `git grep` / `git log` must not be used
  to reconstruct it, and independent reads are batched into one turn. The
  instruction is rendered for every consumer, not only this repository's
  workflow.
- Diff line-range coverage: `changed-unread-file` reports the unread added-line
  ranges (`path:start-end`) instead of whole files, and `submit_review_verdict`
  nudges once with exactly those ranges before accepting the verdict. Reads of
  the diff file itself count (recorded as `diff_read_path` / `diff_read`), and a
  run with no observed reads is *unknown*, not unread. Deletion-only and
  mode-only sections stay in scope and are named until their path is read.
- A no-output/idle watchdog for CLI agent drivers: no parsed event for
  `agentIdleTimeout` seconds (default `900`, `0` disables) kills the attempt and
  reports the idle span, event count, whether the model produced output, the last
  provider error, and the stderr tail. The attempt still fails so the chain can
  advance, but the run outcome is `infra_error`, not a failed review.
- `run_metrics` on the merge evidence packet (schema `1.15.0`): tool calls, read
  calls and read turns, distinct files read, diff line counts, elapsed by phase
  (setup / analyzers / agent / judge / publish), and the last watchdog
  diagnostic. The deterministic run record renders it as a **Review cost** row.
  Measurement only — it never feeds the gate.
- Bounded file-group fan-out planner (`review/file_group_fanout.py`): a large
  diff splits into at most six balanced read-only groups, and a failed group is
  recorded rather than raised. Planning and degradation only; it is not wired
  into server-side roster dispatch in this release.
- Analyzer disposition ledger: every raw analyzer hit gets a stable `hit_id` and
  ends `kept`, `merged`, `downgraded` or `dropped:<stage>` with a required reason.
  The merge evidence packet (schema `1.14.0`) carries the ledger, per-stage counts
  and the baseline-suppression audit rows that were previously only logged; the
  pre-merge Analyzers row reads like `ruff 14 raw → 3 kept (9 out_of_scope, 2
  baseline)`. SARIF ingested via `ciEvidence.sarifArtifacts` follows the same
  contract (#941).
- `self-silencing` analyzer (in-process, every trust tier, no shell): reports added
  suppression markers (`# nosec`, `# noqa`, `// eslint-disable-next-line`,
  `#[allow(..)]`, `//nolint`, …) with the rule codes they silence, and loosening
  edits to `.mergecraft/config.yaml`, `ruff.toml` / `pyproject.toml`, ESLint config
  and scanner ignore files. Edits to `.mergecraft/**` and analyzer/linter config
  also keep a PR out of the `eligible` blast-radius lane (#942).
- `analyze_ci_failures` reads the base branch's recent runs itself, so a
  same-fingerprint base failure clears a failure as pre-existing with no
  agent-supplied arguments; the runs it used are recorded in the result and the CI
  evidence. A passing or unrecognised base status never clears one (#891).
- Opt-in `gherkin-lint` catalog analyzer: syntax and structure lint for changed
  `.feature` files, run through the repo's own pinned `gherkin-lint`. Disabled by
  default because the catalog has no managed npm runtime; enable it with
  `analyzers.overrides.gherkin-lint.enabled: true` (#854).

### Changed

- Review and IncrementalReview now tell the agent how long it has and how to
  read code, so a large review submits a verdict inside its timeout instead of
  being killed while still exploring. The prompt states the agent deadline (run
  timeout minus setup time) with checkpoints: stop exploring by ~60%, submit by
  ~80%. It also makes `run_analyzers` and `run_static_checks` the first calls
  after `checkout_pr`, reads code with a plain `grep -n` plus a ~60-line ranged
  read, forbids repeating a call whose result is already in context or retrying
  variants after a tool error, and runs `git diff <base>...HEAD` once when the
  diff file is refused. Triage now investigates the riskiest hunks first instead
  of pulling "as much context as you need". Because the agent has no clock, once
  it passes 60% of its deadline each successful tool result on the review
  agent's MCP route carries a notice such as `⏱ 16 of 25 min used, about 9 left:
  stop exploring…`, switching to "submit the verdict now" at 80%. A JSON-object
  result gets it as a `timeBudget` field (so OpenCode 2.x code mode, which
  parses the joined text, still sees valid JSON); a plain-text result gets a
  trailing line. Trajectory records and traces never see the notice. The
  verifier route and runs with no timeout get none, and the prompt shows a
  neutral line instead. `compute_modes` takes an optional `time_budget_minutes`.
  The prompt version hash changes.
- Incremental re-review is the default on a re-review. `checkout_pr` now computes
  the range whenever a prior reviewed sha is recoverable — not only when
  `select_mode` chose IncrementalReview — and reports
  `incrementalDiffStatus` (`ok` / `empty` / `unavailable`) with
  `incrementalDiffReason` and `lastReviewedSha`. When the range exists it is the
  review scope; the full diff is for anchoring only.
- A PR's own `analyzers.*` configuration no longer applies to its own review. The
  analyzer settings (`enabled`, `overrides.<id>.enabled`, the `antislop` `rules` and
  `ignore`, `baseComparison`, `inlineBudget`, `impact`) are resolved from the PR's
  base — the operator-owned base snapshot, or the base commit's
  `.mergecraft/config.yaml` — and a head-side change is reported by
  `self-silencing` instead of applied. A symlinked or unreadable base config falls
  back to built-in defaults with a named reason. **Fix:** land analyzer-config
  changes in their own PR; they take effect from the next PR on (#942).

- A run whose analyzer disposition ledger is open — a pipeline stage lost a raw hit
  without recording why — now ends with a `neutral` approval conclusion instead of
  possibly `success`, and a run-scoped finding names the orphaned hits. A blocker
  still outranks it. **Fix:** none for consumers; the finding names the stage to fix
  (#941).

- A mistyped tracing sink (`tracing-to`, `MERGECRAFT_TRACING_TO` or `--tracing-to`
  with a typo such as `logfier`) now ends the run as `configuration_error` on the
  Action and exits with the configuration code on the CLI, naming the variable and
  the value. It used to end as `infra_error`, the outcome of an unclassified crash.
  With tracing off the typo is still ignored and now logs a warning (#930).

- The per-file `changed-unread-file` run-health finding is `Minor` instead of
  `Major`: still listed in the record, and the gate is unchanged — `gate_policy`
  still maps `changed-unread-file` to `request-changes` by rule id, so this only
  stops a Major row per unread file from burying the change-scoped reasons (#885).

- The Release workflow now dispatches CI/CD on the release branch it prepares, and
  CI/CD's `build-dist` job accepts a dispatch on a `release/*` branch or a `v*` tag, so
  the workflow path produces the `artifact-python-dist` the publish step needs. Its
  publish gate names the real approval, `craft publish` with publish credentials, instead
  of a label that nothing acts on (#1004, #1005).

- The wheel no longer ships five more checkout-only modules (`scm/webhooks.py`,
  `evidence/shadow_compare.py`, `evals/human_batch.py`, `evals/skill.py`,
  `agents/catalog_docs.py`); each is reached only from Make targets, scripts or tests (#947).

- The review job joins the `codex-subscription-auth` concurrency group, so two consumers
  never refresh the Codex subscription login at once. GitHub keeps one pending job per
  group, so a third queued review replaces the pending one and needs a re-run (#882).

- Every `actions/checkout` that does not push sets `persist-credentials: false`, and the
  redaction module's own URI patterns no longer flag in the CI secret scan, which allows
  one detector in one file rather than the whole file (#885).

- The structural eval baseline is regenerated with the three multi-round cases
  replayable: `inconclusive_rate` falls from 0.0816 to 0.0204 (3 of 49 cases were
  permanently blocked), with no behaviour change (#892).

### Fixed

- The `tracing` extra moves to OpenTelemetry 1.45.1 (semantic conventions
  0.66b1), which fixes CVE-2026-114603 in `opentelemetry-api` 1.44.0. That
  advisory failed the `pip-audit` security check on every build. The 1.45 OTLP
  exporter keeps its headers on its HTTP client, lowercased and merged with
  `OTEL_EXPORTER_OTLP_*` settings, so reuse of an exporter for the same endpoint
  and headers is matched case-insensitively against those; two new transitive packages,
  `opentelemetry-exporter-http-transport` and `opentelemetry-exporter-otlp-common`,
  come with it.
- A review whose verdict carries a finding with a model-made fingerprint
  (`ci-static-llms-full-stale`) now prints. The verdict back-fill stored the slug
  as-is; the CLI then failed with "fingerprint must be lowercase hex" before
  rendering anything. Back-filled fingerprints are now normalized to hex, as on
  every other path into the run. A slug that carries a path
  (`tests/x.py:30:pin-the-cli`) is hashed too, instead of failing the run with
  "unsafe fingerprint value" (exit 30) after its verdict was recorded.
- OpenCode reviews can read a tool result that was too large to return inline.
  OpenCode saves the full text under the run's data directory and tells the model
  to read it there, but the agent was denied that whole directory to keep the
  auth store out of reach, so every such read failed. The `tool-output` folder is
  now readable; the auth store beside it stays denied.
- A failed span exports with OTel status `ERROR`. Spans mergeCraft marked as failed
  went out as `unset`, so Datadog LLM Observability and Logfire counted a crashed
  run as a success and only its `error` attribute said otherwise.
- A trusted review whose repo gates write build output (`dist/`, regenerated docs)
  no longer fails its integrity check. `run_static_checks` re-pins the read-only
  baseline around in-place gates, as `checkout_pr` does, after first checking that
  nothing changed before the call — so an agent's own writes still fail the review.
- Model names, review ids, session ids and tool-call ids in trace attributes are no
  longer masked as `<redacted>`. These identifier attributes still pass the explicit
  secret patterns (`sk-…`, `ghp_…`, …) but skip the entropy heuristic, which read
  `deepseek-v4.1-flash` and 32-hex ids as secrets.
- OpenCode reviews can read the review diff with the `read` tool. The diff sits in
  the run's temp dir, outside the checkout, so `read` refused it and agents fell
  back to workarounds. The temp dir is now readable, except its isolated auth store,
  config dir and scratch HOME, but only when this run created it with `mkdtemp`: an
  operator-chosen or shared directory passed as the run's temp dir is not opened.
- OpenCode reviews no longer load the reviewed repository's own OpenCode config
  (`opencode.json`, `.opencode/`). A repository could otherwise add MCP servers or
  plugins — code that runs inside the reviewer — including from a fork PR.
- A review whose static checks run repo linters in the checkout no longer fails its
  integrity check: `.ruff_cache`, `.mypy_cache` and `.pytest_cache` are skipped like
  `__pycache__`.
- OpenCode reviews no longer load the operator's global OpenCode config. Each run
  gets an empty `OPENCODE_CONFIG_DIR`, so global MCP servers, plugins and agents
  stay out of the review — and a global MCP server named `mergecraft` no longer
  shadows the run's own server, which had left the agent without
  `submit_review_verdict` and every local review ending in "no terminal review
  verdict".
- An offline review (`mergecraft review`) that stops without a verdict is no
  longer told to commit and push a dirty working tree. The dirty-tree check now
  skips offline reviews even when no mode was selected, so the retry turn asks
  only for the missing verdict.
- OTLP spans now satisfy Datadog LLM Observability's GenAI checks.
  `mergecraft.agent.run` and `agent.attempt` carry
  `gen_ai.operation.name=invoke_agent`, the agent span splits its model slug into
  `gen_ai.provider.name` / `gen_ai.request.model`, OpenCode's `llm.call` carries
  `gen_ai.operation.name=chat`, and every exported span with the deprecated
  `gen_ai.system` also gets `gen_ai.provider.name`.
- A read-only review of a checkout with an in-tree virtualenv no longer fails its
  integrity check when Python writes bytecode mid-review: the checkout hash now
  skips `__pycache__` directories at any depth, as it already did `node_modules`.
  The rest of a virtualenv stays hashed.
- Reviews on PRs with many CI checks no longer stall and time out after listing
  check runs. `list_check_runs` now returns each run's id, name, status,
  conclusion, output title and `check_suite_id`, instead of GitHub's full
  check-run objects with their complete output text. One listing on a ~35-check
  PR had returned 184 KB to the reviewer, slowing every later turn to 90–120 s.
  Full check output is still available from `get_check_suite_logs`
- Reviewers no longer read whole functions through `git grep` context. When a
  `git grep` asks for more than 10 lines of context (`-A`/`-B`/`-C`, `-NUM`,
  `-W`, or an abbreviated long form such as `--after=60`, including inside a
  `(`…`)` expression), the `git` tool returns just the matching lines with their
  line numbers and a note to open the file with the read tool at that line.
  Options placed after the pattern are moved in front of it instead of failing
  with exit 128. A refused `sed`/`cat`/`head`/`tail`/`awk` call now names the
  read to use instead. In the same timed-out review, 102 `git` calls returned
  437 KB, mostly from `git grep -A 40..70`
- A workspace review no longer fails closed with "checkout integrity failure:
  tree changed during read-only review" when dependency prep creates nested
  `node_modules`. pnpm/yarn/npm lay down `apps/api/node_modules`,
  `packages/*/node_modules` and the like (and pnpm can drop `.pnpm-store`
  in-tree), all after the integrity baseline, so the hash now prunes those
  directory names at any depth instead of only at the checkout root. A nested
  `.git` metadata directory is pruned the same way.
- The reviewer's read-only `git` tool now refuses abbreviated spellings of the
  options it already blocks, plus a few that do the same harm. Git accepts any
  unique prefix of a long option, so `git grep --no-inde` went through as
  `--no-index` and `git cat-file --tex` ran a configured textconv filter. Which
  prefixes are unique depends on the git release: on the git 2.39 in the
  review image, `cat-file --filter` is short for `--filters`, while on git
  2.53 it is a different option. So every prefix of a blocked option is
  refused, apart from a short list of exact names checked on both releases.
  The
  tool also refuses `grep --untracked` / `--no-exclude-standard`, because they
  searched untracked and ignored files, including mergeCraft's own scratch
  (the askpass helper, OpenCode's `auth.json`) whenever the run temp dir is
  inside the checkout. It refuses `blame --contents` / `--ignore-revs-file`,
  which read a file the tool cannot confine; `cat-file --filters`, which runs a
  smudge filter; and `ls-remote --upload-pack` / `--exec`, which run a named
  command. These options are refused anywhere in the arguments, including after
  `--`, because git reads a `--` that follows `-e` as a pattern rather than
  the end of options (`git grep -e -- --untracked` still searched untracked
  files).
- Multi-reviewer rosters now dispatch secondary reviewers server-side when the
  primary harness never spawns them, fail closed with a clear error when a
  secondary cannot reach its provider, and always emit the `⏱ LLM review time`
  line (including a zero-second fallback when no LLM calls were timed).
- Exporting findings no longer crashes when a model supplies a slug-style
  `fingerprint`; non-hex values are normalized to a stable lowercase hex digest
  at write time.
- `submit_review_verdict` drops malformed draft findings instead of rejecting
  the whole terminal submission when one pre-recorded row is invalid.
- Checkout integrity hashing skips nested `node_modules`, `.pnpm-store`, run
  `evidence`, and OpenCode session dirs at any depth so harness scratch writes
  during read-only review no longer trigger exit 12.
- A review whose agent submits a verdict without calling `select_mode` now
  publishes the formal review with the run record. Before, the PR got only a
  short progress comment, with no tokens, cost, timing or findings, whenever the
  OpenCode Go rung answered and the Codex fallback did not run.
- The run record on the formal review shows the `Cost:` line. Cost was computed
  but only reached the step summary.
- A recorded review verdict that reaches no GitHub review now says why. The run
  publishes the verdict it recorded, and when it does not — the shadow protocol,
  a run that is not in a review mode, or a submission the post-run re-validation
  rejected (conflicting, stale-attempt, or semantically invalid) — the reason is
  recorded on the run's trajectory instead of returning silently. The row is
  stamped `failure_class: declined`, so the trajectory auditor does not report the
  skip as an `ignored-tool-error`. PR #1017's
  Codex rung recorded `request_changes`, published no review, and left nothing in
  the evidence packet to distinguish that from never having tried; only the
  failing `mergecraft-approval` check showed it.
- agentsec no longer reads a changed instruction or MCP manifest whose symlink
  resolves outside the repository root; the refusal is logged and reported as a
  named skip when it was the only candidate (#851).
- Numeric metadata such as `input_tokens=120` survives log redaction; credential
  named keys and long numeric runs still redact (#877).
- Trusted-tier catalog analyzers drop to the agent UID on the root backend, with
  their scratch tree and the baseline worktree handed to that UID first; an
  unlandable drop reports `unavailable` instead of running as root (#878).
- `run_checks` refuses to run an untrusted static gate without a sandbox context,
  whatever `shell` says, so the executor fails closed even if a caller does not
  (#887).

- A retired Codex subscription login ("refresh token was already used") is reported as
  `infra_error` with *reviewer credential expired - re-authenticate* and the commands
  that fix it, in the check summary and the run record, instead of an unexplained red
  check. There is no scheduled canary: probing the login refreshes it (#922).

- The carry-over workflow no longer falls back to the forgeable `github-actions[bot]`
  login for `MERGECRAFT_REVIEWER_BOT_LOGIN`; an unconfigured App yields an empty login (#913).

- `config tracing` lists the config files it read and agrees with `doctor` and
  `config explain` about `config.local.yaml` and a missing `MERGECRAFT_CONFIG`; the
  flag, environment and YAML precedence is unchanged (#919).

- A column-0 comment between items of a top-level sequence no longer leaves trailing
  items behind when the comment-preserving config writer replaces the key (#920).

- Commands Codex, Claude and OpenCode run natively are recorded on the trajectory with
  their exit status, so a failing command, a timeout and a later passing re-run are
  visible to the auditor; environment and transient failures carry a named class.
  Recording never fails a tool call and changes no review decision (#858).

- `tests/mcp/test_rpc.py` no longer leaves a fake package version cached for later
  tests (#1006).

## [0.1.0a3] — 2026-10-17

> **Never published.** This candidate was prepared and withdrawn before it
> was uploaded: PyPI carries no release for it, and there is no tag and no
> GitHub release. Its changes ship in `0.1.0a4` above, whose
> **Breaking — action required** block lists them.

### Breaking — action required

- The built-in Nous Portal provider is gone: the `nous/...` catalog models,
  `mergecraft auth nous`, and the flat `NOUS_API_KEY` credential no longer
  exist, so a `nous/...` model now fails as an unregistered provider. **Fix:**
  register Nous (or any OpenAI-compatible endpoint) under `providers:` in
  `.mergecraft/config.yaml` with `url`, `harness: opencode` and an `envIndex`,
  and pass the key as `LLM_PROVIDER_<N>_API_KEY`. See
  [docs/authentication.md](docs/authentication.md).

- An invalid `trust.agentSandbox` value (for example `off`, a bare `false`, or a
  typo like `nevr`) now fails configuration validation instead of quietly
  becoming `dispatch`. **Fix:** set one of `never`, `merged-only`, `dispatch`, or
  `same-repo`; the four tiers still normalize whitespace and case.

- The `model_pin` action input no longer carries a default. Leaving it unset
  follows the repository's `modelPin` setting, and an explicit `disabled` now
  overrides a repository `modelPin: true`. **Fix:** leave `model_pin` unset to
  follow the repository, or set `enabled` / `disabled` explicitly; the previous
  `disabled` default meant an unset input could never override the repository.

- Settings the standalone runtime does not consume are accepted but now warn
  once when set to a non-default value: `gates.thermostat`, `tracing.redaction`,
  `stopScript`, `blastRadiusOverride`, `operatorPipeline`, and `autoMergeEnabled:
  true`. **Fix:** none required — the values still parse and round-trip; remove
  the key if the warning is unwanted.

- A malformed tracing environment variable or tracing Action input — the enable
  flag, the region, the content level, or the untrusted-content export — now
  fails configuration instead of being ignored. A typo such as `flase` used to
  drop the value and let a lower layer's more permissive one win; the run now
  fails closed as a configuration error naming the variable, and never prints
  its value. **Fix:** correct the spelling; `MERGECRAFT_TRACING_REGION` still
  accepts `us` and `eu`.

- The MCP server no longer mounts a webhook endpoint. **Fix:** none — a signed
  delivery was verified but processed nothing, and its replay window could never
  fire, so no review path consumed the route.

- Provider circuit-breaker, health, budget and routing-eval helpers that no
  review path called are removed. **Fix:** none — none of them was reachable
  from a review.

- Four context-retrieval modules no review path imported are removed. **Fix:**
  none — no review path imported them.

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not
  implemented instead of being accepted and ignored. **Fix:** use a `dispatch`
  mode that is implemented; `ensemble` and `shadow` are refused.

- The `sarif_upload` action input no longer declares a default, so an unset
  input reaches `.mergecraft/config.yaml`'s `analyzers.sarifUpload` as
  intended. **Fix:** set `sarif_upload` (or `analyzers.sarifUpload`) explicitly
  if you relied on the implicit `disabled`.

- Progress comments are recognised by the identity that published them, not by
  any bot. When neither the expected publisher nor a trusted self-review sticky
  id is available, the run creates a new progress comment — and with it a fresh
  ledger — rather than adopting a comment posted by the shared Actions bot.
  **Fix:** none required; pin the reviewer App (or the self-review workflow) if
  you want the existing sticky adopted.

- Enterprise audit events are no longer written to `.mergecraft/audit.jsonl`
  inside the workspace by default. **Fix:** set `MERGECRAFT_AUDIT_ROOT`, or read
  from the new default location.

- Every exit under `src/mergecraft/cli/` now routes through named constants and
  usage errors exit `2`. **Fix:** scripts that branched on exit code `1` for
  generic CLI failures must follow the new table — most former `1` paths now
  exit `30`; see [`docs/EXIT-CODES.md`](docs/EXIT-CODES.md).

### Known limitations

- Evaluation in this release is structural replay only, not live detection, and
  no human-adjudicated, calibrated or benchmarked result ships in it.

Full long-form history, including the entries condensed or omitted here:
[docs/dev/changelog-archive.md](docs/dev/changelog-archive.md#010a3--long-form-entries).

### Added

- Code-measured LLM review generation time in every posted review record and CLI JSON/text output (`⏱ LLM review time: …`), including per-reviewer breakdown when multiple reviewers run (#983).

- `mergecraft agent assign-model` on the committed roster registers missing models, auto-wires harness providers into `mergecraft.yml`, and updates `with.model` for p0 assignments.

- Human golden-batch manifests declare their own batch id and case list, so a later batch can be reviewed without a code change; the first batch's nine case ids stay pinned as a frozen fixture.

- Behaviour-verification reports record which driver produced them — `cdp`, `stub`, or unset when not recorded — so a report says whether its page came from a real browser or the non-browser fallback.

- `docs/opencode.md` documents the integration: engine selection, commands, subagents, V2 MCP wiring, JEV scope, and Logfire tracing.

- `mergecraft verify-behavior` can reproduce a bug or check a running app and write a versioned report under `.mergecraft/artifacts/`.

- A versioned behaviour-verification report (`schema_version` 1.0.0) records what was observed, which criteria passed, and what blocked the run — without turning those results into code findings (#61)

- Reviews can ingest declared coverage receipts and report change-risk scores on the functions the PR actually touched, advisory by default (#714)

- Opt-in Jev / System One client (`jev.enabled`, default off) with cost accounting, a kill-switch, and GenAI spans; a missing TypeSafe key records a skip and does not fail the review (#728)

- Parallel shadow judge grades review findings and prose against their cited evidence without replacing the reviewer (#728)

- `mergecraft review --tracing-content` and Action `tracing-content` set the capture level without editing YAML

- Multiple reviewer-role bindings run on one PR; findings merge by path/body/line and produce exactly one verdict with strictest severity winning

- `mergecraft workflow sync` keeps `.github/workflows/mergecraft.yml` auth wiring aligned with roster models; unwired providers fail at CLI write time and at run start

- First `mergecraft provider auth` after `init` seeds `agents.reviewer` p0 so review works with no third command

- `docs/agent-roster.md` — operator guide for slots, named agents, local scope, multi-reviewer verdict rules, and the run-start trust snapshot

- `establish_review_scope` — evidence-backed second route into review scope when a materialized diff already describes the PR head

- Read-only git MCP verbs (`show-ref`, `for-each-ref`, `ls-remote`, `config --get`) and `checkout_pr` parameter aliases (`pr_number`, `issue_number`)

- Agent stream logs render human-readable lines instead of dumping raw provider NDJSON.

- `Finding.scope` (`change` | `run`, default `change`) and `FindingSource` `"trajectory"` so trajectory auditor rows are attributed as process evidence, not PR defects

- Job step summary (`GITHUB_STEP_SUMMARY`) written from `_publish` with outcome, pre-merge rows, and findings — capped at GitHub's 1 MiB with the header intact

- Evidence packet persisted to a workflow artifact on every review rung (`if: always`, 30-day retention) so the packet survives runner teardown

- `MERGECRAFT_ACTION_SHA` workflow variable — one pin definition shared by all three review rungs, with `make action-pin-check` enforcing staleness and rung parity (#532)

- Action image digest pin gate (`action-image-digest-check`) and halved `wait-for-ci` poll cadence (20s → 10s, #528)

- `mergecraft tracing logfire wire-workflow --region us|eu` writes `MERGECRAFT_TRACING_REGION` into the wired step's `env:`.

- `mergecraft provider disable <label>` clears a provider's credentials so GitHub CI stops using it, without hand-editing secrets or workflow YAML.

- `mergecraft provider enable <label>` names the authenticate half of that toggle; it delegates to the existing `provider auth` flow (#520)

- Offline public MCP tool-selection eval corpus under ``evals/mcp-public/`` with fixture prompts and deterministic scorer ``mergecraft.evals.mcp_public`` (no live LLM in ``make test``)

- `make action-pin-check` also measures the pin against the default branch's own tip, not just against the other branch's pin.

- `make action-pin-check` guards the self-review Action pin against drift.

- Open-PR finding ledger in the sticky progress comment — `mergecraft findings ledger --pr N` inspects inline, deferred, withdrawn, and unpublished fingerprints without filing GitHub issues

- Optional recall pass (`review.recallPass`, default off) dispatches `mergecraft-recall` after aggregation; novel findings always publish in the deferred lane

- Optional round-aware budgets (`review.roundBudgets`) scale token, cost, tool-call, and subagent ceilings by review round; defaults stay flat until opted in

- Lens execution recording on `ToolState`, review metadata, and merge-evidence packets; findings may carry optional `lens` attribution

- Collateral lists on `Critical` and `Major` findings name callers, tests, and other files that must move with the fix; inline comments render them under **Also update:**

- `make lint` checks that jobs calling local reusable workflows grant at least the permissions the callee declares, catching ``startup_failure`` permission mismatches at authoring time (#425)

- Consumer glossary (`docs/glossary.md`) — plain-language definitions for trust tier, typed findings, blast radius, and related landing-page terms; manifest row and `llms.txt` entry.

- Runnable CLI example trees under `examples/cli/` (local diff, branch range, patch file, and `--agent` JSONL) with `make cli-examples` / `cli-examples-check` and `docs/cli-examples.md` tour page

- Agent-loop reference workflow (`docs/agent-loop.md`) for `mergecraft review --agent` (#383)

- CLI and GitHub Action runs now enter one review engine over one immutable snapshot (#380)

- `mergecraft explain`, `ask`, and `replay` plus `run inspect` / `run diff` print output-only change, line Q&A, and stored-run views (#377)

- `mergecraft review --agent` negotiates protocol version against CLI JSON `schema_version` (both fields kept, aliased), reports retryable mismatches, and names token/cost/tool-call budgets (#379)

- `mergecraft review --agent` streams the first finding before the verdict; `--use-cache` and `--resume` reuse a local result cache; cancelling a review cleans up child processes (#378)

- `llms-full.txt` generated concatenation plus docs pin/link gate (`make llms-check`, folded into `make docs-check`).

- Added: generated CLI and Action reference pages (`docs/cli.md`, `docs/action-reference.md`) plus a docs manifest; `make docs-check` replaces landing-README table splices.

- Review specialists now report unique useful findings plus latency, cost, precision, and recall (#370)

- `.mergecraft/config.yaml` now carries a `schema_version`; unversioned files migrate on load, unknown versions fail closed, and deprecated keys warn before a breaking removal (#368)

- `mergecraft doctor --supply-chain` verifies lockfile reproducibility, bundled agent-CLI provenance, and analyzer version pins; every run manifest now records runtime and tool versions (#366)

- `mergecraft requirements inspect` and `explain` map ticket and local-spec text to requirement states without writing the reviewed tree; policy can require that evidence before a review passes (#352)

- `mergecraft describe` prints an output-only PR title, summary, walkthrough, risk, labels, TODOs, effort band, split advice, and similar-change notes (#351)

- `mergecraft capabilities` prints the review-only capability manifest (modes Review, IncrementalReview, Plan; identify / investigate / verify / explain / prioritize / suggest) (#350)

- Python 3.11 floor ADR (#343, option A): `docs/dev/python-version-floor.md` records parenthesize-now / binary-later.

- `osv-scanner` detect globs now include `uv.lock`, so repos using uv's lock file trigger vulnerability scanning without pip-audit (#309)

- docs: `flake8` and `pylint` catalog entries note they are legacy opt-in; enabled via config override only (#309)

- Catalog manifests for `knip` (JS/TS unused exports/dependencies, `scope: repo`, `category: quality`) and `vulture` (Python dead code, `scope: repo`, `category: quality`) (#337)

- `detekt` flipped to `default_enabled: auto`; activates on any `*.kt` or `*.kts` change, or when `detekt.yml` is detected — provides the default Kotlin lint path (#317)

- `sqlfluff` flipped to `default_enabled: auto`; activates on any `*.sql` change or `.sqlfluff` config presence — skips silently when no SQL dialect is declared (#319)

- `stylelint` flipped to `default_enabled: auto`; activates on any `*.css`/`*.scss` change or `stylelint.config.js`/`.stylelintrc.json` presence — provides the default CSS lint path (#320)

- `htmlhint` flipped to `default_enabled: auto`; activates on any `*.html` change or `.htmlhintrc` presence — provides the default HTML lint path (#321)

- `checkmake` flipped to `default_enabled: auto`; activates on any `Makefile`, `makefile`, or `*.mk` change — provides the default Make lint path (#325)

- `markdownlint` flipped to `default_enabled: auto`; activates on any `*.md` change or `.markdownlint.json`/`.markdownlint.yaml` presence — provides the default Markdown lint path (#326)

- `luacheck` flipped to `default_enabled: auto`; activates on any `*.lua` change or `.luacheckrc` presence — provides the default Lua lint path (#328)

- `fortitude` flipped to `default_enabled: auto`; activates on Fortran files (`*.f90`, `*.f95`, `*.`, `*.f03`, `*.f`, `*.for`) or `.fortitude.toml` — provides the default Fortran lint path (#329)

- `regal` flipped to `default_enabled: auto`; activates on any `*.rego` change — provides the default Rego/OPA policy lint path (#330)

- `psscriptanalyzer` flipped to `default_enabled: auto`, adds `*.psd1` detect glob, and sets `supports_fix: true` — provides the default PowerShell lint and auto-fix path (#331)

- `blinter` flipped to `default_enabled: auto`; activates on `*.bat`/`*.cmd` changes — provides the default Windows Batch lint path (#332)

- `smarty-lint` flipped to `default_enabled: auto`; `ANALYZERS.md` notes that `*.tpl` is ambiguous (Go templates, Terraform) — enable only when `.smarty-lint.json` confirms Smarty intent (#334)

- `ember-template-lint` flipped to `default_enabled: auto`, sets `supports_fix: true`; gates on `ember-cli-build.js` or `ember-source` in `package.json` — bare `*.hbs` files do not trigger it (#335)

- `phpcs` and `phpmd` remain `default_enabled: false`; catalog entries note they are legacy opt-in — `phpstan` (auto) is the default PHP signal (#316)

- `brakeman` flipped to `default_enabled: auto` with tight Rails detection — only activates on Rails marker files (`config/application.rb`, `config/routes.rb`), never on plain Ruby repos (#313)

- New catalog manifest for `bundler-audit` (Ruby gem vulnerability audit, `category: vuln`, `scope: repo`, detects on `Gemfile.lock`) (#313)

- `scripts/check_type_ignores.py` fails when a `type: ignore` or `cast(` in allowed `src/mergecraft/` lacks a one-line reason (#275); wired into `make lint`

- `scripts/check_xpass.py` fails when unexpected pytest xpasses remain on the allowed test tree (#276)

- xpass ratchet now runs as a `pytest_sessionfinish` conftest hook inside the coverage-gate pytest session — no standalone log file or extra CI step (#276)

- docs: README requirements and `docs/distribution.md` Marketplace copy state that mergeCraft 0.1.0 is GitHub-only; GitLab support is planned via the `ScmProvider` abstraction (#279)

- Added: a test-only provider-harness fixture schema and strict matcher (`tests/support/provider_harness`) so deterministic review tests can name the exact provider interaction they expect.

- Added: provider-harness recording workflow and operator docs (`docs/dev/provider-harness.md`); opt-in sanitized capture under.

- Repository context engine indexes per-file symbols (tree-sitter with generic fallback), provenance citations, and trust-gated instruction/skill discovery under `mergecraft.context`

- Call graph, change graph (changed symbol → dependents → tests → contracts), and `mergecraft context inspect` for provenance-backed context retrieval

- `mergecraft policy lint|test|explain` — validate policy rules, run should-trigger/should-not fixtures, and list effective rules with source layers

- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews

- precision corpus gate (`evaluate_dg1_precision_corpus`) replays the corpus and compares confirmed precision against the pre-DG1 baseline

- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy

- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win

- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache

- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets

- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default

- `mergecraft plan` previews model chain, toolset, analyzer detection, and token estimate without provider calls

- Run manifest fingerprints (model/CLI versions plus prompt, config, and policy hashes) for reproducible offline reviews

- `mergecraft review` machine contract: distinct process exit codes per `RunOutcome`, `--format text|json|jsonl|sarif`, and `--agent` JSONL streaming with an explicit `protocol_version`

- Added tracer baseline attributes (`mergecraft.run_id`, `mergecraft.version`, `mergecraft.trust_tier`, VCS and CI fields) merged into spans at close time, with explicit attributes taking precedence

- Added review-context env propagation into spawned agent CLI subprocesses, so subagent runs join the parent review's trace identity

- Added richer tool-call tracing: `gen_ai.tool.call.id` correlating request and response, per-call duration, and an MCP-vs-native origin distinction

- Added `mergecraft eval gate` — a release regression gate comparing a candidate result set against baseline with a declared tolerance band, wired as a blocking job in the release workflow

- Added agent registry binding model, prompt, toolset and budget per role with `mergecraft agents list|show|set` and `make agents-check`

- Added registry-driven harness render for Claude, OpenCode, Codex, Gemini, and Cursor with per-agent models and declared Codex degradation in run metadata

- Added typed specialist handoff and model-diversity policy for verification.

- Added change classifier and risk-based lens routing with recorded per-lens reasons in Review mode

- Promoted 20 themed review lenses from Review prose into registry entries with `mergecraft lens list|show|test`

- Added pluggable orchestrator with declarative pipeline file, trust gate for untrusted sources, and `mergecraft pipeline lint|show|explain`

- Added declared decision nodes for hybrid orchestration — typed triviality, lens selection, and finding disposition seams with pipeline-owned control flow

- Added: optional `harness` setting (`opencode` / `codex` / `claude` / `gemini` / `cursor`) to select the agent runtime independently of provider/model.

- Added: terminal-verdict protocol shadow mode (`gates.terminal_verdict`, default `shadow`) with a closed `VerdictDiagnostic` vocabulary; enforce still applies the fail-closed missing-verdict branch

- Added: `submit_review_verdict` — a typed MCP operation that records a review's terminal verdict (`approve` / `request_changes`), summary and structured findings.

- Published Python distributions are installed outside the checkout and carry build provenance before upload

- `pre-commit` blocks newly added large files and private keys, and scans staged changes for secrets with `gitleaks`

- `make test-durations` refreshes the committed `.test_durations` that least-duration sharding balances by

### Changed

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not implemented instead of being accepted and ignored.

- `mergecraft policy` help and enforcement docs state that a review run does not enforce policy rules.

- Recorded Jev transports and the canary assertion moved out of the runtime package into the test suite.

- A prepared release branch keeps `server.json`'s advertised package version in step with `pyproject.toml`, so the branch no longer fails its own `mcp-server-json-check` drift gate.

- The local `.env` file and the tracing environment layer are read through one typed model each, so a variable's exact name and type live in one place and a new environment read has a defined home.

- The Gemini and Codex harness deny lists name the `push_branch` tool the way each CLI documents it, matching the spelling the other harnesses already used.

- Finding matching against a baseline maximises the number of matched issues, so recall no longer changes when baseline issues are reordered; the scorer version is now `1.1.0`.

- `mergecraft verify-behavior` now drives a real Chrome over the DevTools Protocol and scores each acceptance criterion and reproduction claim through Jev, instead of refusing every run.

- `mergecraft jev enable|disable|status|set` configures the Jev advisory screening gate.

- Order-dependent test coupling now surfaces on a scheduled, non-blocking unit-suite run whose seed is the per-run `github.run_id`, so a pinned seed no longer hides it.

- Bare CLI command names open a TTY interactive session.

- A second gate policy (prompt 2.0.0) records through the existing recorder.

- Production false positives and human dismissals can be ingested into the eval bank as versioned cases, each carrying explicit provenance.

- Consumer setup guidance now lists every file produced by `mergecraft init` that may be committed: the config, learnings file, workflow, and added `.gitignore` lines.

- CLI `--json` payloads carry their own schema version, decoupled from the review snapshot's. Both stay `1.0.0`, so no payload changes; the two can now be bumped independently (#777).

- `mergecraft jev enable` now requests `TYPESAFE_API_KEY` when it is not already set and writes it to `.env`.

- Review records, sticky progress comments, and the Actions step summary now show input and output token counts separately instead of one combined total (#801)

- `make test` no longer runs the nine branch-walking `test_cov_*` suites: they carry a new `coverage` marker and the `make test` selector is now `-m "not integration and not coverage"`.

- The coverage/mutation CI gate's `enforce` mode is now exercised under test — both `shadow` and `enforce`, asserting the gate action and `reaches`.

- The action-pin bump workflow no longer advertises a push it cannot perform.

- PR #742 drops Playwright as the behaviour-verification driver.

- `mergecraft verify-behavior` fails closed when the browser-use stack is unavailable, even with `--artifacts-dir` / `--input`; `--allow-stub` is the only stub opt-in (#61, #752)

- `verify_behavior.enabled: false` skips the run (kill switch); default remains enabled so invoking the CLI still runs on a trusted checkout (#61)

- `verify_candidate` verifies the commit that introduced an image digest rather than whichever commit the candidate range happens to end at.

- `trust.agentSandbox` ladder (`never` / `merged-only` / `dispatch` / `same-repo`) with `mergecraft trust show` and `mergecraft trust set-agent-sandbox` (#553)

- `docs/trust-policy.md` documents the sandbox override ladder, fork floor, and residual risks

- Action `logfire-token` exports to `MERGECRAFT_LOGFIRE_TOKEN` before the Logfire sink initialises (#551)

- Actions-visible warning when tracing targets Logfire but no token resolves (#551) #### Fixed

- Self-review on PRs that edit `.mergecraft/config.yaml` publishes again after the publication guard re-baselines the config hash post-`checkout_pr` (#584)

- Nous and custom gateway providers are detected when only `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` is set (#552)

- Bubblewrap namespace failures surface once as a non-blocking run observation instead of inflating the packet gate with repeated Major findings (#553)

- Entropy redaction no longer strips proven benign analyzer shapes — sweep evidence at `docs/dev/15-w6-entropy-sweep-report.json` (#537) #### Changed

- #553 boundary amended from the `pull_request_target` event to fork heads — same-repo `pull_request_target` may grant the override at `same-repo` tier

- Claude backstop no longer runs when an earlier rung succeeds or posts a verdict including `neutral` — only retryable rung failures without a verdict trigger Claude (#600) #### Changed

- Same-repo `pull_request_target` self-review runs trusted-tier analyzers when `trust.selfReview` is `analyzers` — execution trust without widening approval authority

- Declared CI SARIF artifacts are downloaded and recorded when `wait-for-ci` reaches `state=complete` (green or red).

- Action log phases (setup, model chain, agent dispatch, publish) emit collapsible `::group::` blocks in GitHub Actions logs #### Added

- Dogfood config sets `trust.agentSandbox: same-repo` so Codex `danger-full-access` is honoured on same-repo review runs (#553)

- CI SARIF ingest covers actionlint, zizmor, semgrep, and trufflehog alongside ruff, mypy, and bandit — matching `ci.yml` uploads and `ciEvidence.sarifArtifacts` (#464)

- TruffleHog CI evidence converts JSONL to SARIF so a clean scan uploads a valid empty-results document with tool metadata, not a blank file

- Hardened consumer template forwards wait-for-ci outputs and grants `actions: read` for ciEvidence SARIF ingest

- `evals/README.md` Harbor install pin is `v0.1.0a1`, and live detection is documented as `mergecraft review` (Harbor still calls the hidden `diff-review` alias)

- AGENTS.md and the consumer skill match the default workflow triggers

- The self-review Action pin on all three review rungs moves to `93a7897c`, pin 5 — GitHub Action Logfire honors `MERGECRAFT_TRACING_REGION` (#607)

- Self-review Codex fallback uses `openai/gpt-terra` (GPT 5.6 Terra) instead of `openai/gpt-codex`

- Dogfood `trust.selfReview` / `trust.agentSandbox` knobs apply after merge to the default branch — `pull_request_target` reads the base config snapshot, not the PR head

- `runBounds.tokenBudget` is the soft target; `tokenBudgetTolerance` (default `0.10`) sets the hard ceiling — set tolerance `0` to restore strict enforcement

- Run record and job step summary token lines name target, ceiling, over-target status, and per-phase attribution when phases are recorded

- Policy enforcement modes score a rule's blocking intent from the finding's gate-facing severity, so ``contributes_blocker`` is read off it rather than computed beside it.

- Render path: skip short-id assignment for non-hex fingerprints instead of aborting review output; export and explain paths stay strict (#493)

- Cheat-signature lint: narrow ``getattr_tautology`` to ``object`` targets so legitimate missing-attribute fallback asserts are not flagged; severity stays ``error`` (#501)

- Coverage ratchet: merge-base lookup failures and lowered-floor comparison failures are mutually exclusive, so honesty tests can assert which guard fired (#503)

- Coverage ratchet: document that the merge-base lowering guard is PR-only on ``push`` / ``workflow_dispatch``; absolute ``fail_under`` checks still run on all events (#506)

- Coverage ratchet: pin ``_default_base_branch`` resolution order (``GITHUB_BASE_REF`` → ``GITHUB_REF`` branch → ``pre-0.0.1``) without requiring a git remote (#507)

- **Breaking:** enterprise audit events are no longer written to ``.mergecraft/audit.jsonl`` inside the workspace by default; set ``MERGECRAFT_AUDIT_ROOT`` or read from the new default location

- Analyzer and trace redactors now emit the shared ``<redacted>`` placeholder from ``mergecraft.redaction_sentinel`` instead of the legacy ``[REDACTED]`` analyzer spelling

- Overflow agent findings now append to a server-written `### 🗂 Deferred findings` section with full finding text (non-blocking); analyzer overflow remains in `### 🔧 Mechanical findings`

- `review.verificationBudget` (default 24; `0` = no cap) caps verifier dispatches independently of `analyzers.inlineBudget`

- Harbor `MergecraftReviewAgent` resolves the default `uv tool install` ref lazily in `install` via `action_pin_minimal` instead of calling it at module import (#403)

- Landing README promoted from `readme_test.md` draft: agent-first layout, glossary links, auth table with recommended models, CLI how-it-works section, and `v0.1.0a1` Action pin (RV6)

- `mergecraft init` scaffolds a consumer-ready workflow (`alexhawat/mergeCraft@v0.1.0a1`, `pull_request` trigger, `models:` list) matching `examples/config.yaml` and Example 1 (RV6)

- ``probe_capabilities`` is ``lru_cache``-backed; ``reset_detection_cache`` clears the probe cache for xdist isolation

- ``detect_sandbox_method`` and ``network_namespace_available`` delegate to the cached capability probe with one unified privilege ladder

- Eval methodology: blocker precision is `None` (unpublished) when a run reports no blockers, and severity accuracy is `None` when there are no locality matches — never a vacuous 1.0

- Landing README redesigned as a REACH-style product page (outline B): problem/solution cards, architecture hero, numbered install, and jump-nav.

- `mergecraft review --help` now states that no flags are required and includes full example commands for local worktrees, GitHub branches, and present or past PRs

- Stale pytest `xfail(strict=False)` markers that were already passing are now real tests; remaining allowed-tree xfails are strict (#276)

- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`

- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

- The PR integration job runs keyless hermetic integration tests instead of passing on a check that a helper script exists, so a green run means tests executed

- An E2E live slice with no model configured reports `unavailable` in a warning and the step summary instead of a green `skipped`; a configured-but-broken slice still fails

- Live-provider tests report the HTTP status before parsing a response body, and never echo the credential or the request URL; the Nous leg posts the documented default model

- CodeQL results upload to code scanning on the events whose token can write `security-events`, and an analysis failure fails the job; fork and Dependabot pull requests analyse without uploading

- `make workflow-lint` no longer reports success on a host where it could not lint: it fails and says lint is unavailable

- `make docker-build` tags the image with a lowercase repository name, so the target can succeed

- Every runtime dependency is an exact pin, every third-party import in the package is declared, and the declarations nothing imports are gone

### Removed

- The MCP server no longer mounts a webhook endpoint; a signed delivery was verified but processed nothing, and its replay window could never fire.

- Provider circuit-breaker, health, budget and routing-eval helpers that no review path called are removed.

- Four context-retrieval modules no review path imported are removed.

- The unused `get-installation-token/main.py` script; the `get-installation-token` composite Action is unchanged

### Fixed

- The OpenCode harness hands its isolated `XDG_DATA_HOME` tree to the unprivileged agent user before `setpriv` drops privileges.

- An offline review called as a library without a findings file now asks the model for structured findings, as the CLI always does.

- A review whose agent calls `run_analyzers` on a host without a sandbox no longer fails closed with "checkout integrity failure: tree changed during read-only review".

- The Action images ship OpenCode 2.x (`@opencode/cli` 2.0.29) for every model routed through the OpenCode harness (Nous, OpenCode Zen and Go, MiniMax, TokenHub, custom providers).

- The hardened example workflow's approval gate now receives only the review verdict, not the whole evidence packet.

- The Codex reviewer now runs in the repository it reviews. An offline review started from another directory failed at once, because Codex refuses to run outside a git repository.

- The self-review passes each review step's evidence packet to later steps as a file.

- Both Action images replace the brace-expansion and undici copies bundled inside npm with their patched releases, pinned by checksum.

- A self-review re-run on a job token now picks up the earlier run's checkpoint and progress comment.

- `doctor`, `config show` / `config explain` and the config loader now agree on which files contribute.

- `doctor` fails before printing anything when its rendered output would contain a credential value, naming the environment key and never the value.

- Logfire workflow wiring accepts the lowercase `alexhawat/mergecraft@<ref>` spelling the docs print, while still refusing similarly-prefixed forks and an empty ref.

- `watch` and the review comment's run link honour `GITHUB_API_URL` / `GITHUB_SERVER_URL` for GitHub Enterprise hosts.

- The unused hosted-plan residue is gone: the two `AccountPlan` vocabularies, the context `plan` field and the `proxyModel` producers and consumers were removed, none of which had a reader.

- A Review run that records its verdict now publishes exactly one GitHub review from it, with the recorded findings as inline comments.

- An unknown or missing trust tier is treated as `untrusted` everywhere, including a tool context built without one.

- The recorded prompt version now reflects the rendered prompt the reviewer actually received, so two runs configured with different inline budgets record different versions.

- A configured inline budget of `0` is honoured everywhere: the offline analyzer pre-pass, the pipeline fallback and the rendered prompt now agree, instead of the pre-pass silently using the default.

- The review doctrine states the Python 3.11 install floor, and the `push` input, the compatibility matrix and the review checks describe review-only behaviour — no value grants commit or push.

- Documentation links and glossary anchors resolve on GitHub (the glossary's `{#id}` headings become real anchors), and the operator-facing `MERGECRAFT_*` knobs are documented in `docs/cli.md`.

- CI failures with no evidence of cause are now reported as **unattributed** — blocking, with `introduced_by_pr: unknown` — instead of being cleared as not-this-PR.

- `--allow-stub` permits the stub only when the browser stack is unavailable and logs why, instead of bypassing a reachable browser.

- Every agent CLI driver and the OpenCode server boot no longer hang when a child fills its stderr pipe.

- OpenCode server boot no longer blocks the event loop in a blocking `readline`.

- The Claude and Gemini reviewers can no longer write files, run shell tools or fetch the web.

- Tracing no longer clears a bound data-residency allowlist.

- The sticky progress comment keeps the finding ledger and the learnings delta across the final deterministic-record write, so a later run hydrates every prior record instead of losing it.

- Analyzer findings are attributed to the file that actually caused them again.

- GitHub App runs mint separate least-privilege API, Git, and cross-repository tokens. Cleanup attempts to revoke every internally minted token.

- Coverage gates use native line/branch metrics and accept only complete, fingerprinted shard sets. A single run trace covers setup through publication across Action, offline, and MCP execution.

- Evaluation records round-trip without dropping corpus data and write atomically after validation.

- The keyless shadow job is a fixture replay of two hard-coded packets. It does not read a live review and leaves #737 open.

- A live shadow row records the model on the packet (the slug that ran, else the configured reviewer). When the packet has no model, the row leaves it unset instead of claiming Claude.

- `mergecraft eval ingest --from-dismissals` turns recorded dismissal signals into structural eval cases. A dismissal is stored as `agent-seeded`, not as a human label (#738).

- Resetting the MCP shell sandbox cache tolerates a patched capability probe — it clears the probe cache only when a callable `cache_clear` is present — so test-isolation teardown no longer errors.

- `mergecraft verify-behavior` stays inert on a fork or `pull_request_target` Actions event instead of always skipping the trust gate (#61)

- `mergecraft review --verification-report` does not load a report on an untrusted checkout, including when a workflow treats the workspace as trusted (#61)

- Verify criteria are scored per criterion; reproduce matches page text to repro notes; `--start-command` retries navigate while the app comes up (#61)

- Local `--shell enabled` now refuses when no sandbox backend is available unless `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` is set; on macOS, `sandbox-exec` is the backend when present (#593)

- Tracked public markdown is linted for decision-ledger tokens, -dot citations, and pointers into gitignored plans; Priority 1 docs were rewritten to stand alone (#709)

- `trivy` on Apple Silicon provisions the native ARM64 build so the local coverage gate does not hang under Rosetta

- Action reviews no longer crash at startup with `infra_error` when loading the shared token cap (#741)

- Enabled Jev reviews now keep the shadow-judge record next to the evidence packet after the command finishes, so paid calibration rows are retrievable (#728)

- A TypeSafe connect, DNS, or timeout failure on the shadow judge records a skip and leaves the completed review successful (#728)

- `jev.model` accepts only the pinned `jev-1.13.0` id, so a configured newer version cannot run while audit rows still claim the pin (#728)

- The Action-pin staleness budget counts changes rather than landings.

- A stale self-review Action pin on `main` no longer fails every open pull request.

- The sticky run record lists Action pin (manifest C) next to baked image source (S) so pin-lag (pinning S deploys the previous digest) is visible without reading Action logs (#641)

- Consolidated integration CI retains Python 3.11 and 3.14 coverage after prerelease/main reconciliation; the coverage ratchet runs once on 3.14.

- Bring the GitLab review-support matrix correction from main to the prerelease branch.

- Local base-only reviews retain working-tree changes; remote comparisons deepen bounded shared history and fail explicitly rather than substitute endpoint diffs.

- Installed convergence evaluations include their recall corpus. Example drift checks run in disposable copies and no longer rewrite tracked outputs.

- Redaction preserves closing assignment brackets and ordinary source paths while retaining secret-pattern and high-entropy controls.

- Optional image live checks require an actual terminal review rather than CLI help.

- Self-review App tokens now refresh per provider attempt and revoke after the job.

- Action images use patched, checksum-pinned npm and GitHub CLI tooling and remove unused vulnerable pip bootstrap copies.

- Local review honors configured model chains, explicit/environment precedence, fallback restrictions, and cumulative budgets; a process without a terminal verdict is inconclusive (#592).

- Installed skills use a verified documentation commit containing every linked target and teach canonical, explicitly scoped provider authentication (#589).

- Analyzer isolation reports unsupported macOS accurately and warns when trusted execution lacks isolation.

- Credential broker stream failures now close the connection without inserting a second HTTP response, and client disconnects release upstream responses (#595)

- Brokered Codex runs preserve configured proxy bypass entries and always bypass proxies for the loopback broker, without changing parent proxy settings (#597)

- Removed an obsolete Codex broker auth branch that suppressed the API-key authentication diagnostic; subscription authentication is unchanged (#596)

- Release verification uses compatible GitHub CLI policy flags, validates deployment candidates automatically, and publishes canonical image tags only after signed staging digests verify.

- Release E2E now runs for reusable workflow callers, and image promotion requires verified signatures, source provenance, and SBOM attestations.

- Logfire `llm.call` rows now include the prompt mergeCraft sent and the model output, with a real duration instead of an empty ~2µs span

- Codex, Claude, and Gemini tool-use now shows up as `tool.call` children on the same Logfire trace as the review run

- Authentication quick start uses registry labels (`anthropic`, `openai`, `google`) instead of harness names that `provider auth` rejects (#590)

- GitHub Action Logfire tracing honors `MERGECRAFT_TRACING_REGION`, so an EU write token is no longer posted to the US ingest host (#607)

- Anchor-422 recovery no longer spins on an out-of-range comment index — it demotes all inline comments and posts once (#570)

- The published GitHub review body always matches the terminal submission; probe strings and split publication races no longer land a placeholder review (#572)

- Multi-reviewer findings carry server-stamped `raised_by` attribution on the published review; agents cannot supply the field via `submit_review_verdict` (#574)

- Token spend slightly over `runBounds.tokenBudget` warns and completes instead of failing at the cliff; crossing the hard ceiling still ends the run (#571)

- Base-branch coverage measurement reads that worktree's `.mergecraft/config.yaml` instead of the PR head's — a PR that adds a config key and its schema field no longer fails the base run (#573)

- A refused terminal verdict now reaches the deterministic run record by name.

- Git MCP containment: refuse `--no-index`, confine positional paths, deny credential paths (`.git/config`, askpass tree), and redact git failure text before it becomes a tool result

- Post-run retry loop classifies scope and policy refusals before resuming — deterministic refusals no longer spend a second provider turn

- Single Loguru writer with `enqueue=True` and explicit queue drain — runner logs no longer interleave mid-line from concurrent stdout/stderr writers

- Bubblewrap namespace failures surface `user_namespace_failure_hint` once per run (not gated behind a non-zero Codex exit code)

- `checkov` and `yamllint` catalog rows document linux-amd64 manifest-only provisioning instead of presenting as runtime failures

- Git config MCP: deny `config --list` and credential-bearing keys on `config --get-all` so brokered auth headers cannot leak through enumeration

- `get_commit_info` validates unified diff evidence before establishing review scope; successful `checkout_pr` records scope via `register_review_scope`

- Claude driver: pass ``--verbose`` alongside ``--print --output-format=stream-json``.

- Trajectory auditor classifies tool failures before counting them, so self-corrected schema slips, policy refusals, and environment faults no longer masquerade as ignored errors that block the PR

- Codex fallback routing reads `decision.verdict` from the in-process evidence packet instead of racing the check-runs API

- Pipeline predicate validation no longer rejects repository paths whose names contain substrings such as ``subprocess`` or ``import``; the closed regex is the sole control

- Pipeline severity predicates include ``Trivial`` and rank unknown severities below every taxonomy member instead of treating them as ``Minor``

- ``ReviewEngine.run`` clears the timeout callback on every invocation so a second run with ``on_timeout=None`` does not retain the first run's handler

- Required static checks block approval unless every row is explicitly ``passed`` or ``not_applicable``; ``unavailable``, ``error``, ``timeout``, and unknown statuses no longer satisfy the gate

- Review publication reads repo settings from the run-scope snapshot taken before untrusted execution instead of reloading ``.mergecraft/config.yaml`` from the mutable checkout

- Shipped ``operational_readiness`` policy pack rules now declare the required evidence keys ``enforcement: required`` consults before it treats the rule as satisfied

- Authenticated git operations against GitHub now work at all.

- `actions/checkout` no longer persists its token in the review workflow, the shipped hardened example, its template, or the dogfood artifact.

- ``prep`` lockfile selection prefers ``uv.lock`` over a stray ``requirements.txt``; ``should_run`` threads one ``cwd`` into ``run`` instead of reading ``Path.cwd`` twice

- The Action image now installs the `[tracing]` extra (`uv sync --frozen --no-dev --extra tracing`).

- `mergecraft.yml` now actually passes the tracing inputs it has supported since.

- ``redact_tool_payload`` caps UTF-8 byte length (not Python character count) and keeps a head slice plus a visible truncation marker instead of discarding the whole body

- ``redact_url`` preserves ``http`` vs ``https`` when redacting basic-auth userinfo

- ``tests/tracing/test_redaction_doctests.py`` executes ``mergecraft.tracing.redaction`` doctests

- Webhook signature verification encodes signature operands with UTF-8 surrogateescape before ``compare_digest``, so non-ASCII header bytes are rejected instead of raising ``TypeError``

- The MCP server no longer mounts a webhook endpoint: a signed delivery was verified but processed nothing

- `validate_http_url` rejects whitespace and control characters anywhere in a provider URL, not just at the ends.

- `mergecraft workflow` resolves a relative `--workflow` against `--cwd` on every subcommand.

- The consumer workflow file is replaced atomically by `mergecraft workflow`, matching the config writer. A crash mid-write used to leave it truncated

- `provider migrate` validates a migrated `NOUS_BASE_URL` through `validate_http_url` like every other URL entry point, instead of storing it unchecked

- `.mergecraft/config.yaml` is replaced atomically (temporary file plus rename, preserving permissions) by every CLI writer.

- `mergecraft workflow provider add --apply` writes the registry config only after the workflow file lands, and rolls the workflow back if that config write then fails.

- `mergecraft workflow provider add --url` on an already-registered provider now applies the validated endpoint to the row that is wired and persisted.

- Indexed registry credentials survive the legacy credential re-injection in `build_agent_env`.

- `list_check_runs` omits `check_runs` when the listing is truncated, instead of returning a partial catalog with `total_count`.

- Check-suite log fetch skips with a distinct unavailable payload when no GitHub client is bound, instead of looking like “no failed runs”

- Catalog-check rejects all-zero `sha256` provenance pins (placeholders that made `provision_managed_binary` treat a trailing-slash URL as a directory and fail with `Is a directory`).

- A transient Nous HTTP 404 (including a false billing/credits refusal) now fails over to the next model instead of stopping the run and reporting a missing `set_output` schema failure (#466)

- The approval gate now unions agent findings with analyzer findings, so an agent Critical or Major finding fails ``mergecraft-approval`` and the evidence packet's ``request_changes`` action.

- A clean mypy JSON typecheck no longer fails the SARIF convert step, so the mypy artifact still uploads for review evidence

- Evidence packet `decision.verdict` is a GitHub check conclusion (`success` / `failure` / `neutral`); schema version 1.9.0

- `mergecraft-approval` posts `neutral` when the evidence packet was not assembled, instead of omitting the check

- Custom provider slugs not in the operator registry now fail closed instead of silently routing to OpenCode; the built-in catalog allow-list was narrowed accordingly.

- Repo-native analyzers no longer fall back to an arbitrary PATH binary.

- An explicit `--model` now beats `MERGECRAFT_MODEL`.

- Offline reviews (`--base`/`--head`, `--diff`, `--cwd`) can record a terminal verdict.

- Retryability now has one decision path.

- Codex `error` and `turn.failed` events are no longer discarded.

- Provider quota exhaustion is now classified as retryable for failover.

- `opencode serve` output is now drained for the process lifetime.

- A provider timeout no longer kills the review.

- `mergecraft --version` reported `0.1.0` while the project was at `0.1.0a1`: the number was restated as a literal in `mergecraft/__init__.py` alongside `pyproject.toml` and the two drifted.

- `review --dry-run` skips the analyzer catalog while still materializing the diff and returning the review prompt (#401)

- `load_audit_events` skips malformed JSONL lines and non-dict payloads instead of raising (#398)

- `route_model` routes security specialist at `critical` risk to the same capable model as `high` instead of Haiku (#394)

- Checkout and packaged `defaults.yaml` copies drifted after README v2; `make pins-check` gates byte identity (#402, #414)

- Hermes generated skill package lists `GEMINI_API_KEY` and `NOUS_API_KEY` (not `GOOGLE_API_KEY`) in `required_environment_variables`, matching `docs/authentication.md` (#415)

- Coverage ratchet floor raised to 80% after new docs contract tests increased measured line coverage above the prior ceiling

- Transitive `h2` 4.4.0→4.4.1 in `uv.lock` for `pip-audit` (PYSEC-2026-3628)

- `mergecraft init` no longer emits `uses:./` in consumer repos — published Action ref instead (V8/)

- `mergecraft init` scaffold drops comment triggers and unsafe `github.event.comment.body` prompt wiring; defaults to `CLAUDE_CODE_OAUTH_TOKEN` (README Example 1 parity)

- Evidence image uploads, issue comments, and PR label tools work on review-only runs again

- Linked-repo contract breakage is included in ordinary PR checkout, not only `mergecraft xrepo explain`

- Linked-repo checkout reads only operator-granted siblings, and skips a sibling whose HEAD is not the pinned SHA

- Webhook signature verification fails closed without a configured secret

- Untrusted download and clone URLs are SSRF-checked, and binary downloads pin DNS to the validated addresses

- `bandit` now uses built-in `--format json` instead of the optional SARIF extra, so auto-enabled Python security coverage still runs on plain Bandit

- `bundler-audit` now runs the gem CLI (`bundler-audit check --format json`) instead of `bundle audit`, so Ruby lockfile audits actually execute

- `tflint` no longer passes changed `.tf` files as positional args (invalid since TFLint 0.47); it lints the working directory and the pipeline still scopes findings to the diff

- `bundler-audit`, `cargo-audit`, and `cargo-deny` findings no longer fake a line-1 GitHub anchor when the tool did not report a line; crate/gem coordinates stay in the message

- `clippy` now runs as `cargo clippy --message-format=json` (package/workspace) instead of passing PR paths as cargo args, so auto-enabled Clippy keeps rustc JSON findings

- A successful analyzer with empty stdout (for example a clean `tsc --noEmit`) is treated as passed instead of unavailable

- `tsc` project-level diagnostics without a file location (for example `error TS18003`) now surface as body-only findings instead of a silent pass

- `tsc` help text and other unmatched nonempty stdout now fail closed instead of counting as a clean pass

- Project-level `tsc` findings survive diff scoping when the PR only changes `.ts` / `.tsx` files

- `brakeman`: command changed from `-o brakeman.sarif` (writes to file) to `-o -` (stdout) so the SARIF output is captured by the adapter; `parser: sarif` is unchanged (Thermos Finding 1, #338)

- MCP HTTP server now issues a separate bearer token for the orchestrator ``/mcp`` route; reviewer/verifier harnesses keep ``ToolContext.mcp_auth_token`` for their role endpoints (#349)

- OpenCode HTTP ``llm.call`` usage attrs omit unset counters instead of zero-filling ``gen_ai.usage.*`` when the session response reports output tokens only (#297)

- `agents/claude`: `write_mcp_config` wrote a single MCP server entry pointing to `/mcp/reviewer` (derived from the orchestrator's `current_agent_id` at `_run` start).

- `mcp/git`: corrected `commit_changes` tool description — it performs a local commit only and does not push to the remote or produce a GitHub-verified commit (#259)

- `mcp/git`: `--namespace` is now refused outright rather than forwarded.

- Fixed eval corpus run directories splitting on slashes in model slugs (e.g. `openrouter/openai/gpt-5`) — run ids are sanitized to a single flat component (#219)

- Fixed live corpus reviews running in an empty scratch directory — the case's repo context is materialized before the review (#220)

- Benchmark result sets now record full version pins and a reproducibility digest, so same-commit runs are comparable (#140)

- Two ensemble models that both report no findings no longer escalate to a judge (#238)

- Reviews of Python repositories with `shell: disabled` no longer fail closed after a completed review just because dependency installation was skipped as a security policy

- Fixed: model-chain fallback now advances when the provider succeeds without a terminal verdict; a valid `request_changes` is a usable result and does not trigger fallback

- Fixed: explicit `harness:` now selects the runtime agent, not only span labels

- Fixed: a previously recorded `approve` is re-validated before GitHub publish, so a later confirmed blocker cannot ship an `APPROVE` review

- Fixed: body-only `create_pull_request_review` with `approved: false` no longer posts a GitHub `APPROVE`

- Fixed: `create_pull_request_review` now requires established review scope in Review modes, matching `submit_review_verdict`

- Fixed: terminal-verdict shadow mode now records a predicted outcome beside the legacy result on the live finalize path

- Fixed: a body-only COMMENT is no longer recorded as `request_changes`, and body-only `request_changes` is rejected unless it has real findings

- Fixed: publication must match the recorded terminal verdict and is re-validated before sending `APPROVE`

- Fixed: IncrementalReview `report_progress` no longer advances the model chain

- Fixed: Review completion via `create_pull_request_review` now records a terminal verdict, and IncrementalReview may complete via `report_progress` without mapping to `inconclusive`

- Fixed: verifier confirms persist outside replaceable analyzer run state, including agent-authored findings

- Fixed: a verifier `confirm` now persists the finding fingerprint so `approve` over a confirmed blocker is rejected on the live tool path, not only in unit tests that seed `verified_ids`

- Fixed: a stored `approve` is re-validated at finalize against current evidence, so a later failed required gate or verifier confirm cannot leave the run `passed`

- Fixed: a provider success without a usable terminal verdict now advances the model chain when fallback is allowed, instead of accepting the first process-successful result

- Fixed: a later `run_static_checks` call that matches no gates no longer wipes a prior failed row, so `approve` still fails closed

- Fixed: `approve` is now rejected on the live path when `run_static_checks` recorded a failed required gate; previously the validator only saw those rows in unit tests

- Fixed: a review run that completes without submitting a terminal verdict now reports `inconclusive` (a `neutral` check conclusion) instead of `passed`.

- The checkout tool refuses a pull request number other than the one the run was bound to, and refuses a fork pull request on a run trusted for execution or authority.

- The `MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS` environment switch is removed; the security paragraph is always in the system prompt.

- Inside GitHub Actions the CLI no longer loads a `.env` from the checked-out workspace at startup; set `MERGECRAFT_ENV` to load an explicit file. Local (non-Actions) runs are unchanged.

- Linked-repo grants now match an exact lowercase `owner/name`; a bare name no longer authorizes a same-named repository, and two manifest entries sharing a name are both refused.

- Harbor's agent wrapper invokes `mergecraft review` instead of the deprecated `diff-review` alias.

- The sandbox write/network test and the symlink-target chown test run in the privileged lanes built for them, and fail rather than skip inside those lanes

- The keyless provider-catalog smoke no longer hides behind a live gate and runs in the unit suite

- Both in-image test scripts pin the same `pytest` and `pytest-asyncio` as the project they test

### Security

- The Claude reviewer can no longer read the run's credential material.

- The review job declares `actions: read`, and no review rung falls back to the shared `github-actions[bot]` login when no reviewer App is configured.

- Untrusted static checks run inside the sandbox against a disposable copy-on-write view of the checkout.

- Local log sinks are scanned for credentials after the run.

- Transitive `soupsieve` 2.8.4→2.9.2 in `uv.lock` for `pip-audit` (CVE-2026-85999, CVE-2026-86000) (#728)

- Fork-controlled `.mergecraft/config.yaml` can no longer lift the untrusted tracing-content cap; export of prompt bodies on fork PRs requires the Action input, env, or trusted base settings

- MCP HTTP startup no longer treats a TCP connect probe as proof of identity; server-thread failures propagate and ``GET /health`` requires a per-run nonce

- Analyzer JSON and JSONL outputs are structurally redacted by key and value before persist, so non-prefixed secrets in trufflehog-style payloads do not reach prompts or ``.mergecraft/analyzer-runs/``

- Entropy-based secret redaction uses a length-relative threshold with benign-shape exclusions for git SHAs, hex runs, and identifiers so legitimate code tokens in logs are not mangled unnecessarily

- OpenCode review sessions deny ``webfetch``, ``external_directory``, and ``edit``; ``read`` is allowlisted to the checkout and evidence scratch instead of ``*``

- Post-run checkout integrity verification via ``security.review_integrity`` hashes the tree before review and fails closed on mutation

- ``setpriv`` argv carries ``--no-new-privs``, ``--inh-caps=-all``, and ``--bounding-set=-all``; fails closed when ``setpriv`` lacks ``--bounding-set`` support

- Root-side ``git`` subprocesses route through ``utils/git_hardening.git_argv`` with pinned safe-config keys; ``make lint`` enforces the route via ``scripts/check_git_argv.py``

- ``prepare_workspace_for_agent`` no longer recursively chowns ``.git``; sandbox shell binds every registered workspace root's ``.git`` read-only

- Linked-repo ``_rev_parse_commit`` rejects leading-dash revs, validates pinned SHA shape, and passes ``--end-of-options`` before the rev

- Sandbox capability probes run real isolation checks instead of gating on ``CI``; untrusted MCP shell refuses unsandboxed spawn unless ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1``

- Skipped untrusted analyzers emit a ``Minor`` finding (``rule_id: analyzers.sandbox-unavailable``) naming missing isolation primitives

- ``sudo-unshare`` shell spawn passes env by name via ``--preserve-env`` with ``env=env`` on ``Popen`` so provider keys never appear in argv

- Namespaced shell spawn hides every ``git`` binary and binds ``.git`` read-only inside ``unshare`` / ``sudo-unshare`` branches; unsandboxed opt-in runs the raw command without host mount soup

- Python ``prep`` installs into ``.mergecraft/prep-scratch/prep-venv`` with a default-deny env allowlist so PR build deps cannot mutate the reviewer's interpreter or inherit provider credentials

- Mutating MCP tools other than review-session verbs (`select_mode`, checkout, review publication) are refused unless a write-capable mode is selected, including before mode selection (#350)

- GitLab webhook `X-Gitlab-Token` is compared as a shared secret, not an HMAC of the body (#361)

- External URL retrieval also blocks decimal, hex, and short IPv4 forms, IPv6-mapped loopback, and DNS that resolves to loopback, link-local, or metadata; DNS failure is fail-closed (#362)

- Dependency and container-image vulnerability gates no longer report a pass without running a scanner (#362)

- Untrusted PR trees no longer receive a `shell` tool when PID-namespace isolation is unavailable (#287)

- Untrusted PR trees no longer run package install lifecycle scripts in the Action process when `shell` is the default `restricted` (#284)

- `mcp/git`: the glued single-token spelling (`-ckey=value`) is refused alongside the spaced and inline forms, so the alias-execution block no longer depends on how the flag was written.

- `mcp/git`: `git diff --output=<path>` wrote an arbitrary file through a read-only tool — the subcommand allowlist constrains the verb, not the flags the verb accepts.

- `mcp/git`: `-C`, `--git-dir`, and `--work-tree` are now confined to the resolved primary repo root; any path outside raises `ValueError` with the offending path in the message (#257)

- Linked-repo reads are grant-gated: a run can only load repos declared in its authorized set; linked-repo and ticket text render through the fence as untrusted data

- CLI offline reviews now derive a trust tier from review-source provenance; cloned or out-of-root paths review at untrusted tier unless the operator passes an explicit `--trust` override

- Executable repo config (`setupScript`, `prepushScript`, `stopScript`, `staticChecks[].command`) from an untrusted review source is ignored; declarative config still applies

- `build_mcp_app_for_role` with `role="reviewer"` or `role="verifier"` no longer mounts the orchestrator toolset at `/mcp`; only the role-specific path is active (#282)

- The changelog-preview workflow passes no repository secrets to the third-party reusable workflow it calls

- Cleanup and token-revocation failures are logged as warnings naming the step and path — including a residual askpass file — instead of being suppressed.

## [0.1.0] — 2026-08-14

> **Never published.** `0.1.0` was never tagged, has no GitHub release and no
> package upload; its entries are kept here as history. The version above,
> `0.1.0a4`, is the pre-release cut in its place. `0.1.0a1` (`521c0aed`) was an
> Action-only tag — no PyPI upload and no GitHub release; `0.1.0a2` was skipped.
> A consumer upgrading from `v0.1.0a1` should read the **Breaking — action
> required** block above.

Planned initial public release (never published): mergeCraft is a standalone,
BYOK GitHub Action for AI-powered PR review — no proprietary backend, no
account, review runs against your own Claude/Codex/Gemini subscription or API
key.

Full pre-release development history: see
[`docs/dev/changelog-archive.md`](docs/dev/changelog-archive.md).

### Added

- Multi-agent review drivers for Claude Code, Codex, Gemini CLI, Cursor
  Cloud, and OpenCode, each resolving from a subscription login or an API
  key with no proprietary backend in between
- Curated multi-provider catalog (Nous Research/DeepSeek, Tencent TokenHub,
  MiniMax) plus a generic custom OpenAI-compatible gateway, configurable via
  `.mergecraft/config.yaml` or `with:` inputs
- Ordered model chain with automatic fallback: entries missing credentials
  are skipped and retryable provider failures advance to the next entry
- Analyzer catalog covering linters and type-checkers (Ruff, MyPy, Pyright,
  ESLint, Biome, Oxlint), dependency and secret scanning (OSV-Scanner,
  Trivy, TruffleHog), pattern scanning (Semgrep/OpenGrep/ast-grep), contract
  diffing (oasdiff, Squawk, buf), GitHub-native tools (actionlint, zizmor,
  ShellCheck, Hadolint), and a first-party scanner for MCP/skill manifests;
  selection is trust-tier aware (`analyzers: off|auto|full|untrusted-only`)
- Merge Evidence Packet: every run emits a versioned, structured record of
  findings, analyzer checks, the blast-radius lane, and the structural
  decision, exposed as the Action's `evidence_packet` output
- Blast-radius classifier maps changed paths to low/medium/high merge
  lanes, with additive per-category repo overrides
- Structural `mergecraft-approval` status check — a pure function of typed
  findings, run completion, and trust tier, so a crashed or timed-out run
  reports `neutral` rather than silently passing
- Eight trajectory checks read the agent's own mediated tool calls (a file
  edited but never read, a tool error retried with nothing changed, and six
  more) and feed the evidence packet
- File-backed eval bank (`mergecraft eval add|list|replay|promote`) turns
  real review outcomes into regression cases and permanent pytest tests
- Optional tracing: a local JSONL sink plus Logfire/OTLP remote export, a
  full per-run span tree, and a redaction boundary that scrubs secrets
  before any sink sees them (`mergecraft tracing`, `mergecraft auth logfire`)
- `mergecraft findings export|carryover` files GitHub issues for review
  findings a merged PR left unresolved, so they survive past the merge
- Optional GitHub code-scanning upload (SARIF) for analyzer findings
  (`sarif_upload: enabled`)
- Per-run nonce fencing neutralizes prompt-injection attempts in untrusted
  PR titles, bodies, and comments before they reach the reviewing agent
- Comment-triggered runs (`@mergecraft`) are gated on the commenter's GitHub
  author association by default, extendable via `commentInvocationAllowlist`
- CI pipeline intelligence clusters failures, distinguishes flaky and
  pre-existing failures from ones the PR introduced, and blames failures to
  the hunks that caused them
- `mergecraft models|analyzers|eval|tracing|learnings|auth` CLI command
  groups; README's Action-input, Action-output, and CLI reference tables are
  generated from the live sources and CI-gated against drift
- Hardened example workflow
  (`examples/workflows/mergecraft-hardened.yml`) with a same-repo secret
  guard, wait-for-CI, and approval-check enforcement
- Release pipeline builds each image once, attaches SBOM and vulnerability
  scan reports, cosign-signs and attests the digests, then promotes tags by
  digest — no second rebuild between scan and release

### Changed

- Typed `ProviderConfig` for OpenAI-compatible gateways (capabilities declarative; API keys stay in env vars). No wire-format change to generated `opencode.json`
- **BREAKING** — `with: model:` is now the head of the effective model
  chain rather than a replacement for it; set `model_pin: enabled` (or
  `modelPin: true`) to restore the old single-model behavior
- **BREAKING** — comment-driven invocation under `pull_request_target` is
  refused by default; opt in with `allow_pr_target_comments: true`
- **BREAKING** — new learning entries land in a quarantined staging section
  by default instead of taking effect immediately; set
  `autopromoteLearnings: true` to restore auto-promotion
- **BREAKING** — an unrecognized `analyzers:` input value now resolves to
  the strictest tier (`untrusted-only`) instead of the most permissive
  (`auto`)

### Security

- Agent privilege drop fails closed: a run that cannot drop root aborts
  instead of continuing to execute the reviewing agent as root
- Trust tier is derived before any repo-controlled script or git setup
  runs, and an unrecognized event shape fails closed to `untrusted`
- Agent CLI subprocesses receive an explicit credential allowlist — no
  ambient GitHub tokens or inactive provider keys reach the process
- A first-party analyzer (`agentsec`) scans `.mcp.json`, `CLAUDE.md`,
  `AGENTS.md`, and skill files for policy violations, and still runs under
  `shell: disabled`
