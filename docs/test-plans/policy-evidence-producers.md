# Test plan — policy evidence producers: real input for `required` rules

**Owner:** `test-creator` · **Branch:** `feat/policy-evidence-producers` · **Base:** `origin/main` @ `f312aa81`

A `required` policy rule names evidence keys (`requirements`, `xrepo`, `health_check`,
`rollback_plan`, `contract_schema`) and blocks until they are present. Until now the review
handed the enforcement engine an empty evidence map on every run, so a `required` rule with
keys always sat at `Major` and the only way past it was a waiver.

This suite pins one in-run producer per key, each reading from a source the pull request
under review cannot write, and the wiring that feeds the collected population to
`evaluate_enforcement` and `evaluate_rule_evidence`. It is written first and is **red until
the implementation lands**: no test is skipped and none carries an `xfail`; the
implementation must make every assertion pass without touching the test files.

Three rules the suite enforces throughout:

* **Nothing a pull request writes about itself is evidence.** The pull request body, a
  manifest or config key added on the head, and a check run any head-ref workflow could post
  are all ignored. Every absent key carries a reason, and the row repeats it.
* **Unknown is never present.** A source the run did not read (`None`), a listing that
  failed, a run that did not succeed, a document that is malformed, oversized or bound to
  another commit — each keeps the key absent.
* **No cost without a need.** Producers run only when a triggered rule requires evidence,
  only for the keys those rules name, and once per diff path. No producer runs a process,
  with one exception: reading a declaration from the base commit is a `git` read of the base
  config, and nothing else may run on that path.

Verification commands:

```bash
make lint && make typecheck
UV_PROJECT_ENVIRONMENT=$PWD/.venv-dev MERGECRAFT_PYTEST_JOBS=0 uv run pytest \
  tests/policy/test_evidence_producers.py tests/policy/test_review_evaluation_evidence.py \
  tests/config/test_policy_evidence_settings.py -q
```

## Names this suite pins

| Surface | Name | Shape |
| --- | --- | --- |
| Record | `mergecraft.policy.evidence_producers.EvidenceRecord` | frozen; `key: str`, `source: Literal["linked-issue-criteria", "operator-manifest", "declared-check-run", "declared-artifact"]`, `detail: str`, `digest: str \| None` |
| Population | `mergecraft.policy.evidence_producers.PolicyEvidence` | frozen; `present: dict[str, EvidenceRecord]`, `absent: dict[str, str]` (reason per key); the two maps partition the requested keys |
| Collector | `async mergecraft.policy.evidence_producers.collect_policy_evidence(ctx, *, required_keys: Collection[str]) -> PolicyEvidence` | produces exactly `required_keys`; never raises on a transport failure (the key is absent and the reason names the error) |
| Evaluator | `mergecraft.policy.review.evaluate_review_policy(..., evidence: PolicyEvidence \| None = None)` | `None` keeps today's behaviour (every key missing); otherwise the present keys feed both engine seams |
| Run path | `mergecraft.policy.review.ensure_policy_evaluated(ctx)` | unchanged signature, still returns `list[Finding]` synchronously; collects through `collect_policy_evidence` when a triggered rule requires keys, and must work from inside a running event loop |
| Tool state | `ToolState.linked_issues: tuple[LinkedIssue, ...] \| None = None` | the issues the pull request closes, read once at run start; `()` means it closes none, `None` means not (fully) read. Replaces the earlier `linked_issue_bodies` |
| Linked issue | `mergecraft.scm.types.LinkedIssue` | frozen; `number: int`, `author_login: str`, `body: str` (a missing body is `""`). The declared-scope work reads the same field |
| Run-start writer | `mergecraft.main._read_linked_issues(ctx)` | fills `ToolState.linked_issues`; no pull request ⇒ no call and `None`; a failed, partial or malformed read ⇒ `None` (written, never left at an earlier value) |
| Client read | `GitHubClient.closing_issues(owner, repo, number) -> tuple[LinkedIssue, ...] \| None` | one GraphQL `closingIssuesReferences(first: 25)` page with `pageInfo { hasNextPage }` and each issue's `number`, `body`, `author { login }`; `hasNextPage` ⇒ `None`. Replaces `closing_issue_bodies` |
| Tool state | `ToolState.linked_repo_base_manifest: BaseManifestLookup \| None = None` | the linked-repo manifest as read from the base (the lookup the checkout already performs); `None` means not read |
| Tool state | `ToolState.linked_repo_review: XrepoReview \| None = None` | the `review_linked_repos` result this run recorded; `None` means linked repositories were not reviewed |
| Head commit | `primary_repo_state(ctx.tool_state).checkout_sha` | the commit a check run or artifact must be bound to |
| Settings | `RepoSettings.policy: PolicySettings`; `PolicySettings.evidence: dict[str, EvidenceProducerSettings]` | default empty |
| Settings | `EvidenceProducerSettings` | exactly one of `check_run` (alias `checkRun`: `name: str`, `trusted_apps: list[str]` alias `trustedApps`) or `artifact` (`name: str`, `workflow: str` — the repo-relative workflow file allowed to upload it, required); `extra="forbid"`; `populate_by_name=True` |

