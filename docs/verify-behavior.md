# Behaviour verification

A versioned report that records whether a running app matched its acceptance
criteria — or named what blocked the run. The report is its own artifact. It is
not a typed finding: a behavioural mismatch has no diff line to anchor to.

**Audience:** consumer (operators and agents who will run or consume a report)

`schema_version` is required and pinned to **`1.0.0`**. The JSON Schema is
derived from the Pydantic models. Markdown is a **view** of that JSON, not a
second source of truth.

## Status vocabulary

Closed sets. Unknown values are rejected.

| Surface | Statuses |
|---------|----------|
| `verify` report | `pass` · `fail` · `partial` · `blocked` · `skipped` |
| `reproduce` report | `reproduced` · `not_reproduced` · `partial` · `blocked` |
| Per criterion | `pass` · `fail` · `unverified` |

Cross-mode values are invalid: `verify` rejects `reproduced`; `reproduce`
rejects `pass`.

`blocked` is first-class. When `status` is `blocked`, `blocked.missing` is
required and must name at least one missing input (credentials, seed data,
startup command, unreachable URL). A blocked run is never a pass and must not
be omitted from review output.

A report is successful only for verify `pass` or reproduce `reproduced`.

## Artifact layout

Reports and captures land under `.mergecraft/artifacts/`:

| Kind | Path |
|------|------|
| Issue reproduce | `.mergecraft/artifacts/issues/<n>/repro/` |
| Pull-request verify | `.mergecraft/artifacts/prs/<n>/verify/` |
| Manual run | `.mergecraft/artifacts/manual/<timestamp>/` |

`artifacts.video` is nullable and unused in this version. `artifacts.trace` is
nullable — filled when the driver records a trace at no extra pipeline cost.
There is no video recording pipeline.

## Trust

Behaviour verification is **trusted-tier only**. On an untrusted checkout
(typically a fork pull request) the capability is inert and reports `skipped`
with the reason. The same skip applies when `shell: disabled`. Configuration
cannot re-enable it on an untrusted tier.

The report body is derived from application output the change under review
controls — page text, console messages, logs. That content must be fenced
before it reaches any review prompt.

Credentials are **names only**: inputs list env-var names
(`credential_env_names`); the report records which names were used
(`credential_names`). Values are never stored on the models.

## Field provenance

Which GitHub issue asked for each field. `#61` is canonical; `#62` and `#63`
are absorbed into the same contract.

### Input

| Field | Issues |
|-------|--------|
| `mode` | 61, 62, 63 |
| `repo_path` | 62, 63 |
| `startup_command` | 61, 62, 63 |
| `base` | 61 |
| `base_url` | 61, 62, 63 |
| `issue_or_pr` | 61, 62 |
| `acceptance_criteria` | 61, 62, 63 |
| `auth.strategy` | 62 |
| `credential_env_names` | 63 |
| `artifacts_dir` | 61, 62 |
| `viewport` | 63 |
| `device_targets` | 63 |
| `allowed_network` | 63 |
| `forbidden_network` | 63 |
| `prior_screenshots` | 63 |
| `repro_notes` | 63 |
| `yaml_input` | 62 |

### Output

| Field | Issues |
|-------|--------|
| `schema_version` | schema pin (this contract) |
| `mode` | 61, 62, 63 |
| `target` | 61, 62, 63 |
| `target_url` | 61, 62, 63 |
| `status` | 61, 62, 63 |
| `steps` | 61, 62, 63 |
| `acceptance_criteria` | 61, 62, 63 |
| `observed` | 61, 62, 63 |
| `expected` | 61, 62, 63 |
| `observed_mismatches` | 61, 62 |
| `skipped_or_unverified` | 61 |
| `artifacts.screenshots` | 61, 62, 63 |
| `artifacts.video` | 61, 62, 63 |
| `artifacts.trace` | 62, 63 |
| `artifacts.logs` | 61, 62, 63 |
| `artifacts.network_summary` | 63 |
| `console_errors` | 63 |
| `application_logs` | 63 |
| `suggested_next_fix` | 62, 63 |
| `blocked.missing` | 61, 62, 63 |
| `timestamp` | 62 |
| `credential_names` | credentials-by-name rule |

## Markdown view

`render_verification_markdown` projects the JSON. Headings are
`## Behavior verification` (verify mode) or `## Reproduction attempt`
(reproduce mode). Two reports that differ only in `observed` differ in
Markdown only there. Blocked reports name every `missing` entry.
