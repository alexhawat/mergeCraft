# Merge-attention grade

A compact **low / medium / high** hint for how much human attention a pull request likely deserves before merge. It is an **uncalibrated heuristic** — not a scorecard, not a merge vote, and not wired into `mergecraft-approval` or any exit code.

## Axes

| Axis | Primary evidence |
| --- | --- |
| Alignment | Blast-radius scope/fix codes, terminal verdict, self-assessment |
| Impact / blast radius | `blast_radius.lane` and reason codes |
| Verification | Analyzers, static checks, CI notes, blocking findings, end-to-end proof |
| Rollback cost | Policy `rollback_plan` evidence, migration/destructive lane codes |
| Error detection | Policy `health_check` evidence vs blast-radius lane |

When deterministic evidence is missing, **model judgement** may fill alignment gaps; those verdicts are labelled in the summary table and run record.

## Rubric (internal thresholds)

Overall grade is the **maximum** axis level (low < medium < high). Axis levels map from lane codes, policy evidence presence, blocker counts, and verification gaps. Numeric weights are **not published**; operators tune behaviour via config globs only.

The grade is **uncalibrated**: `medium` on one repository is not comparable to `medium` on another.

## End-to-end proof (#1611)

User-facing globs default to UI (`**/*.tsx`, `**/components/**`, …), CLI (`**/cli/**`, …), and public API paths. Performance-sensitive globs default to `**/perf/**`, `**/benchmark/**`, and similar.

Proof is detected in:

- Pull request description
- Published review summary (including attachments linked in markdown)
- CI artifact basenames ingested into `ci_evidence`
- Files under the run evidence directory (images, recordings, bench outputs)

Missing proof for a user-facing or perf-sensitive change is a **verification gap** on the verification axis (not a nit).

## Configuration

Under `review.mergeAttention` in `.mergecraft/config.yaml`:

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Compute the grade |
| `includeInPacket` | `true` | Store on the merge evidence packet |
| `displayInSummary` | `true` | Append block to the GitHub review summary |
| `userFacingGlobs` | `[]` | Extra globs merged with defaults |
| `perfSensitiveGlobs` | `[]` | Extra perf globs merged with defaults |

Set `enabled: false` to restore pre-feature behaviour (no packet field, no summary block).

## Safety

`decide_approval`, status checks, and terminal verdict enforcement **never read** `merge_attention`. Tests assert that varying the grade does not change gate outcomes.