### Row wording

| Case | Text the row carries |
| --- | --- |
| Present key | evidence line `evidence present: <key> (<source>: <detail>)` |
| Absent keys | evidence line and message clause `required evidence missing: <absent keys, comma-separated>` — present keys are not listed |
| Absent reason | each absent key's reason appears in the row's message or evidence |
| Unknown key | reason `no producer exists for <key>` |
| Undeclared proof | reason `no producer is declared for <key>; declare policy.evidence.<key> in the base configuration` |
| No base manifest | reason `no linked repositories are declared on the base` |

### Seams the suite chose (and why)

* **Closing issues live on `ToolState` as `linked_issues`.** The `requirements` producer is
  pure over `ToolState.linked_issues` (each a `LinkedIssue` with `number`, `author_login`
  and `body`) and the diff, so tests set the field directly. The read itself happens once at
  run start (`main._read_linked_issues` over `GitHubClient.closing_issues`), and the writers
  are driven for real in `tests/policy/test_evidence_writer_seams.py`. The declared-scope
  work reads the same field under the same name; whichever change lands second rebases onto
  it. The earlier `linked_issue_bodies` / `closing_issue_bodies` names are replaced, because
  the record must name the issue authors.
* **The `xrepo` producer reads what the checkout already computed.** The checkout reads the
  base manifest (`BaseManifestLookup`) and runs `review_linked_repos`; recording both on
  `ToolState` keeps the producer pure, process-free and free of a second git walk.
* **A declaration resolves exactly like the policy rules.** An operator-owned settings
  snapshot wins. Otherwise the declaration is read from `.mergecraft/config.yaml` at the base
  commit the policy rules are read from (`before_sha`, the same source `load_review_policy`
  uses), parsed through the settings model. The pull request head's config — on disk or in a
  non-operator snapshot — is never read. A base that is unknown, missing from the checkout,
  or whose config does not parse keeps the key absent, and the reason names the base (not
  the declare-it reason, because the base was never read). The ambient `GITHUB_BASE_REF`
  is cleared in these tests, so the base comes from the run state.
* **The artifact document is one JSON member of the artifact zip.** The suite uploads a
  single `policy-evidence.json` member. The 64 KiB bound is on the document's uncompressed
  bytes, and it bounds the read: the producer may decompress at most cap + 1 bytes.
* **The artifact record's `digest` is the SHA-256 of the document bytes.** A check-run
  record's digest is not pinned.

## Contract → test map

### The collector and its result

