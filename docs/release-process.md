# Release process

How mergeCraft cuts a **release candidate**, soaks it, and promotes a stable
version. Contributor Craft mechanics (`craft prepare` / `craft publish`) live in
[CONTRIBUTING.md](../CONTRIBUTING.md#releases-craft). This page is the
process gate around those commands.

**Audience:** contributor.

Config schema versioning and migrations are **out of scope** here (separate
issue). Behavioural migration notes for a cut still belong in that release's
changelog section.

## Release candidate (RC)

1. `craft prepare` (or the Release workflow) cuts `release/<version>` and
   moves `CHANGELOG.md` `## [Unreleased]` into a dated version section.
2. CI/CD on that branch must be green: `make ci`, image build, SBOM + Trivy
   CRITICAL/HIGH, eval regression gate.
3. Tag the candidate as an RC (Craft/`pre-0.0.1` promotes images to `:rc`,
   never `:latest`). Do **not** call the cut stable yet.

## Soak period

An RC soaks before a stable GitHub/PyPI/GHCR promotion:

- Keep the RC published long enough for at least one scheduled **Integration**
  live-provider job and one scheduled **E2E** nightly security slice to pass
  (same preconditions as CONTRIBUTING.md).
- Collect **real-world adoption evidence** sufficient to validate production
  behaviour (dogfood on this repo plus any consumer reports against the RC
  tag). Promote only when that evidence does not contradict the candidate.
- If soak finds a blocker, cut a new RC; do not retag a failed candidate as
  stable.

## Changelog

Every user-visible change lands under `CHANGELOG.md` `## [Unreleased]` before
the cut (Keep a Changelog). Craft copies that block into the version section
at prepare time. Skip only with `#skip-changelog` or the `skip-changelog`
label.

## Migration notes

When a release changes defaults, removes a flag, or otherwise requires a
consumer action, add a **Migration** subsection in that version's changelog
entry (and keep a one-line pointer here if the note is long). Do not invent a
second schema-migration system on this page.

## See also

- [CONTRIBUTING.md](../CONTRIBUTING.md) — Craft prepare/publish
- [CHANGELOG.md](../CHANGELOG.md)
- [support-matrix.md](support-matrix.md) — generated support matrix
- [SECURITY.md](../SECURITY.md) — security-response and disclosure

## Action manifest and consumer pin lifecycle

A source revision and an Action reference have different roles. Let **S** be
built source, **D** its signed image digest, **C** the later commit whose
`action.yml` names D, and **P** the consumer workflow update that pins C.
The deployed path is `uses@C → action.yml@C → D → S`. Pinning S immediately
after its image builds still runs the older digest already stored at S.

CI/CD explicitly requests its required security E2E slice on push and manual
runs. Only approved main, pre-release, release-branch, or version-tag refs can
publish. Images are scanned by digest, signed and attested, then independently
verified before canonical source-tag and mutable-tag promotion. New builds use
run/attempt-specific staging tags, so failed scanning or signing leaves no
unsigned canonical tag that blocks a fresh attempt. Existing source tags are reused only
when the same source and trusted provenance verify; an unsigned collision or
registry outage fails rather than overwriting an immutable tag.

After an approved CI/CD run completes, prepare **two separate reviewed changes**:

1. In a clean isolated worktree checked out at S, set `SOURCE_REVISION` to that
   full commit and `IMAGE_DIGEST` to the verified slim digest, then run
   `make action-manifest-prepare`. This verifies provenance and changes only
   `action.yml`. Review, commit and merge this change. Record its resulting
   manifest commit C; if squash merging, record the actual merged commit.
2. Fetch the target branch. In a clean isolated worktree based on that branch,
   set `MANIFEST_COMMIT` to C and `RELEASE_BASE_BRANCH` to `main` or `pre-0.0.1`,
   then run `make action-pin-prepare`. This requires C to be in the fetched
   target branch, verifies C's image, and updates consumer references to C.
   Review and merge this second change P.
3. Run `make action-image-digest-check` against the updated consumer checkout.
   Successful output records the manifest commit, image digest and built source.
   Observe an actual Action run at C before declaring deployment verified.

Preparation never commits, pushes, creates a PR, or claims checks ran. Repeating
an already satisfied phase reports that state without creating new changes.
An exact, unstaged preparation patch can be repeated; staged files, unexpected
untracked files, and unrelated changes are rejected. An uncommitted manifest
reports `manifest_commit: null`; an already committed manifest reports its actual C.
Consumer preparation supports both literal `uses` references and
`MERGECRAFT_ACTION_SHA` markers, including marker-only workflows.
C may differ from S only in `action.yml`'s `runs.image`; changing entrypoint,
arguments, source, dependencies or build files requires a new built source.
Do not combine C and P into a squash-merged change that discards the referenced C.

`make lint` performs a source image-syntax check and explicitly reports its
provenance as **UNVERIFIED**. It does not depend on publishing the code being
validated. Both CI and CI/CD run a read-only candidate gate over immutable base
and head Git objects: changing `runs.image` verifies the complete new manifest;
changing consumer references verifies every resulting C. Source-only Action
metadata changes can build with the existing image field, but do not endorse
that commit as a deployment manifest. Pinning such a commit still requires its
complete runtime behavior to match the verified built source.
The strict deployment checker fails on missing registry
content, missing tools, invalid signatures, absent tracing, or an unverified
source mapping. Optional offline inspection exits with an unverified status;
it never reports cryptographic verification. Verification requires authenticated
`gh` registry access and `cosign`, with repository, workflow, source revision,
GitHub-hosted runner and issuer constraints.

The image records S in its build metadata. C and D are reported by the external
verifier after publication; they cannot be baked into the image that creates D.
Local contract tests do not establish that production images have been signed
or deployed. Required live acceptance remains a successful release run with
E2E, build, scan, signing, attestation, verification and promotion, followed by
an observed consumer Action run resolving C to D.

### Recovery and pending pin automation

Canonical publication serializes both image kinds by source revision, verifies
both before writing either tag, and checks that registry readback preserves D.
Concurrent runs producing different digests for one S fail instead of overwriting
it. If only one tag was published before a transient failure, retrying accepts
that identical digest and completes the other. The release tooling currently
requires both image kinds in `ghcr.io/alexhawat/mergecraft`; differing
`IMAGE_SLIM` or `IMAGE_ANALYZERS` repositories are explicitly rejected.

For ordinary failed staging builds, rerun all jobs or the failed downstream jobs;
canonical tags have not been written before successful scan/sign/verification.
A legacy unsigned or partially attested canonical source-S tag still deliberately
fails reuse. Recover its original downstream jobs with the captured digest, or
prepare a new source revision; never overwrite it or trust its revision label.

Pending PR #578 combines App identity with older pin automation. Its pin
portion must be reconciled with this two-phase C/P lifecycle before enabling
it: automation that pins the built source S directly would reintroduce the
previous-image defect. App identity remains separate work; this release change
does not register an App, install credentials, or enable that pending workflow.
