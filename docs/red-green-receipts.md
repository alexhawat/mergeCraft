# Fail-then-pass receipts

A fix pull request has to show that it fixes something: at least one test that failed before the change and passes after it. mergeCraft never runs your tests to find out. Your own CI runs them, on the base commit and on the head commit, and uploads the results as a small JSON receipt. The review reads that receipt, checks it belongs to this pull request, and turns it into the `fix_proof` gate of the blast-radius checklist (see [`blast-radius.md`](blast-radius.md#fix-proof)).

## Which pull requests need one

A pull request is a fix when either is true:

- its title starts with a conventional `fix` type: `fix:`, `fix(scope):`, `fix!:` or `fix(scope)!:`, in any case, after leading whitespace;
- it carries a label named in `review.fixLabels` (default `bug` and `fix`, compared without regard to case). A configured list replaces the default; an empty list turns label detection off.

`review.fixLabels` is honoured only from the pull request base, like `review.ignorePaths`: the base checkout on a `pull_request_target` run, otherwise the base commit's `.mergecraft/config.yaml` read at `pull_request.base.sha`. A change to `fixLabels` in the pull request itself is ignored, so a pull request cannot switch off its own label detection. A base without the key, or one that cannot be read, gives the defaults.

Everything else is `fix.not-required` and passes the gate without a receipt.

## Configuration

```yaml
ciEvidence:
  redGreen:
    artifact: red-green-receipt
    workflow: .github/workflows/red-green.yml
review:
  fixLabels:
    - bug
    - regression
```

`ciEvidence.redGreen` declares one receipt: `artifact` is the workflow artifact that holds it, and `workflow` is the repo-relative workflow file that is the only one allowed to upload it. Both keys are required; an absolute `workflow` path or one with a `..` segment is refused. Unset by default; the base config is still read once per run, but no workflow run is listed or downloaded, and a fix pull request in a repository that declares none gets `fix.no-receipt`, and the reason names `ciEvidence.redGreen`.

Like `review.fixLabels`, the block is honoured only from the pull request base: the base checkout on a `pull_request_target` run, otherwise the base commit's `.mergecraft/config.yaml` read at `pull_request.base.sha`. A block that the pull request adds or rewrites in its own config is ignored, and a base that has no block, cannot be read or does not validate declares nothing. The recorded detail tells the two apart: a base that was read and has no block (or has no config file at all) "declares no" receipt, while a base config the contents API refused, a block that does not validate, or an unknown base commit says the base config "could not be read". One known limit: base YAML that does not parse at all falls back to the default settings, so it reads as a base that declares no receipt.

The receipt is read after the review has its diff, once the `wait-for-ci` step reports `complete`, so forward its outputs to the review job as described in [`ANALYZERS.md`](ANALYZERS.md). A run that skips the agent has no review diff, so its receipt cannot be verified and is `no-receipt`.

## Format

The receipt is a JSON member of the artifact zip, preferably named `red-green.json` (otherwise the first `.json` member is read):

```json
{
  "schema": "mergecraft.red-green/1",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "head_sha": "89abcdef0123456789abcdef0123456789abcdef",
  "tests": [
    {"id": "tests/test_parser.py::test_empty_input", "base": "failed", "head": "passed"},
    {"id": "tests/test_parser.py::test_plain_input", "base": "passed", "head": "passed"}
  ]
}
```

| Key | Meaning |
|---|---|
| `schema` | exactly `mergecraft.red-green/1` |
| `base_sha` | the full SHA of the pull request's base commit the tests ran against |
| `head_sha` | the full SHA of the pull request's head commit |
| `tests` | the tests that matter for the fix, each with `id`, `base` and `head` |

Each `base` and `head` is one of `passed`, `failed`, `error` or `skipped`.

Bounds, all refused rather than truncated:

- at most 1 MB (1 000 000 bytes of UTF-8), checked before anything is decoded; a larger receipt is `invalid` and the detail says it was oversized;
- at most 2 000 tests, each `id` at most 500 characters;
- no other keys, at the top level or in a test; a missing key, a wrong type, an unknown result or another schema id is `invalid`.

## Verdict

| Receipt | Status | Reason on a fix |
|---|---|---|
| at least one test `failed` or `error` on the base, and every listed test `passed` on the head | `proven` | `fix.proven` (low) |
| any other combination: nothing red on the base, or a test not green on the head | `not-proven` | `fix.not-proven` (medium) |
| an empty `tests` list | `no-tests` | `fix.not-proven` (medium) |
| SHAs that are not exactly the pull request's base and head | `mismatch` | `fix.receipt.mismatch` (medium) |
| malformed, over a bound, or another schema | `invalid` | `fix.receipt.invalid` (medium) |
| no successful same-repository run of the declared workflow uploaded one, the pull request changes that workflow, the change set could not be verified, the archive is too large, or the download failed | `no-receipt` | `fix.no-receipt` (medium) |
| the base declares no `ciEvidence.redGreen`, or the base config could not be read | `not-declared` | `fix.no-receipt` (medium) |

A test that is green on both sides is fine beside a red-then-green one: it shows the fix did not break a neighbour. A test that is `skipped` on the head is not a pass.

## Trust

The receipt is data the pull request's own CI produced, so it is trusted only as far as the run that produced it.

A `pull_request` run of the declared workflow executes head-side code: the head's tests, its `conftest.py`, its plugins and any script the workflow calls from the checked-out tree. Every check below binds the receipt to that run, so a receipt proves what the head's own test run reported, and nothing more. It is no defence against an author with push access to the repository, who can make the head's tests or fixtures report whatever they like. Treat `fix.proven` as evidence that the fix comes with a test that fails without it, not as proof that a hostile author could not fake one; review the tests themselves as usual.

Write the receipt in an inline step of the declared workflow, not with a converter script from the head tree: the pull request leaving that workflow untouched is checked below, but a script under `scripts/` that the workflow calls is head-side code like any other. The provenance checks:

- **Only the declared workflow, in this repository, counts.** The artifact is read only from a run of exactly the declared `workflow` file (the run's `path`) whose `head_repository` is the reviewed repository. A run from a fork is never read, even of the declared workflow, and the detail names the fork; a run with no head repository is never read either. A workflow the pull request adds, or any other workflow, cannot supply the receipt, and a forged run listed beside the real one never shadows it.
- **Only a successful run counts.** The run's listing row must say `status: completed`, `conclusion: success` and `head_sha` equal to the pull request head. A failed, cancelled, timed-out or still-running run is never read.
- **The pull request must leave the declared workflow alone.** The check uses the unfiltered change set: every path in the review diff (both sides of a rename), plus the files the review ignored by config (`review.ignorePaths`) and the files GitHub sent no reviewable patch for. If the declared workflow is anywhere in it, nothing that workflow uploads counts. When the change set cannot be verified (no diff, an unreadable diff, or a truncated file listing) the receipt does not count either.
- **Bounded before and after download.** The artifact's listed `size_in_bytes` must be known and at most 2 MiB (2 097 152 bytes); a larger, missing or malformed size is never downloaded. Inside the zip, the receipt member is read at most one byte past the 1 MB cap.
- **Bound to the exact commits.** `base_sha` and `head_sha` must equal the pull request's base and head in full (case does not matter). A short SHA never matches, so a receipt from an older push or another branch is `mismatch`.
- **Never executed.** The zip is opened in memory and only the receipt member is read, at most one byte past the cap. Scripts, Makefiles or test files in the artifact are ignored, and test ids are plain strings that are never run or rendered into a prompt.
- **Author inputs only add the requirement.** A `fix` title or label makes the proof required; nothing in the title, body or labels can satisfy it. The label list itself comes from the pull request base, never from the pull request's own config. A fix that is neither titled nor labelled as one is not asked for a receipt, which is the accepted gap.
- **A proof only passes its own gate.** A `proven` receipt never lowers another reason: a migration stays `high`, and a source change without tests stays `medium`.

The receipt is evidence about your tests, not a test run by mergeCraft. The `fix.*` reason repeats the recorded detail, so a refused receipt says why.

## Producing a receipt

Any CI can write the receipt. The sketch below is a GitHub Actions job: it reads both SHAs from the event file, runs the fix's tests on the head, runs the same tests against the base's source, writes the receipt with an inline step, and uploads it. The job itself must succeed, so test failures are recorded rather than allowed to fail the step.

```yaml
red-green:
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - name: Run the fix's tests on the head and on the base
      run: |
        BASE_SHA=$(jq -r .pull_request.base.sha "$GITHUB_EVENT_PATH")
        HEAD_SHA=$(jq -r .pull_request.head.sha "$GITHUB_EVENT_PATH")
        TESTS="tests/test_parser.py"
        git checkout --quiet "$HEAD_SHA"
        pytest "$TESTS" --junitxml=head.xml || true
        git checkout --quiet "$BASE_SHA" -- src/
        pytest "$TESTS" --junitxml=base.xml || true
        git checkout --quiet "$HEAD_SHA" -- src/
        echo "BASE_SHA=$BASE_SHA" >> "$GITHUB_ENV"
        echo "HEAD_SHA=$HEAD_SHA" >> "$GITHUB_ENV"
    - name: Write the receipt
      run: |
        python - <<'EOF'
        import json, os
        import xml.etree.ElementTree as ET

        def results(path):
            out = {}
            for case in ET.parse(path).iter("testcase"):
                name = f"{case.get('file') or case.get('classname')}::{case.get('name')}"
                tags = {child.tag for child in case}
                out[name] = (
                    "failed" if "failure" in tags else
                    "error" if "error" in tags else
                    "skipped" if "skipped" in tags else
                    "passed"
                )
            return out

        base, head = results("base.xml"), results("head.xml")
        receipt = {
            "schema": "mergecraft.red-green/1",
            "base_sha": os.environ["BASE_SHA"],
            "head_sha": os.environ["HEAD_SHA"],
            "tests": [
                {"id": name, "base": base.get(name, "error"), "head": state}
                for name, state in sorted(head.items())
            ],
        }
        with open("red-green.json", "w", encoding="utf-8") as fh:
            json.dump(receipt, fh)
        EOF
    - uses: actions/upload-artifact@v4
      with:
        name: red-green-receipt
        path: red-green.json
```

The receipt step is inline so that it is covered by the untouched-workflow check; mergeCraft does not ship a converter. The JUnit test ids above are a sketch: shape them to match your runner. Which tests to list is your call: the tests the pull request adds or changes are the usual choice. The checkout of `HEAD_SHA` matters, because the default `pull_request` checkout is a merge commit whose SHA is neither the base nor the head.