| Behaviour | Layer | Test |
| --- | --- | --- |
| Records and populations are frozen | unit | `tests/policy/test_evidence_producers.py::test_evidence_records_and_results_are_frozen` |
| Only the requested keys are produced; an unrequested declared check run is never read | unit | `…::test_only_the_requested_keys_are_produced_and_nothing_else_is_read` |
| An unknown key is absent with `no producer exists for <key>` | unit | `…::test_an_unknown_key_is_absent_because_no_producer_exists` |
| Present and absent partition the request; each record's `key` matches; sources come from the closed vocabulary | integration | `…::test_present_and_absent_partition_the_requested_keys` |

### `requirements` — linked-issue criteria mapped against the diff

Trust story: the criteria come from the issues the pull request closes, and mergeCraft maps
them against the diff itself, by keyword. The pull request body is never read for them. An
issue the pull request author wrote is author-controlled text, so `requirements` proves
traceability from issue to diff, not independent review: the record names each issue's
author and says the criteria were keyword-matched, and `docs/policy-evidence.md` says so.

| Behaviour | Layer | Test |
| --- | --- | --- |
| Every criterion `satisfied` / `partially_satisfied` (one issue or two) ⇒ present, source `linked-issue-criteria`, detail names the count | unit | `…::test_requirements_present_when_every_linked_criterion_is_evidenced[one-issue-two-criteria]`, `…[two-issues]` |
| One `contradicted` / `not_evidenced` / `out_of_scope` criterion ⇒ absent; the reason names that criterion and its state, not the satisfied one | unit | `…::test_one_unevidenced_criterion_keeps_requirements_absent_and_is_named[contradicted]`, `…[not-evidenced]`, `…[out-of-scope]` |
| The same criteria in the pull request body alone ⇒ absent; in a closing issue ⇒ present | unit | `…::test_the_pull_request_body_is_never_a_requirements_source[closing-issue]`, `…[pull-request-body-only]` |
| `linked_issues is None` ⇒ absent, `linked issues were not read` | unit | `…::test_unread_closing_issues_keep_requirements_absent` |
| A closing issue with no acceptance criteria ⇒ absent | unit | `…::test_linked_issues_without_criteria_keep_requirements_absent` |
| A fresh run state has not read the closing issues | unit | `…::test_the_default_run_state_has_not_read_the_closing_issues` |
| The record names every issue author and says `keyword-matched` | unit | `…::test_a_requirements_record_names_the_issue_authors_and_the_matching` |
| The row a reader sees carries the author and `keyword-matched` | functional | `tests/policy/test_review_evaluation_evidence.py::test_a_requirements_row_says_the_criteria_were_keyword_matched` |
| `docs/policy-evidence.md` says `author-controlled`, `traceability` and `not independent review` | doc | `tests/policy/test_evidence_producers.py::test_the_policy_evidence_doc_says_requirements_proves_traceability` |
| Run start: two closing issues ⇒ two `LinkedIssue` rows in order; the read names the repository and pull request | integration | `tests/policy/test_evidence_writer_seams.py::test_run_start_records_each_closing_issue_with_its_author` |
| Run start: closes none ⇒ `()` | integration | `…::test_run_start_records_an_empty_tuple_when_nothing_is_closed` |
| Run start: GraphQL failure, `hasNextPage`, no pull request object, a malformed node ⇒ `None` | error | `…::test_run_start_leaves_linked_issues_unread_on_any_doubt[…]` |
| Run start without a pull request ⇒ no call, `None` | integration | `…::test_run_start_without_a_pull_request_reads_nothing` |
| The real credential phase (`main._resolve_credentials`) calls `closing_issues` once with the repository and pull request number and fills `ToolState.linked_issues`; deleting the call in that phase turns it red (checked against a mutated copy) | functional | `…::test_the_credential_phase_reads_the_closing_issues_once` |
| `closing_issues` over a mock transport: `POST /graphql`, `first: 25`, the fields above | integration | `…::test_closing_issues_asks_for_one_bounded_page_with_authors` |
| `closing_issues` with `hasNextPage` ⇒ `None` | error | `…::test_closing_issues_refuses_a_second_page` |

