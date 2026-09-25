# Test plan — self-workflow and scaffold hardening

Branch: `wave/self-workflow-scaffolds`. This suite is authored ahead of the
implementation on purpose: every test below collects and lints cleanly, and
fails on the anchor for the reason named in its `xfail` marker. Non-strict
`xfail` is used so a test that turns green stops being a failure without any
later edit to `tests/`.

## Why

The self-review workflow was hardened against an untrusted PR — it never
checked the PR head out, it pinned every action, it refused to persist the
checkout token — and then handed the same workspace to a container that checks
the PR head out *into it*, and ran `./scripts/decide_*.sh` from that workspace
with a write-scoped token. The same shape repeats on the consumer surfaces:
the scaffold asks for content write and persists its token, the examples pin
actions by mutable tag, a third-party changelog workflow receives every secret,
and the approval gate trusts a check-run by name and recency so any app can post
one. These contracts pin the fixes.

## Contracts → tests

### 1. Fallback scripts run from a trusted, verified copy

Contract: the fallback decision scripts must not be read from the workspace once
a review rung has switched it to the PR head. A copy is taken directly after the
trusted checkout, before any mergeCraft step, asserts `HEAD == $GITHUB_SHA`,
stages exactly `scripts/decide_codex_fallback.sh`,
`scripts/decide_claude_fallback.sh` and `scripts/lib/provider_verdict_guard.sh`
with layout preserved, lives under the runner home (never under the
Docker-mounted temp directory or the workspace), records their hashes as a step
output, and each decide step re-verifies the hashes before running the copy.

- Unit / structural — `tests/ci/test_self_review_trusted_scripts.py`:
  `test_no_workspace_relative_script_runs_after_a_mergecraft_step`,
  `test_a_trusted_copy_is_staged_before_the_first_mergecraft_step`,
  `test_decide_steps_run_the_verified_copy`.
- Integration / functional — the same file's
  `test_decide_scripts_still_produce_need_from_a_trusted_copy` stages the copy
  under a fresh root and drives each script with the existing `gh` stub, proving
  relative library resolution survives the relocation.
- Shared harness — `tests/ci/support_self_review_cascade.py` gained
  `stage_trusted_copy`, a `cwd` parameter on `run_decide_script`, and a `gh`
  stub that emulates `--jq` and carries issuer/head/attempt fields, so the
  cascade routing can be exercised against run-bound data.

### 2. Approval gate provenance

Contract: the gate's verdict comes from the review job's own output; a
`mergecraft-approval` check-run only corroborates it. A passing gate needs the
output to be `success` **and** an attributable check: on this head, issued by
`github-actions` (or the configured App id when `EXPECTED_APP_ID` is set), with
`external_id` equal to `<run_id>:<run_attempt>`, and a conclusion that agrees.
A foreign check is ignored; a lone foreign check cannot pass; an unattributable
check, a disagreement, or an empty output fails closed. The hardened example and
the dogfood artifact keep their documented fail-open notice only when
*no* `mergecraft-approval` check exists at all. The shared routing library
prefers the packet verdict and uses the same name-filtered, run-bound check
query.

- Unit / structural — `tests/ci/test_approval_gate_provenance.py`:
  `test_gate_reads_this_runs_own_output`,
  `test_gate_queries_the_check_by_name_with_an_explicit_page`,
  `test_self_workflow_exposes_the_run_verdict_as_job_outputs`,
  `test_shared_routing_lib_uses_the_same_name_filtered_query`.
- Integration / functional — the behavioural matrix in the same file
  (happy path, foreign-check masking, wrong attempt, configured App, empty
  output, forged success, disagreeing check, lone foreign check), run against
  all three gate copies: `.github/workflows/mergecraft.yml`,
  `scripts/example_workflows/hardened.yml.tpl`, and
  `docs/artifacts/dogfood-mergecraft.yml`.
- Routing — `test_routing_prefers_the_packet_verdict_over_a_foreign_check` and
  `test_routing_never_treats_a_foreign_check_as_a_verdict` drive the decide
  script from a staged copy against the run-bound `gh` stub.

### 3. Scaffold and examples: least privilege

Contract: the `mergecraft init` scaffold, the minimal example and the minimal
template default to `contents: read`, set `persist-credentials: false` on
checkout, and carry one comment naming the `contents: write` that dispatch-driven
pushes need.

- Unit — `tests/ci/test_checkout_credential_persistence.py`: the workflow list
  now includes the minimal template and the minimal example;
  `test_minimal_surfaces_request_read_only_contents` pins `contents: read` and
  an explicit `persist-credentials: false`.
- Functional — `tests/cli/test_init_cmd.py`:
  `test_scaffolded_workflow_requests_read_only_contents` runs `mergecraft init`
  in a temporary repo and inspects the generated workflow.

### 4. Per-PR serialization

Contract: the scaffold and the minimal template declare a `concurrency` group
keyed on the pull-request number with `cancel-in-progress: true`.

- Structural — `tests/ci/test_scaffold_action_pins.py`:
  `test_scaffold_serializes_runs_per_pull_request`,
  `test_minimal_template_serializes_runs_per_pull_request`.
- Functional — `tests/cli/test_init_cmd.py`:
  `test_scaffolded_workflow_serializes_runs_per_pull_request`.

