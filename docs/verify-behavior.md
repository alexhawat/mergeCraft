# Behaviour verification

A versioned report that records whether a running app matched its acceptance
criteria — or named what blocked the run. The report is its own artifact. It is
not a typed finding: a behavioural mismatch has no diff line to anchor to.

**Audience:** consumer (operators and agents who will run or consume a report)

## Command

`mergecraft verify-behavior` reproduces a bug or verifies acceptance criteria
against a running app. Invoking the CLI is the opt-in.
`verify_behavior.enabled: false` in `.mergecraft/config.yaml` is a kill
switch and refuses the run (report status `skipped`). The command is
trusted-tier only. On a local operator machine (no `GITHUB_EVENT_PATH` /
`GITHUB_EVENT_NAME`) it runs unless that kill switch is set. In GitHub
Actions it reads those variables: a fork `pull_request` or
`pull_request_target` is inert and the report status is `skipped`, so a
PR-authored `startup_command` does not run. `shell: disabled` is also inert.
`enabled: true` cannot re-enable an untrusted tier.

Live browsing binds to a **CDP host-Chrome driver** under `mergecraft.browser`
— not Playwright, and mergeCraft never launches, downloads, or sandboxes a
browser. Chrome is started by the operator or CI host with
`--remote-debugging-port`; `MERGECRAFT_CDP_URL` (default
`http://127.0.0.1:9222`) points at its HTTP endpoint. Acceptance criteria and
reproduce claims are scored by `mergecraft.jev`; when Jev is unavailable or its
transport fails each criterion is left `unverified` with a named reason rather
than guessed, and the report is `partial` — never an aborted run. When
the CDP endpoint is unreachable the CLI **refuses** (non-zero exit) and, with
`--artifacts-dir`, writes a `skipped` report naming the probed endpoint.
`--allow-stub` is the only way to use the non-browser stub (tests);
`--artifacts-dir` never opts into it. The production Action image does not
include a browser.

Flags:

| Flag | Purpose |
|------|---------|
| `--mode` | `reproduce` or `verify` |
| `--base` | Git base ref |
| `--start-command` | Command that starts the app |
| `--url` | Base URL to open |
| `--criteria-file` | Acceptance criteria, one per line |
| `--artifacts-dir` | Directory for the report JSON and redacted logs |
| `--issue-file` | Issue or repro notes (reproduce) |
| `--input` | YAML verification input |
| `--viewport` | Pixel size, for example `1280x720` |
| `--allow-stub` | Tests only: permit the non-browser stub when live browsing is unavailable |

### Verify a feature

```bash
# Start Chrome with remote debugging, then:
export MERGECRAFT_CDP_URL=http://127.0.0.1:9222
mergecraft verify-behavior \
  --mode verify \
  --url http://127.0.0.1:8765/ \
  --criteria-file criteria.md \
  --artifacts-dir .mergecraft/artifacts/prs/42/verify \
  --start-command 'python -m http.server 8765'
```

`criteria.md` is one criterion per line (`- Clear button removes the image`).
The run writes `report.json` and redacted console logs under `--artifacts-dir`.
Without a reachable CDP endpoint the command does not exit 0 and never reports
a pass — including when `--artifacts-dir` is set.

After navigate, optional YAML `actions` (`click` / `fill` / `type`) are driven
through the `BrowserDriver` protocol. Each acceptance criterion is judged
against the observed page text by the pinned Jev model: one call per criterion
returning a `noul`, mapped in Python at the `0.5` act floor to `pass` or
`fail`. An unavailable judge, a failing Jev transport, a blank page, or a
missing answer leaves the criterion `unverified` and names the reason in
`skipped_or_unverified` — the CLI never invents a local verdict and never aborts
the run. Report status is `pass` only when every
criterion is `pass`; any `unverified`, or a mix of `pass` and `fail`, is
`partial`. Verify with no criteria is `partial`, not `pass`. When
`--start-command` is set, navigate retries for up to 15s on connection
refused so a slow app can come up.

YAML `actions` example:

```yaml
actions:
  - action: fill
    selector: "#email"
    text: user@example.com
  - action: click
    selector: "#submit"
```

### Reproduce a bug

```bash
mergecraft verify-behavior \
  --mode reproduce \
  --url http://127.0.0.1:8765/ \
  --issue-file issue.md \
  --viewport 1280x720 \
  --base origin/main \
  --artifacts-dir .mergecraft/artifacts/issues/61/repro
```

`issue.md` holds the repro notes. The CLI asks the pinned Jev model whether the
observed page reproduces those notes; a non-empty homepage is not a hit. An
unavailable or failing judge is `partial` with a named `repro unverified:`
reason, never `reproduced`. Credentials are env-var **names** only
(`credential_env_names` in YAML); values never appear in the report JSON.