Each criterion's state is asserted against the real mapper first, so a fixture that stops
producing the state it names fails loudly instead of testing nothing.

### `xrepo` — the operator-owned manifest, reviewed in full

Trust story: the manifest that counts is the one on the base; a pull request that adds or
edits its own manifest is never read for its own review, and every linked repository the
base declares must have been reviewed with nothing omitted.

| Behaviour | Layer | Test |
| --- | --- | --- |
| Base manifest, every repository reviewed, no omission ⇒ present, source `operator-manifest`, detail names each repository | unit | `…::test_xrepo_present_when_every_base_linked_repo_was_reviewed` |
| Manifest only on the pull request head ⇒ absent, `no linked repositories are declared on the base` | unit | `…::test_a_manifest_only_on_the_pull_request_head_is_not_xrepo_evidence` |
| No manifest anywhere ⇒ the same reason | unit | `…::test_no_manifest_anywhere_is_absent_with_the_base_reason` |
| One omitted repository ⇒ absent; the reason names it and the omission reason | unit | `…::test_one_omitted_linked_repo_keeps_xrepo_absent_and_is_named` |
| A base-declared repository the review never saw ⇒ absent, named | unit | `…::test_a_base_linked_repo_the_review_never_saw_keeps_xrepo_absent` |
| A base manifest that exists but is unreadable ⇒ absent with that reason | unit | `…::test_an_unreadable_base_manifest_keeps_xrepo_absent` |
| Base manifest never read, or linked repositories never reviewed ⇒ absent | unit | `…::test_an_xrepo_input_the_run_never_produced_keeps_xrepo_absent[base-manifest-not-read]`, `…[linked-repos-not-reviewed]` |
| A real `checkout_pr` of a repository whose base declares a linked repository records `linked_repo_base_manifest` and `linked_repo_review`, and the producer reads them (the ungranted repository is an omission, so `xrepo` stays absent naming it) | functional | `tests/policy/test_evidence_writer_seams.py::test_checkout_records_the_base_manifest_and_the_linked_repo_review` |

### `health_check` / `rollback_plan` / `contract_schema` — declared check runs

Trust story: the declaration lives in the operator-owned configuration; the check run must be
on the head commit, completed, successful, carry the declared name exactly, and come from a
GitHub App the operator trusts. `github-actions` can never be trusted: a head-ref workflow
names its own jobs.

| Behaviour | Layer | Test |
| --- | --- | --- |
| Success from a trusted App ⇒ present; `failure`, `neutral`, `cancelled`, in progress, an untrusted App, `github-actions`, another name, or a run bound to another commit ⇒ absent naming the run; check runs are listed for the head commit | unit | `…::test_a_declared_check_run_is_evidence_only_on_trusted_success[…]` (nine cases) |
| A present record names the run, the App and the run URL | unit | `…::test_a_present_check_run_names_the_run_the_app_and_its_url` |
| The right run on the base commit or a branch ref ⇒ absent; only the head commit is queried | unit | `…::test_the_right_check_run_on_another_commit_is_not_evidence` |
| A listing failure ⇒ absent with the error named; the collector does not raise | error | `…::test_a_check_run_listing_failure_is_absent_not_a_crash` |
| No declaration ⇒ absent with the declare-it reason and no network call, for each key | unit | `…::test_a_key_with_no_declaration_names_where_to_declare_it[health_check]`, `…[rollback_plan]`, `…[contract_schema]` |

### Declared artifacts

