# Plan 015: Supersede the stale 0.1.0a2 candidate and verify a fresh release

- Status: TODO candidate preparation; publication pending explicit operator approval
- Issue: [#783](https://github.com/alexhawat/mergeCraft/issues/783)
- Priority: P2; effort: M plus CI/soak time; change risk: HIGH for publication.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: Operator-selected technical remediation and corresponding main CI verification. Do not block an honestly uncalibrated alpha merely because 011–014 await human work; do not claim their results in it.

## Intent and verified current state

#783 is an unaccepted Craft publication request for an older source revision, not a product bug or a reusable approval. Its source `f98db2a522015b065c50bb451719052387a8a061` differs from audited main across 158 files, its Full verify job failed, all six targets remain unchecked, and no `accepted` label authorizes publication. A later green code PR, including #817, neither repairs that candidate nor proves any package or image was deployed.

`docs/release-process.md:14–34` requires candidate-specific CI/image/eval evidence and a soak with scheduled live-provider Integration, scheduled nightly security E2E, and real adoption evidence. `CONTRIBUTING.md:146–193` documents Craft prepare/publish. `docs/release-process.md:57–125` separately requires source S → signed digest D → manifest commit C → consumer pin P and an observed Action run. Keep each identity distinct.

```
craft prepare <version>
# Only after candidate-specific verification, soak and operator publication approval:
craft publish <version>
```

This planning task performs none of those state-changing or live operations. A future release task may carry out ordinary preparation/dry-run work within its authorization, but publication remains a separate operator decision for the concrete version and source.

## Scope and execution context

The expected deliverable is primarily operator evidence, not a product-code patch. Inspect `.craft.yml`, `.github/workflows/release.yml`, `.github/workflows/ci-cd.yml`, `pyproject.toml`, `CHANGELOG.md`, `action.yml`, and `docs/release-process.md`; do not alter release plumbing unless a separate evidenced defect is filed and scoped. Candidate-specific CI, image, attestation, manifest/pin, soak and publication receipts are external release records, not repository source files.

Begin in a clean isolated worktree at the exact operator-selected main SHA after the selected fixes merge. Preserve the user's original checkout and local config edit. Run `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` (expected 0), then inspect `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- .craft.yml .github/workflows/release.yml .github/workflows/ci-cd.yml pyproject.toml CHANGELOG.md action.yml docs/release-process.md` before relying on this handoff.

Read AGENTS.md, CONTRIBUTING.md, `docs/_standards/coding-standards.md`, `docs/REVIEW-DOCTRINE.md`, `docs/eval-methodology.md`, and `docs/release-process.md`. Python 3.11+, uv, Make-only recurring commands, strict typed models, loguru and camelCase config aliases apply to any separately approved code fix. Do not weaken trust or release gates, create new `evidence/` artifacts, fabricate human records, or run paid/live work without concrete authorization. Generated files must come from their generator. Conventional Commits use subjects ≤72 characters; no `--no-verify`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Inspect existing candidate | `gh issue view 783 --repo alexhawat/mergeCraft` plus read-only ref/run/package queries | record exact current state; mutate nothing |
| Prepare preview | `craft prepare <explicit-version> --dry-run` | inspect the operator-selected version/branch behavior; do not assume `0.1.0a2` is reusable |
| Required local gate | `make ci` | exit 0 on the exact proposed source; this does not prove deployment |
| Additional local integration | `make test-integration` | exit 0 with supported self-skips recorded accurately |
| Local release diagnostics | `make test-integration-live`, `make npm-audit`, `make workflow-lint` | the live target needs concrete provider authorization; local results do not replace scheduled receipts |
| Deployment identity after C/P | `make action-image-digest-check` | verify manifest commit → signed digest → built source after publication and pin preparation |

All listed Make targets exist at the audited revision. `make ci` already includes `coverage-gate`, so do not repeat an unchanged full coverage run. Replace placeholders only from the candidate record. Listing a live or publication command is not authorization to run it during this plan-only task.

## Ordered steps

### 1. Replace stale candidate evidence

After selected fixes land, record the exact intended main SHA and inspect existing `0.1.0a2` branch/tag/package/image state and referenced check runs. Do not force-overwrite published artifacts or immutable tags. If an immutable artifact exists or Craft reports a collision, use a new operator-selected explicit version and a fresh approval record. Even if nothing was published, do not reuse the stale approval as authority for a different source.

Verification: Read-only state checks and prepare dry-run identify one concrete candidate and all version collisions.

### 2. Prepare and fully verify

Freeze one candidate proposal: exact source S, explicit version, changelog/migration notes, local gate results, known limitations and collision state. Use the documented Release workflow or Craft prepare on that chosen candidate in a future authorized release task. Run CI/CD from the resulting release revision, covering Python build, both images, SBOM, Trivy high/critical gate, signatures/attestations and structural eval. Inspect analyzers-image source metadata as part of image smoke; the audit identified an unverified source-stamping concern, not a proven new bug.

Verification: Every required job and artifact is tied to the candidate SHA; failed/skipped verification cannot certify it.

### 3. Soak and prepare the approval

Follow the existing RC process, requiring at least one successful scheduled live-provider Integration run, one successful scheduled nightly security E2E run, and actual adoption evidence against this exact RC. Local live runs or PR self-skips do not substitute for those receipts. Prepare a publication packet naming the source/revision, package hashes, image digests, signatures/attestations, scheduled runs, adoption evidence, known limitations and all six intended targets. No new claims of calibrated benchmark quality unless 014 has actually completed.

Verification: Candidate verification and soak receipts are complete and reviewable before presenting publication approval.

### 4. Publish only when explicitly authorized

This planning task does not authorize package publication or an accepted label. After operator approval of the concrete publication packet, use Craft's existing publish flow for the exact verified candidate. Verify PyPI, GitHub, slim/slim-latest and analyzers/analyzers-latest targets.

Then prepare and merge the two separately reviewed changes required by `docs/release-process.md`: manifest commit C for verified digest D built from S, followed by consumer pin P to C. Run `make action-image-digest-check` from the updated consumer checkout and observe an actual Action run resolving C to D before declaring deployment verified. Close or supersede #783 only when its historical status and the fresh approval record are represented accurately.

Verification: Target artifacts/tags and actual Action run identity match the approved source and signed digest; publication receipt is recorded.

## Done criteria

- [ ] No stale failed candidate is approved or overwritten blindly.
- [ ] All six intended publish targets and required preconditions have candidate-specific evidence before closure.
- [ ] Scheduled live-provider, scheduled security E2E and adoption soak evidence refer to the exact candidate.
- [ ] Production fixes trace through S → D → C → P and an observed Action run; no code PR is described as deployed by itself.
- [ ] Relevant commands pass with actual results/limitations recorded.
- [ ] `git diff --check` exits0; changed paths stay within scope, plus plan status/changelog.
- [ ] Update this plan and plans/README.md; distinguish preparation complete from blocked human/operator steps.

## Stop conditions and maintenance

Stop on immutable version collisions, missing provenance, failed/cancelled/skipped required gates, unresolved release-blocking security bugs, missing scheduled soak/adoption evidence, or absent explicit publication approval. Do not set `accepted` or force-retag as a shortcut. Also stop/reconcile on materially drifted source, a twice-failed verification, or an out-of-scope change. Do not count skipped work as complete.

The current blockers are concrete: no fresh operator-selected source/version exists; selected remediation is not integrated; #783 points to an old failed source; candidate CI/image/attestation receipts do not exist; soak has not occurred; publication is not approved; and no post-release manifest/pin/observed-run chain exists. Candidate inventory and the checklist can proceed before those events. No release, provider, or live mutation occurs in this planning task.
