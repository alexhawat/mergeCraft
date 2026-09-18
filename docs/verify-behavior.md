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

The Playwright implementation lives behind the optional `mergecraft[browser]`
extra. `--help` works without that extra. When the extra is installed, the
command launches headless Chromium with async Playwright inside the runner
(no sync `Page.goto`). Without the extra the command fails closed and names
`mergecraft[browser]` — including when `--artifacts-dir` or `--input` is set.
`--allow-stub` is the only way to use the non-browser stub (tests). The
production Action image does not include Playwright.

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
| `--allow-stub` | Tests only: permit the non-browser stub when the extra is absent |

### Verify a feature

```bash
pip install 'merge-craft[browser]'
mergecraft verify-behavior \
  --mode verify \
  --url http://127.0.0.1:8765/ \
  --criteria-file criteria.md \
  --artifacts-dir .mergecraft/artifacts/prs/42/verify \
  --start-command 'python -m http.server 8765'
```

`criteria.md` is one criterion per line (`- Clear button removes the image`).
The run writes `report.json` and redacted console logs under `--artifacts-dir`.
The extra is required for this command; skipping `pip install` with
`--artifacts-dir` still names `mergecraft[browser]` and does not exit 0 as a
pass.

After navigate, optional YAML `actions` (`click` / `fill` / `type`) are
driven through the Playwright protocol. Each acceptance criterion is scored
from the page text against that criterion's own wording (`unverified` when
empty; a criterion that names `still visible` or `mismatch` fails only when
that phrase is on the page; otherwise pass when the criterion's significant
tokens all appear). Verify with no criteria is `partial`, not `pass`. When
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

`issue.md` holds the repro notes. Reproduce is `reproduced` only when those
notes' significant tokens appear in the page text — a non-empty homepage is
not a hit. Credentials are env-var **names** only (`credential_env_names`
in YAML); values never appear in the report JSON.

`schema_version` is required and pinned to **`1.0.0`**. The JSON Schema is
derived from the Pydantic models. Markdown is a **view** of that JSON, not a
second source of truth.

## Optional extra and driver

The driver is a thin protocol (`BrowserDriver`): navigate, extract text, click,
fill, type, press key, scroll, screenshot, read/set cookies, and read console.
Playwright is the one implementation, isolated in
`mergecraft.verify.playwright_driver`. Nothing else in mergeCraft imports
Playwright.

Install the optional extra to use that implementation:

```text
pip install 'merge-craft[browser]'
```

The extra installs the Playwright Python package only. It does not download
browser binaries, and the production Action image does not include a browser.
When the extra is absent, the gate names `mergecraft[browser]` rather than
raising a raw import error, including when `--artifacts-dir` is set.

CI (`make ci` / `make test`) never launches a live browser. Unit tests drive
an in-process fake. A real-browser smoke test, if added later, must be marked
`integration` so those targets exclude it.

Cookie handling on the protocol uses name/value dicts. Reports and logs record
credential **names** only — never values. Playwright tracing may fill the
nullable `artifacts.trace` field at no extra pipeline cost; there is no video
recording pipeline.

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