Trust story: the proof is produced by CI on the head commit and can only say `ok` for the
key and the commit it ran on. It counts only when the run executed exactly the workflow file
the base declares (`artifact.workflow`, matched against the run's `path`), the pull request
does not change that file, the run's `head_repository` is the reviewed repository (never a
fork), and the run completed with `success` on the head commit. A pull request that adds its
own workflow, or a fork's run, can upload the right name with a perfect document; neither
proves anything. The archive's reported size must be known before it is downloaded, and the
document is read with a hard size bound.

| Behaviour | Layer | Test |
| --- | --- | --- |
| A schema-valid `ok` document for this key and head ⇒ present, source `declared-artifact`, detail carries the document's `detail`, digest is the document's SHA-256; runs are listed for the head commit | unit | `…::test_a_declared_artifact_document_is_evidence` |
| `head_sha` mismatch, `status: degraded`, `key` mismatch, wrong `schema` ⇒ absent, named | unit | `…::test_an_artifact_document_that_does_not_vouch_for_this_commit_is_absent[…]` |
| Bytes that are not JSON ⇒ absent naming the artifact | error | `…::test_an_artifact_that_is_not_json_is_absent` |
| A failed, cancelled or in-progress run, or a run bound to another commit ⇒ absent | unit | `…::test_an_artifact_from_a_run_that_did_not_succeed_on_the_head_is_absent[…]` |
| An upload listed only for another commit ⇒ absent; only the head commit is queried | unit | `…::test_an_artifact_listed_only_for_another_commit_is_absent` |
| A successful run without the declared artifact ⇒ absent, named | unit | `…::test_a_missing_declared_artifact_is_absent_and_named` |
| Exactly 64 KiB ⇒ present; 64 KiB + 1 ⇒ absent naming the limit | edge | `…::test_an_artifact_document_is_bounded_at_64_kib[at-the-cap]`, `…[one-byte-past-the-cap]` |
| A 256 KiB document is never decompressed past cap + 1 bytes (zip reads metered) | edge | `…::test_an_oversized_artifact_is_never_read_past_the_cap` |
| The declared, untouched, same-repo workflow ⇒ present; the record names the workflow file | unit | `tests/policy/test_evidence_artifact_provenance.py::test_the_declared_untouched_same_repo_workflow_is_evidence` |
| A fork's own workflow the diff adds (`.github/workflows/forged.yml`) uploading a perfect proof ⇒ absent, naming the declared workflow | unit | `…::test_a_forked_workflow_the_pull_request_adds_is_not_evidence` |
| A fork run of the declared workflow, another same-repo workflow, a run with no `path`, a run with no `head_repository` ⇒ absent, named | unit | `…::test_an_artifact_from_any_other_run_is_not_evidence[…]` |
| A diff that edits the declared workflow ⇒ absent, naming the file | unit | `…::test_a_diff_that_edits_the_declared_workflow_voids_its_artifact` |
| A newer forged run listed beside the operator's run never shadows it | unit | `…::test_the_declared_run_is_chosen_over_a_newer_forged_one` |
| `size_in_bytes` null, a string or missing ⇒ absent, the reason says the size is unknown, and the archive is never downloaded | edge | `…::test_an_artifact_of_unknown_size_is_never_downloaded[…]` |

### Declarations come from the operator-owned snapshot, else the base commit

