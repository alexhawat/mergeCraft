# Supply chain — image scans and vulnerability waivers

mergeCraft publishes container images from [`.github/workflows/ci-cd.yml`](../.github/workflows/ci-cd.yml).
The `sbom-scan` job runs Trivy on every digest that can be promoted to `:latest` or
`:analyzers`, and **HIGH/CRITICAL findings block the pipeline** unless explicitly waived.

This policy is part of the [0.0.1 distribution checklist](https://github.com/alexhawat/mergeCraft/issues/141).

## Blocking scan gate

Every ref that reaches `build-images` can publish a signed digest (`main`, `pre-0.0.1`,
`release/*`, and `v*` tags). The Trivy step uses `exit-code: 1` for
`severity: CRITICAL,HIGH` on all of those refs so a mutable tag cannot move while an
unwaived finding remains. Findings with no upstream fix are excluded (`ignore-unfixed: true`)
and do not block promotion.

## Waiving a finding

When a transitive CVE cannot be fixed immediately:

1. Reproduce the finding locally (or from the `image-scan-reports` workflow artifact).
2. Add an entry to [`.trivyignore`](../.trivyignore) **above** the CVE id:

   ```text
   # justification: <why this is acceptable and what compensating control exists>
   # expiry: YYYY-MM-DD
   CVE-2024-12345
   ```

3. Keep the justification specific (upstream package, fix timeline, exposure surface).
4. Set expiry to the earliest reasonable re-review date — waivers are not permanent.
5. Open a tracking issue if the waiver will outlive the next release.

CI runs `scripts/check_trivyignore_expiry.py` before Trivy scans. Expired entries fail
the job even when the CVE is still listed in `.trivyignore`.

## Operator baseline before promotion

Before the first blocking publish on `pre-0.0.1`, run a baseline Trivy scan against the
current image and either fix or waive every HIGH/CRITICAL finding. Do not promote `:latest`
with an unknown baseline.
