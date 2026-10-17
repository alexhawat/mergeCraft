# Test plan — CI credentials, config errors, release plumbing and housekeeping

**Owner:** `test-creator` · **Branch:** `wave/ci-config-release-housekeeping` · **Base:** `origin/main`

**Status: RED by design.** Every row below names a test that fails against the
current tree for the reason in its contract column; the implementation waves make
them pass. None carries an `xfail` marker (`xfail_strict = true` would turn a later
pass into a failure).

The thesis the suite pins: a surface says what it actually does. An outage that
reads as a red check nobody requires is not reported; a release path that cannot
produce its artifact is not documented; a module that ships with no caller is not
the product. Nothing here lets a review job hide a failure — no secret-writing
token in a review workflow, no canary that burns the credential it watches.

## Contract → test map

| # | Issue | Contract | Test module | Layer |
| --- | --- | --- | --- | --- |
| 1 | #882 | Every job that receives `CODEX_AUTH_JSON` joins the `codex-subscription-auth` group and never cancels a running consumer | `tests/ci/test_codex_credential_serialisation.py` | workflow shape, scanned across all workflows |
| 2 | #922 | The "refresh token was already used" failure is named in the driver result, classified `infra_error`, and reaches the check summary and run result; other Codex failures are unchanged | `tests/agents/test_codex_credential_expired.py` | driver, classifier, `main()` harness |
| 3 | #913 | No workflow declares the shared Actions bot as `MERGECRAFT_REVIEWER_BOT_LOGIN`; every declaration falls back to an empty string | `tests/ci/test_reviewer_bot_login_fallback.py` | workflow text, every workflow |
| 4 | #885 (1) | Every `actions/checkout` sets `persist-credentials: false` unless the job pushes; each exemption is checked to push | `tests/ci/test_workflow_checkout_credentials.py` | workflow shape |
| 5 | #885 (2) | The redaction module's own URI patterns stop flagging; a different detector in that file, or the same detector elsewhere, still flags; documented credential-shaped examples carry the inline marker | `tests/ci/test_trufflehog_uri_allowlist.py` | scanner emit path with a stubbed scan |
| 6 | #885 (3) | `changed-unread-file` is listed but non-blocking; the other trajectory checks keep their severity | `tests/evidence/test_changed_unread_file_advisory.py` | auditor, approval decision |
| 7 | #919 | `config tracing` lists the files `doctor` and `config explain` list, reports a missing `MERGECRAFT_CONFIG` the same way, and leaves flag → env → YAML precedence unchanged | `tests/cli/test_tracing_config_sources.py` | CLI, resolver |
| 8 | #920 | A column-0 comment inside a top-level sequence no longer ends the block; the docstring states the rule | `tests/config/test_config_block_sequence_comment.py` | unit |
| 9 | #930 | An unknown tracing sink with tracing on is `configuration_error` (Action) and the configuration exit code (CLI); with tracing off it is ignored with a warning | `tests/action/test_tracing_sink_configuration_error.py`, `tests/cli/test_tracing_sink_exit_code.py` | `main()` harness, CLI entrypoint |
| 10 | #1004 | `build-dist` runs for a dispatch on a release ref and not on ordinary branches; the release workflow dispatches the build on the prepared branch holding only `actions: write` | `tests/release/test_release_workflow_artifact.py` | workflow shape |
| 11 | #1005 | The publish gate names the real approval (the publish command); `post-release.sh` no longer edits `pyproject.toml` | `tests/release/test_release_approval_text.py` | workflow text, script run |
| 12 | #1006 | `tests/mcp/test_rpc.py` leaves no `package_version` cache behind, shown by running the poisoning order in a child pytest | `tests/mcp/test_rpc_cache_isolation.py` | child process |
| 13 | #947 | The wheel excludes the five checkout-only modules and no shipped module imports them | `tests/ci/test_wheel_contents.py` | packaging config, AST scan |
| 14 | #858 | Each driver records native exec calls with the real outcome; recording never fails the call | `tests/evidence/test_driver_exec_recording.py`, `tests/agents/test_driver_exec_recording.py` | recorder, three drivers' stream consumers |
| 15 | #892 | The three formerly blocked replay cases replay to their expected decision; the committed baseline is regenerated from the bank | `tests/evals/test_replay_floor.py` | replay, committed artifact |

## Revert sensitivity

Each code or config item has a test that fails when the change is reverted:

- #882, #913, #885 (1): remove the key from one job and the scan names the job.
- #922: drop the metadata key and the classifier test and the harness test fail;
  drop the named reason and the driver tests fail.
- #930: restore the plain `ValueError` and both the Action outcome and the CLI exit
  code tests fail.
- #1006: restore the setup-only fixture and the child-pytest probe sees `9.9.9+wheel`.
- #858: stop passing the run's state to a driver's stream consumer and that driver's
  seam test fails (the helper's own tests stay green, which is why both layers exist).

## Not covered here

- Operator-gated work is prepared, not executed: closing #970, running the failure
  harvest or labelling its output, creating fixture repositories, and the paid Railway
  run. Their deliverables are documents and scripts, checked by `make docs-check` and
  the script's own tests.
- No test runs the release workflow or publishes anything.
