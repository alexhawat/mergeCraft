# Failure-shaped trajectory harvest

**Audience:** contributor

The trajectory auditor has eight checks. Four of them (`unresolved-failure`,
`ignored-tool-error`, `stale-assumption-after-failure`, `repeated-tool-loop`) cannot be
scored on a happy-path harvest, because those runs never contain the failure shape the
checks detect. This page is the **recipe** for producing that shape on purpose,
without fabricating a label (#859). `scripts/harvest_failure_trajectories.py` is the
script; `make eval-harvest-failures` prints its plan.

**The recipe is shipped; the harvest is not run.** Running it spends model credit, and
its output needs operator labels. The script plans by default and runs nothing without
`--execute`.

## Rules the script enforces

- **Public sources only (the public-sources-only rule).** Trajectories come from mergeCraft's own public pull
  requests or from offline reviews of **public** commits. With `--execute` the script
  asks GitHub whether the repository is public and refuses anything it cannot confirm.
- **Every draft is scanned.** Each trajectory is checked against known secret shapes
  (tokens, keys, bearer headers, URL passwords) before a draft is written; a match drops
  the case whole. Entropy-flagged tokens (repository paths and signature hashes trip it
  constantly) are not a gate, but the draft records `entropy_flagged` so the operator can
  read it before committing.
- **Nothing is labelled.** Every draft carries `truth: null` for all eight checks. The
  operator supplies labels and records them through the label policy API; an agent never
  originates one, so a draft is not scored data until a person has labelled it.

## Phases

| Phase | What it provokes | Check it feeds | Needs |
| --- | --- | --- | --- |
| `environment` | The review runs without a usable user-namespace sandbox and without the unsandboxed override, so shell or analyzer calls fail with an environment class and are not retried | `ignored-tool-error` (environment) | Nothing beyond a provider credential |
| `transient` | The review runs behind a blocked proxy, so network steps fail once with a transient class | `ignored-tool-error` (transient) | Nothing beyond a provider credential |
| `exec` | The review runs with the shell enabled over a commit whose own checks fail, so a command exits non-zero and is either never re-run or re-run byte-identically | `unresolved-failure`, `stale-assumption-after-failure` | Driver-native exec recording (#858), now in the tree |

Phase 4 of the issue (calibration-only negatives for `changed-unread-file`,
`stale-assumption-after-failure` and `missing-completion-signal`) is not scripted: those
are curated additions made by hand under the calibration-only rule.

## Running it

Read the plan first; this runs nothing:

```bash
make eval-harvest-failures HARVEST_COMMITS="<sha> <sha>"
# or: uv run python scripts/harvest_failure_trajectories.py --commit <sha> --phase environment
```

The operator runs the real harvest from a machine with a provider credential:

```bash
uv run python scripts/harvest_failure_trajectories.py \
  --commit <sha> --commit <sha> --phase all --execute
```

Drafts land in `evals/trajectories/harvest-drafts/<case-id>.json`. Each holds the source
(repository, commit, URL), the trajectory, the checks the auditor fires on it as
candidates, the secret-scan result, and the eight null labels.

## After the run

1. Read each draft and its source commit. Drop any that is not what the phase intended.
2. Label the surviving drafts through the label policy API; record the adjudication.
3. Re-run the trajectory scoring to see whether each of the four checks now has at least
   one positive candidate.

## Open question for the maintainer

The private `mergecraft-*-example` fixture repositories are ideal `exec`-phase material
(they carry planted-defect pull requests designed to fail tests) but are not public yet.
They become in-bounds sources once they are made public with attribution; until then the
script will refuse them.