| Behaviour | Layer | Test |
| --- | --- | --- |
| A declaration added only in the pull request's own config (non-operator snapshot, base commit without it) ⇒ absent with the declare-it reason | integration | `tests/policy/test_evidence_producers.py::test_a_declaration_only_in_the_pull_request_head_config_is_ignored` |
| An operator snapshot without the declaration beside a working-tree config with one ⇒ absent | integration | `…::test_the_working_tree_config_cannot_add_to_the_operator_snapshot` |
| Operator-owned path: no producer spawns any process (`subprocess.*`, `os.system`, asyncio subprocesses patched to fail) while four keys are produced | integration | `…::test_no_producer_ever_runs_a_subprocess` |
| Not operator-owned: the base commit's `checkRun` is honoured whether the head removes it or rewrites it to trust its own App; the record names the base's run and App, never the head's | integration | `tests/policy/test_evidence_base_declarations.py::test_the_base_commit_declaration_is_honoured_on_a_pull_request_run[head-removes-the-declaration]`, `…[head-rewrites-the-declaration]` |
| A head that rewrites the declaration and posts only its own run ⇒ absent, naming the base's declared run | integration | `…::test_a_rewritten_head_declaration_cannot_clear_the_key_on_its_own` |
| The base's `artifact` declaration is honoured while a key only the head declares stays absent with the declare-it reason | integration | `…::test_a_base_artifact_declaration_is_honoured_beside_an_undeclared_key` |
| A base config without the key, or no base config at all, while the head declares it ⇒ absent with the declare-it reason (guard: green before and after) | integration | `…::test_a_declaration_only_the_head_adds_is_absent[config-without-key]`, `…[no-config]` |
| No base commit, or a base commit the checkout cannot resolve ⇒ absent; the reason names the base commit (or its id) and is not the declare-it reason | error | `…::test_an_unreadable_base_keeps_the_key_absent_and_names_the_base[no-base-commit]`, `…[base-commit-not-in-the-checkout]` |
| A base config the settings model refuses ⇒ absent; the reason names `.mergecraft/config.yaml` and the base commit | error | `…::test_a_base_config_that_does_not_parse_keeps_the_key_absent` |
| An operator-owned snapshot wins over the base commit in both directions (guard: green before and after) | integration | `…::test_an_operator_owned_snapshot_wins_over_the_base_commit[snapshot-declares-base-does-not]`, `…[base-declares-snapshot-does-not]` |
| A base config whose blob git cannot read (the loose object is gone) ⇒ absent; the reason names `.mergecraft/config.yaml`, the base commit and `could not be read`; no SCM call | error | `tests/policy/test_evidence_base_declarations.py::test_a_base_config_git_cannot_read_keeps_the_key_absent_without_a_scm_call` |
| A base config of 1 000 001 bytes ⇒ absent; the reason names the config and the 1000000-byte cap; no SCM call | edge | `…::test_an_oversized_base_config_keeps_the_key_absent_without_a_scm_call` |
| Base path: every process started is `git`, at least one names `.mergecraft/config.yaml` and the base commit, and the key is produced | integration | `…::test_the_base_commit_read_is_the_only_process_a_producer_starts` |

### Settings

| Behaviour | Layer | Test |
| --- | --- | --- |
| `policy.evidence` defaults to an empty map on a `PolicySettings` | unit | `tests/config/test_policy_evidence_settings.py::test_policy_evidence_defaults_to_no_declarations` |
| `checkRun` parses in config spelling and by field name | unit | `…::test_a_check_run_declaration_parses[config-spelling]`, `…[field-names]` |
| `artifact` parses with its `workflow` | unit | `…::test_an_artifact_declaration_parses` |
| `artifact` without `workflow` ⇒ `missing` error at `policy.evidence.<key>…workflow` | error | `…::test_an_artifact_declaration_needs_its_uploading_workflow` |
| Both or neither proof ⇒ one validation error under the declaration naming `checkRun` and `artifact` | error | `…::test_a_declaration_names_exactly_one_proof[both]`, `…[neither]` |
| `github-actions` (any case) in `trustedApps` ⇒ validation error saying so; a trusted App is accepted | error | `…::test_github_actions_is_refused_as_a_trusted_app[github-actions]`, `…[GitHub-Actions]` |
| A `checkRun` without `name` ⇒ `missing` error at `name` | error | `…::test_a_check_run_declaration_needs_a_name` |
| A misspelt key ⇒ `extra_forbidden` at that key | error | `…::test_an_unknown_key_in_a_declaration_is_refused` |
| The block loads from `.mergecraft/config.yaml` | integration | `…::test_policy_evidence_loads_from_the_repository_config` |

