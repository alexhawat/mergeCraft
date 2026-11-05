# Policy evidence

A policy rule with `enforcement: required` names evidence keys under
`evidence.required`. The rule's finding stays at `Major` until every key it names
is present. Once they all are, the rule takes the engine's satisfied path: a
blocking declared severity drops to `Trivial`, and a non-blocking one keeps its
declared value. This page covers where each key comes from during a review, and
why the pull request under review cannot produce its own evidence.

**Nothing a pull request writes about itself counts as evidence.** That excludes
the pull request body, a manifest or config key added on the head branch, and a
check run that a head-branch workflow can post under any name it likes. Every
producer except `requirements` reads from a source the pull request cannot
write. `requirements` reads issues the author may have written: it is
author-traceable, not independent (see below). Each key that stays absent
carries a reason, which the policy row repeats.

## Producers

| Key | Where the evidence comes from | Who can write that source | Why the pull request cannot forge it |
| --- | --- | --- | --- |
| `requirements` | Acceptance criteria in the bodies of the issues the pull request closes (GitHub's closing references, read once at run start). mergeCraft keyword-matches each criterion against the diff. | Whoever can edit those issues, which may be the pull request author. | The author cannot claim the diff satisfies the criteria, because mergeCraft does the matching, and the pull request body is never read for criteria. An issue the author wrote is still author-controlled, so this key proves traceability, not independent review. |
| `xrepo` | The linked-repo manifest (`.mergecraft/linked-repos.yaml`) as read from the base commit, plus this run's review of the linked repositories. | Whoever can merge to the base branch. | A manifest the pull request adds or edits is never used for its own review. Every repository the base declares has to be reviewed in this run, with none omitted. |
| `health_check`, `rollback_plan`, `contract_schema` | The proof declared for the key under `policy.evidence.<key>` in the base-side configuration (the operator-owned snapshot, or the base commit's `.mergecraft/config.yaml`; never the pull request's own copy): either a check run or a workflow artifact on the head commit. | Whoever can merge to the base branch, for the declaration. A GitHub App the operator trusts, or a successful CI run on the head commit, for the proof. | The declaration is read from the base side, which the pull request cannot write. A check run counts only when an App named in `trustedApps` posted it, and `github-actions` is refused. An artifact counts only when a run of the declared workflow file uploaded it, the pull request does not change that file, and the run came from this repository rather than a fork; its document can only vouch for the key and commit it names. |

### `requirements`

The key is present when the linked issues contain at least one acceptance
criterion and the diff evidences every one of them: each maps to `satisfied` or
`partially_satisfied`, with its evidence paths inside the diff. Any of the
following keeps the key absent:

- A criterion that is `contradicted`, `not_evidenced` or `out_of_scope`. The
  reason names that criterion and its state.
- A pull request that closes no issue, or closing issues that have no acceptance
  criteria.
- Linked issues that were never read. A pull request event is required, and if
  the read fails or the pull request closes more issues than fit on one page,
  the issues count as unread. They are never treated as closing nothing.

**What this key does and does not prove.** The criteria are keyword-matched
against the changed paths; nobody reads the code against them. An issue the
pull request author opened is author-controlled text: they choose the criteria
the diff is then matched against. `requirements` therefore proves traceability
from issue to diff, not independent review. The record names each linked issue
and its author's login and says the criteria were keyword-matched, so a reader
can see whose words the rule was cleared on. Pair `requirements` with a key a
pull request cannot shape, such as a declared check run, when a rule needs more
than traceability.

### `xrepo`

The key is present when the base declares at least one linked repository, every
declared repository was reviewed in this run, and the review recorded no
omission. It stays absent, with a reason, in these cases:

- The base declares no linked repositories (`no linked repositories are declared
  on the base`). This also applies when only the pull request's head has a
  manifest.
- The base manifest exists but could not be read, or was not read at all.
- The review never ran, never saw one of the base's repositories, or omitted
  one. An omission happens when a repository is not granted for the run, its
  sibling checkout is missing, or its pin does not match. The reason names each
  repository affected and why.

### Declared proofs: `health_check`, `rollback_plan`, `contract_schema`

With no declaration for a key, the key is absent with `no producer is declared
for <key>; declare policy.evidence.<key> in the base configuration`, and
mergeCraft reads nothing from GitHub for it.

Declarations come from the **base-side configuration, never the pull request's
own copy**, and they resolve the same way the policy rules do:

1. An **operator-owned settings snapshot** wins. This is the configuration a
   `pull_request_target` run captures from the base before it checks out the
   pull request; the base commit is then not consulted.
2. Otherwise mergeCraft reads `.mergecraft/config.yaml` at the pull request's
   **base commit**, the same commit the policy rules are read from, and parses it
   through the settings model. This is a bounded `git` read and the only process
   a producer ever starts.
3. The pull request head's configuration, on disk or in a snapshot that is not
   operator-owned, is never read. A head that removes the base's declaration
   cannot drop it, a head that rewrites it to trust its own App cannot replace
   it, and a `policy.evidence` block only the head adds counts for nothing (the
   key stays absent with the declare-it reason).

A base that cannot be read is unknown, not empty. If no base commit is known,
the base commit is not in the checkout, the file cannot be read, or the settings
model refuses the base config, the key stays absent and the reason names the
base commit (and `.mergecraft/config.yaml` when the file did not parse) rather
than saying nothing was declared. A base commit with no `.mergecraft/config.yaml`
declares nothing.

**Check run** (`checkRun: {name, trustedApps}`). mergeCraft lists the check runs
on the reviewed head commit. A run counts only when all of the following hold:

- its name matches `name` exactly;
- its own `head_sha` is the reviewed commit;
- it was posted by a GitHub App whose slug is in `trustedApps`;
- it has completed with conclusion `success`.

If a trusted run with that name failed, was cancelled, came back neutral or is
still in progress, the key stays absent, even when another run with the same
name succeeded. A run on the base commit or on a branch ref says nothing about
the head, so mergeCraft never queries for it. `github-actions` is refused in
`trustedApps`, because a `pull_request` workflow takes its job names from the
head ref, which the author controls. A workflow that is meant to vouch for a key
has to publish its check run as its own App.

**Artifact** (`artifact: {name, workflow}`). A JSON document that says `ok` is
easy to write; what makes it evidence is which code uploaded it. `workflow` names
the one repo-relative workflow file (for example
`.github/workflows/deploy-proof.yml`) allowed to upload the proof. mergeCraft
lists the workflow runs for the reviewed head commit, and a run's artifact counts
only when all of the following hold:

- the run executed exactly the declared workflow file (the run's `path`). A run
  of any other workflow, including one the pull request adds, and a run with no
  `path` are ignored;
- the pull request does not change that workflow file. A `pull_request` run
  executes the pull request's own copy of the workflow, so a diff that edits it
  could make it upload anything; such a diff voids the artifact;
- the workflow's unchanged status is verifiable. If its changed path was ignored
  by `review.ignorePaths` or the `ignore_paths` Action input, or its patch was
  unavailable, the artifact is refused before any workflow or artifact API call.
  A truncated files listing or an absent/unreadable diff also keeps the evidence
  key absent, because the workflow might have changed outside the delivered diff;
- the run's `head_repository` is the reviewed repository. A fork's run, and a run
  whose head repository is not reported, never count;
- the run completed with `success` and is bound to the head commit.

Runs that fail any of these are skipped, so a forged run listed beside the
operator's never shadows it. From a run that passes, mergeCraft downloads the
artifact called `name`. Its reported size must be known: an archive of unknown
size (GitHub reported none, or not a number) or larger than 1 MiB is refused
before download. Inside the zip mergeCraft looks for exactly one member,
`policy-evidence.json`, of at most 64 KiB uncompressed. The cap applies to the
read itself: mergeCraft never decompresses more than 64 KiB plus one byte. The
record names the artifact, the workflow run and the workflow file.

An untouched workflow file is not the whole story: a `pull_request` run still
executes head-side code that the declared workflow calls, such as scripts, local
actions and reusable workflows, so keep the step that writes the proof document
inline in the declared workflow itself.

The member must be a JSON object of this shape:

```json
{
  "schema": "mergecraft.policy-evidence/1",
  "key": "rollback_plan",
  "head_sha": "<the full head commit SHA the run checked out>",
  "status": "ok",
  "detail": "rollback rehearsed against staging"
}
```

Any of the following keeps the key absent, with a reason naming the artifact:
a different `schema`, a `key` other than the declared one, a `head_sha` other
than the reviewed commit, a `status` other than `ok`, bytes that are not JSON,
and a document over the cap. The record shows `detail` and stores the SHA-256 of
the document bytes as its digest.

A workflow that produces the document writes it after the work it proves has
succeeded, then uploads it. For example:

```yaml
- run: ./scripts/rehearse-rollback.sh
- run: |
    printf '{"schema":"mergecraft.policy-evidence/1","key":"rollback_plan","head_sha":"%s","status":"ok","detail":"rollback rehearsed against staging"}' \
      "$(git rev-parse HEAD)" > policy-evidence.json
- uses: actions/upload-artifact@v4
  with:
    name: rollback-proof
    path: policy-evidence.json
```

## Configuration

`policy.evidence` maps a key to exactly one proof. It lives in
`.mergecraft/config.yaml` on the base branch:

```yaml
policy:
  evidence:
    health_check:
      checkRun:
        name: "Deploy / health"
        trustedApps: ["acme-ci"]
    rollback_plan:
      artifact:
        name: rollback-proof
        workflow: .github/workflows/deploy-proof.yml
```

- Only `health_check`, `rollback_plan` and `contract_schema` take a declaration.
  `requirements` and `xrepo` have their own producers, and any other key has no
  producer, so it is always absent with `no producer exists for <key>`.
- A declaration that names both `checkRun` and `artifact`, or neither, is a
  configuration error.
- `checkRun` needs a non-empty `name` and at least one App in `trustedApps`.
  `github-actions`, in any letter case, is refused.
- `artifact` needs a non-empty `name` and the repo-relative `workflow` file that
  uploads it; an absolute path or one containing `..` is refused.
- Unknown keys are refused at every level, so a misspelt `trustedApps` fails
  loudly instead of silently trusting nobody.

## When producers run

Producers run only when a rule the change set triggers has `evidence.required`,
and only for the keys those rules name. A repository with no such rule makes no
extra GitHub call. The evidence is collected once per diff, alongside the policy
rows, so every verdict seam reads the same population. A re-scoped diff collects
again. Producers read state the run already holds and the GitHub API; the only
process any of them starts is the `git` read of the base commit's config, and
only when there is no operator-owned snapshot. A failed read leaves the key absent and names the error; it never
fails the review.

## What the row shows

For each required key that is present, the policy row lists `evidence present:
<key> (<source>: <detail>)`. The source is one of `linked-issue-criteria`,
`operator-manifest`, `declared-check-run` or `declared-artifact`. If any required
key is missing, the message and the evidence both carry `required evidence
missing: <keys>`, naming only the absent keys, followed by one `why <key> is
missing: <reason>` line for each of them.

## See also

- [`REVIEW-CHECKS.md`](../REVIEW-CHECKS.md), *Policy rules*: enforcement modes,
  where the rules come from, and waivers.
- [`docs/trust-policy.md`](trust-policy.md): which events capture an operator-owned
  snapshot, and when the base commit's configuration applies instead.
