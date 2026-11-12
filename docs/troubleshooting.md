# Troubleshooting

Symptom-first fixes for the failures new installs hit most often.

**Audience:** consumer (product and setup documentation)

Start with the commands that read state without changing it:

```bash
mergecraft doctor                     # git, providers, analyzers, auth, config, MCP wiring
mergecraft provider status --github   # roster, credentials, workflow wiring, repo secret presence
mergecraft workflow sync --check      # exits non-zero when a roster model has no credential step in the workflow
```

`provider status --github` needs a token with `repo` scope (`gh auth token` or
`GITHUB_TOKEN`); without one, the remote fields read `unknown`
([agent roster](agent-roster.md)).

## The review never starts, or the check never appears

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| No `mergecraft` check on the pull request | The workflow file is not on the base branch yet, or the trigger does not match the event. The default scaffold listens for `pull_request` (`opened`, `ready_for_review`, `synchronize`) and `workflow_dispatch` only. | Merge the workflow first, then push a commit or run `workflow_dispatch`. Comment triggers are an opt-in pattern in [workflows](workflows.md). |
| The check is missing on a pull request that only touches ignored files | A workflow-level `paths-ignore` skipped the whole run, so no check was reported. If `mergecraft` or `mergecraft-approval` is a required check, the pull request waits. | Drop `paths-ignore` and use the `ignore_paths` Action input instead ([action reference](action-reference.md)); a run that ignores every changed file then passes quickly with "nothing to review". |
| A comment such as `@mergecraft review` does nothing | Only `OWNER`, `MEMBER` and `COLLABORATOR` commenters are authorized, the comment body is never read for authority, and the default scaffold has no comment trigger. | [Comment-trigger authorization](workflows.md#comment-trigger-authorization). |
| A fork pull request is skipped or reviewed without secrets | Fork pull requests are untrusted: no secrets, read-only tools. This is the [trust tier](glossary.md#trust-tier) working as designed. | Review the fork locally with `mergecraft review`, or read the [security model](workflows.md#security-model) for the `pull_request_target` trade-offs. |

## Credentials

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| The run fails at start with an empty secret such as `CLAUDE_CODE_OAUTH_TOKEN` | `provider auth` stores indexed `LLM_PROVIDER_<N>_*` secrets; the workflow passes only the secrets named in its `env:` block. If the two differ, the container never sees the credential. | Run `mergecraft workflow sync --check`. If it reports an unwired provider, run `mergecraft workflow sync --apply` and commit the workflow. Secret names per provider: [provider reference](authentication.md#provider-reference). |
| The hardened template reports that the review was skipped | Its credential gate found none of the secret names it tests for. | Confirm the secret exists (`mergecraft provider status --github`) and that the template is current (`mergecraft workflow sync --check`, then `--apply` if it reports a gap). |
| `refresh token was already used` (ChatGPT subscription login) | `CODEX_AUTH_JSON` rotates its refresh token on use, and the Action does not write the refreshed login back. | Re-run `mergecraft provider auth openai`, or switch to `OPENAI_API_KEY`, which does not expire ([authentication](authentication.md)). |
| `mergecraft review` finds no credential after `provider auth` | The default scope is `github`, which stores an Actions secret and writes no local credential. | Add `--scope local` (or `--scope both`), or use `--dry-run` to print the prompt without calling a model. |
| `gh` errors during `provider auth` | `--scope github` and `--scope both` call `gh secret set`. | `gh auth login`, or use `--scope local`. |
| A model is skipped | There is no credential for that model's provider. | `mergecraft models list`, then authenticate that provider. |

## Results and exit codes

Exit codes are contractual; the full table is [EXIT-CODES](EXIT-CODES.md).

| Code | Meaning | What to do |
|------|---------|------------|
| `10` / `11` | Non-blocking / blocking findings | Read the findings. `11` fails the merge gate by design. |
| `20` | Inconclusive: no verdict was reached | Re-run. Typical causes are a model that returned no structured output, or hunks that never reached the reviewer (the check is `neutral`). To report a coverage gap without making the run inconclusive, set `review.coverage.onIncomplete: warn` ([REVIEW-CHECKS](REVIEW-CHECKS.md)). |
| `30` | Configuration error | `mergecraft config validate`. A YAML syntax error, an unknown key on a security or runtime block, or a duplicate key aborts the run on purpose ([config failure policy](config-failure-policy.md)). |
| `40` | Provider or infrastructure failure | Check the provider credential and quota, then re-run. |
| `50` | Timed out | Raise the Action `timeout` input or shrink the change ([action reference](action-reference.md)). |

`mergecraft-approval` is computed from typed findings and run state, never from
review prose. If it fails, read the blocking findings with
`mergecraft findings export --pr <number>`; prose cannot override a blocker. The
difference between the two checks is in the
[glossary](glossary.md#checks).

## A config change breaks the whole run

`.mergecraft/config.yaml` is strict on security and runtime settings: a key an
older pinned Action image does not know fails the whole config load. Upgrade the
pin first, then write the key ([upgrade](upgrade.md)).

## Still stuck

```bash
mergecraft support-bundle write -o mergecraft-support.tgz   # gzipped, secrets redacted
```

Attach the bundle to an issue at
[github.com/alexhawat/mergeCraft/issues](https://github.com/alexhawat/mergeCraft/issues).
Report security problems through [SECURITY.md](../SECURITY.md), not a public issue.

## See also

- [Installing mergeCraft](install.md)
- [Authentication](authentication.md)
- [Exit codes](EXIT-CODES.md)
- [Upgrade](upgrade.md)
- [Uninstall](uninstall.md)