### Policy rows read the population

| Behaviour | Layer | Test |
| --- | --- | --- |
| `evaluate_enforcement` (`violation["available_evidence"]`) and `evaluate_rule_evidence` both receive key → detail for every present key | unit | `tests/policy/test_review_evaluation_evidence.py::test_the_engine_and_the_evidence_check_receive_the_present_keys` |
| Every key present ⇒ the row's severity is what the engine derives for complete evidence (each declared severity; each case checked to differ from the outstanding severity) | unit | `…::test_a_required_rule_with_every_key_present_renders_the_satisfied_severity[Critical]`, `…[Major]`, `…[Minor]`, `…[Trivial]` |
| The row lists `evidence present: <key> (<source>: <detail>)` per present key | unit | `…::test_the_row_lists_each_present_key_with_its_source_and_detail` |
| Partial evidence ⇒ engine severity for partial input; `required evidence missing:` names only the absent key; the absent reason is in the row | unit | `…::test_partial_evidence_names_only_the_missing_keys_and_their_reasons` |

### Run path

| Behaviour | Layer | Test |
| --- | --- | --- |
| No triggered rule requires evidence (none declared, or the evidence rule's scope did not match) ⇒ the collector is never called and GitHub is never read; the triggered row is still produced | integration | `…::test_no_producer_runs_unless_a_triggered_rule_requires_evidence[no-rule-requires-evidence]`, `…[evidence-rule-not-triggered]` |
| A trusted check run on the head clears a `required` rule end to end; the row names the run | functional | `…::test_a_required_rule_proved_in_run_drops_to_the_satisfied_severity` |
| The same, called synchronously from inside a running event loop | functional | `…::test_the_run_path_collects_evidence_from_inside_a_running_event_loop` |
| The collector is asked only for the triggered rules' keys | integration | `…::test_the_producers_are_asked_only_for_the_triggered_rules_keys` |
| Two calls on one diff ⇒ one collection and no extra reads; a re-scoped diff collects again | integration | `…::test_evidence_is_collected_once_per_diff_path` |
| After collection on the producers' own loop (called from inside a running loop and from none), every per-loop GitHub transport it opened is closed and `GitHubClient._clients` holds no entry; removing the loop-transport close in `policy/review.py` turns it red (checked against a mutated copy) | integration | `…::test_the_collection_loop_closes_its_github_transport[inside-a-running-loop]`, `…[no-loop]` |
| Inside a running event loop, with the operator snapshot only in the run-scope ContextVar (not on the context), the producers still see it (the worker hop copies the context) | functional | `…::test_the_run_scope_snapshot_reaches_the_producers_inside_a_running_loop` |
| No base-side declaration ⇒ the rule stays at the outstanding severity, the row carries the declare-it reason, and no check run is read | functional | `…::test_a_declaration_the_operator_did_not_make_keeps_the_rule_blocking` |

## Shared fixtures

`tests/support/policy_evidence_fixtures.py` holds the `EvidenceGitHub` client (answers only
check-run, workflow-run, artifact-list and artifact-download reads, records every call, and
fails any raw HTTP or GraphQL call), builders for check runs, workflow runs, evidence
documents and artifact zips, the settings and snapshot builders, `linked_issue(s)`, and
`evidence_ctx`, which sets the tool-state seams only when a test passes them. A built
workflow run defaults to the declared workflow (`.github/workflows/deploy-proof.yml`) with
`head_repository` `acme/demo`; `artifact_declaration()` declares that workflow.

## Open questions left to the implementation

* A check-run listing that contains the declared name twice (a re-run) with different
  conclusions is not pinned; the safe reading is that any non-success attempt on the head
  keeps the key absent.
* An artifact zip holding more than one JSON member is not pinned.
* Whether present keys a rule does not require appear on that rule's row is not pinned; the
  engine's `available_evidence` map does carry every present key.
