# Plan 017: Preserve ordinary uppercase repository filenames

- Status: Integrated; independent focused verification passed; final combined-tree CI pending
- Issue: [#827](https://github.com/alexhawat/mergeCraft/issues/827)
- Planned against main `41cf53b3`, 2026-09-22.
- Dependencies: coordinate 001/005; separate central-redactor commit.

## Verified defect and scope

The coordinator reproduced `redact_secrets("docs/REVIEW-DOCTRINE.md") == "<redacted>.md"` on main. The entropy token regex stops before the filename extension; the suffix exemption accepts only short lowercase path components. An ordinary uppercase kebab filename is consequently classified as a dense secret. This affects analyzer output and safe trajectory paths.

Scope: `src/mergecraft/analyzers/redact.py`, existing analyzer redaction tests, and trajectory path regressions in plans 001/005. Follow AGENTS.md, CONTRIBUTING.md and REVIEW-DOCTRINE; preserve trust and secret boundaries. Do not create a local trajectory exception that restores text removed by the shared redactor.

1. Add a failing regression for the shipped doctrine path and ordinary uppercase kebab/snake filename components.
2. Narrowly correct the central filename-suffix classification, reusing existing benign identifier semantics. Do not exempt arbitrary strings merely because they contain a slash or extension.
3. Keep known credential prefixes and arbitrary mixed-case high-entropy values embedded in paths redacted. Use fabricated canaries only; test the whole path, mixed output and final trajectory serialization.
4. Restore coverage of the original legitimate doctrine path in trajectory tests. A read of that path must remain useful, while secret-bearing paths are dropped at the persistence boundary.
5. Run focused analyzer-redaction and trajectory checks through Make, plus touched-code lint/types. The coordinator reviews the complete diff and re-runs these checks before integration; final full CI runs on the integrated branch.

Completion requires ordinary path preservation and unchanged secret-removal assertions. Stop if the proposed exemption would classify an arbitrary high-entropy filename as safe. Report limitations instead of weakening redaction.