`schema_version` is required and pinned to **`1.0.0`**. The JSON Schema is
derived from the Pydantic models. Markdown is a **view** of that JSON, not a
second source of truth.

## Driver stack

The driver is a thin protocol (`BrowserDriver`): navigate, extract text, click,
fill, type, press key, scroll, screenshot, read/set cookies, and read console.
Live browsing binds to `mergecraft.browser.launch_browser_driver`, a
CDP-backed driver that attaches to a host Chrome over `MERGECRAFT_CDP_URL`.
Nothing in mergeCraft imports Playwright, and mergeCraft never launches,
downloads, or sandboxes a browser — lifecycle stays with the host.
Construction is lazy: it probes `/json/version` but opens no websocket until
the first command. The driver creates its own page target and closes only the
target it created; an existing host tab is never closed.

Start Chrome with `--remote-debugging-port` and set `MERGECRAFT_CDP_URL` when
the default `http://127.0.0.1:9222` is wrong. When the endpoint is unreachable
the CLI refuses with a named `skipped` report rather than raising a raw import
or connection error, including when `--artifacts-dir` is set.

CI (`make ci` / `make test`) never launches a live browser. Unit tests drive an
in-process fake. One live driver case is gated on a reachable endpoint and
self-skips with a named reason (naming CDP and the probed URL) when none
answers, so it is never silently deselected. A real-browser smoke test, if
added later, must be marked `integration` so those targets exclude it.

Cookie handling on the protocol uses name/value dicts. Reports and logs record
credential **names** only — never values. Post-run `screenshot.png` is omitted
until pixel redaction exists — `auth.strategy` is not a reliable signal that the
viewport is secret-free (a `mock` spec can still run against an authenticated
CDP session or fill credentials via actions). A nullable
`artifacts.trace` field may be filled when the driver records tracing at no
extra pipeline cost; there is no video recording pipeline.

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

## What a green verify does and does not prove

A verify report is `pass` only when **every** acceptance criterion is judged
`pass`. That proves the named criteria were observed to hold on the page the
run actually reached — and nothing more.

It does **not** prove:

- that criteria not listed were checked;
- that the page was reached through the production configuration, unless the
  run used the same `--start-command` and `--url`;
- that the judgment is correct. A criterion is judged by the pinned Jev model
  as written; an unavailable judge leaves it `unverified`, never a locally
  fabricated verdict;
- anything the run skipped. An unreachable endpoint, an inert trust tier, a
  disabled shell, a disabled capability, a blocked URL, or an unavailable
  judge produce `skipped` / `blocked` / `partial` with a named reason, never
  `pass`.

A `pass` with no criteria is impossible: verify with no criteria is `partial`.

## Refusal and named skip

A run refuses — non-zero exit, never `pass` — and names why:

| Condition | Report / signal |
|-----------|-----------------|
| CDP endpoint unreachable | non-zero exit; `report.json` status `skipped`, `skipped_or_unverified` starts with `cdp_unavailable:` and names the probed URL |
| Untrusted tier (fork PR, `pull_request_target`) | status `skipped` with the trust reason |
| `shell: disabled` | status `skipped` with the shell reason |
| `verify_behavior.enabled: false` | status `skipped` with the config reason |
| Env credentials named in the input are absent | status `blocked`, `blocked.missing` names them |
| App URL unreachable | status `blocked`, `blocked.missing` names the URL |
| A configured action target is absent | status `blocked`, `blocked.missing` names the step |
| Jev unavailable (disabled, no credential, kill switch) | criteria `unverified` with the skip token named; report `partial` |
| Jev transport fails (`transport_error`) | criteria `unverified` with `transport_error` named; report `partial`, never an aborted run |

An unavailable judge is a named `unverified`, not a pass and not a silent
absence. The same rule holds for the test suite: a live case with no reachable
endpoint reports a named skip in the `-rs` summary, never a quiet deselect.

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
(typically a fork pull request, including when the CLI sees that event via
`GITHUB_EVENT_PATH`) the capability is inert and reports `skipped` with the
reason. The same skip applies when `shell: disabled`. Configuration cannot
re-enable it on an untrusted tier. A `--verification-report` is not consumed
on an untrusted tier (the consume default is fail-closed).

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
| `actions` | click / fill / type steps (this CLI) |

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

## Review consume

Pass a report into an offline review:

```bash
mergecraft review --diff changes.patch \
  --verification-report .mergecraft/artifacts/prs/42/verify/report.json
```

`mergecraft diff-review` accepts the same `--verification-report` flag.
The report is nonce-fenced before it reaches any prompt. Behavioural
results appear in their own `## Behavior verification` section and are
not code findings. A `blocked` report is rendered and names what is
missing. Omitting the flag leaves the review unchanged.