### 5. Immutable action pins from one source

Contract: every `uses:` in the self-workflow, both templates, both examples, the
scaffold, the dogfood artifact and the README example is `owner/repo@<40-hex>`
(local `./` refs and the hardened operator placeholder are exempt). Every
`actions/checkout` uses the one `checkout_sha` defaults key, and the mergeCraft
ref is the new `action_sha_minimal` key — the commit the release tag resolves to.

- Unit — `tests/ci/test_scaffold_action_pins.py`:
  `test_every_action_reference_is_a_full_commit_sha`,
  `test_every_actions_checkout_uses_the_shared_checkout_sha`,
  `test_action_sha_minimal_matches_the_published_commit`.
- Unit — `tests/pins/test_defaults_yaml_sync.py` extends the byte-identity gate
  with key presence/format for both SHA keys in both defaults copies.
- Offline drift gate — `tests/pins/test_action_sha_matches_tag.py` compares
  `action_sha_minimal` with the commit the tag resolves to, parsed from the
  recorded `git ls-remote` capture in `tests/pins/fixtures/`. The live
  comparison runs in the pins Makefile target.

### 6. No secrets to a third-party reusable workflow

Contract: no workflow job that calls a reusable workflow outside this repository
passes `secrets: inherit`.

- Structural — `tests/ci/test_reusable_workflow_secrets.py`:
  `test_no_external_reusable_workflow_receives_every_secret` scans every
  workflow under `.github/workflows/`.

### 7. Fallback rungs pin their model and report the executed chain

Contract: each review rung sets `model_pin: enabled` and carries the credential
variable for its own `model:` provider. The credential-degradation record
follows the executed chain: a pinned rung reports only its head; an unpinned rung
reports the genuinely uncredentialed tail at its real slot index.

- Structural — `tests/ci/test_self_review_rung_model_pin.py`:
  `test_every_rung_pins_the_model_it_runs`,
  `test_every_rung_env_carries_the_credential_for_its_model`.
- Unit — `tests/agents/test_roster_degradation_run_chain.py`: drives
  `collect_roster_credential_degradations` with a configured Nous-only roster,
  an OpenAI head and OpenAI-only credentials, pinned and unpinned.

### 8. True comments and legacy surfaces

Contract: no comment in the self-workflow claims the job never checks out; the
approval gate's false premise is replaced with the real reason for writing
packets to the runner temp directory.

- Structural — `tests/ci/test_self_review_trusted_scripts.py`:
  `test_no_workflow_comment_claims_the_job_never_checks_out`.

Contract: Harbor invokes `mergecraft review`, never the deprecated
`diff-review`; the unused `get-installation-token/main.py` is deleted while the
composite action is unchanged.

- Unit — `tests/harbor/test_harbor_agent_review_command.py` parses the agent
  source and pins the run command (harbor-extra-independent, so it runs in the
  default environment — the existing harbor module skips without the extra).
- Unit — `tests/ci/test_get_installation_token.py`: the legacy script is gone
  and the composite still mints/validates via the SHA-pinned app-token action.

## How to run

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"
make lint
make typecheck
uv run pytest tests/ci tests/cli tests/pins tests/harbor tests/agents/test_roster_degradation_run_chain.py -q
```

The suite is expected RED until the implementation waves land. Each `xfail`
marker names the wave that will satisfy it; the markers are removed during
post-wave reconciliation so the branch ends on real passes.

## Reconciliation log

- 2026-09-25 — SW2 landed the self-workflow hardening, so the four
  trusted-script tests, the three self-gate structural/routing tests, and the
  reusable-workflow-secrets test turned green and their non-strict `xfail`
  markers came off. The behavioural provenance matrix keeps its expected-red
  cases, but now per parameter (`hardened`, `dogfood`) rather than on the whole
  function: those two consumer surfaces are SW3's to green. The self-workflow
  gate cases run as real passes.
- 2026-09-25 — SW3 landed the consumer surfaces (shared SHA pins, read-only
  contents and per-PR serialization in the scaffold and examples, and the
  hardened-example / dogfood gate hardening), so every remaining SW3 `xfail`
  marker came off. The provenance matrix no longer needs its per-parameter
  split: `_TARGET_PARAMS` is a plain `self`/`hardened`/`dogfood` tuple and all
  cases run as real passes. Also cleared: the five `test_scaffold_action_pins.py`
  pins, the minimal-surface read-only pin, both scaffold functional pins, both
  shared-SHA defaults params, and the offline tag→SHA drift gate.
- 2026-09-25 — one assertion was genuinely superseded, not merely red-then-green.
  SW-D7 pins the README Example 1 `uses:` line to a full commit SHA carrying a
  `# vX.Y.Z` label, which is mutually unsatisfiable with the older
  `test_landing_pins_a_release_tag` release-tag expectation. It now asserts a
  full 40-hex lowercase SHA **and** the human-readable tag label, renamed
  `test_landing_pins_a_full_sha_and_labels_the_release_tag`;
  `test_landing_has_no_sha_pin_caveat` is unchanged. The stale row in
  `readme-v2-agent-first.md` was updated to match. Remaining `xfailed` in
  `tests/{ci,cli,pins,docs}` are SW4-owned:
  `test_self_review_rung_model_pin.py` (1) and `test_get_installation_token.py`
  (1).
