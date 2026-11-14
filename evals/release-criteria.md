# mergeCraft 1.0 exit criteria

All criteria must be met before tagging 1.0.

1. Verify on main that revision identity, checkout and findings remain tied to
   the reviewed head. Composed regression tests exercise stale heads, finding
   provenance, verdict integrity and fail-closed delivery together.
2. Publish a reproducible detection report with at least two distinct providers,
   immutable model pins, and at least three complete recorded runs per provider
   on the same frozen, independently human-adjudicated held-out corpus. Every
   case must carry repository context and a closed-world baseline. Report
   deduplicated precision, recall and F1, case-clustered intervals, between-run
   variance, the clean-case false-positive rate, incomplete attempts, median
   latency and median cost with measurement coverage. The clean-case target
   is at most one deduplicated finding per ten adjudicated zero-issue review
   attempts for each provider. Report the number of distinct cases and the
   confidence intervals with the point estimates. Use at least 30 distinct
   clean cases and 30 distinct defect-bearing cases for a comparative claim.
   Repeated runs increase measurement of model variability within those cases.
3. Ship draft-aware review triggers, a read-only review discussion mode and
   a learning workflow that requires maintainer approval before applying
   dismissals, resolutions or reactions to future reviews.
4. Freeze `schemaVersion: 1` and ship `mergecraft config migrate`. Document a
   deprecation policy that emits warnings for at least one minor release
   before removing the deprecated contract.
5. Make the default update path install a released version and verify the
   consumer pin-update automation against a release candidate.
6. Back every configuration advertised as supported in the support matrix
   with a CI lane. Mark community-configured entries separately.
7. Document the CLI commands, Action inputs, MCP tools and exit codes covered
   by the 1.0 stability promise. Mark experimental surfaces explicitly and
   contract-test the supported surface.

The [repeated detection harness](README.md#repeated-held-out-detection-campaign)
implements the campaign and credential-free rescore. Publication depends on
independent human adjudication and judge calibration
([#780](https://github.com/alexhawat/mergeCraft/issues/780),
[#736](https://github.com/alexhawat/mergeCraft/issues/736),
[#735](https://github.com/alexhawat/mergeCraft/issues/735)) and on recorded
live runs. No qualifying detection result has been produced.
