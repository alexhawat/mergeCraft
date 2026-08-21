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
