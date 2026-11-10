# Installing mergeCraft

Consumer install paths for the GitHub Action and the local CLI. The landing
[Example 1](../README.md#example-1--auto-review-every-pr) workflow is the
minimal auto-review setup.

## Requirements

<!-- BEGIN:requirements -->
**Requirements:** [uv](https://docs.astral.sh/uv/) is the only prerequisite for the
install; it downloads a compatible Python (3.11+) itself, so no system Python is
needed. The [GitHub CLI](https://cli.github.com) (`gh auth login`) is needed only
for `provider auth --scope github` (the default), which stores the secret
with `gh secret set`; `mergecraft init` and `--scope local` need neither `gh` nor a
network. Two providers need one more CLI at the credential step: the Codex CLI for `openai`
and Claude Code for `anthropic`
([provider table](authentication.md)).
<!-- END:requirements -->

A provider credential is also required: a Claude Pro/Max or ChatGPT Plus/Pro subscription, or an API key.

mergeCraft supports **GitHub** repositories only. GitLab support is planned via
the `ScmProvider` abstraction.

## Path A — GitHub Action (no local Python)

Add a workflow that uses the Docker Action. Pin to an immutable ref — a full
commit SHA, or a release tag ([`docs/distribution.md`](distribution.md)).

1. Copy the workflow from [Example 1 in the README](../README.md#example-1--auto-review-every-pr)
   to `.github/workflows/mergecraft.yml`.
2. In the repository's **Settings → Secrets and variables → Actions**, add the
   credential for one provider. The secret names for every provider are in the
   [provider table](authentication.md#provider-reference). The workflow's `env:`
   block must pass the secret you add to the step, as Example 1 does for
   `CLAUDE_CODE_OAUTH_TOKEN`.
3. Open a pull request, or run the workflow with `workflow_dispatch`.

For a pinned runtime without managing Python versions, the container image ships
a compatible interpreter; no local Python install is needed.

## Path B — local CLI

PyPI carries the pre-release `mergecraft-action` (the CLI binary stays
`mergecraft`):

```bash
uv tool install mergecraft-action==0.1.0a5
mergecraft --install-completion   # bash/zsh/fish — see --show-completion
mergecraft init   # writes .mergecraft/config.yaml + .github/workflows/mergecraft.yml
```

Docs on `main` may describe unreleased behavior, including CLI selection rules
and review fixes that this alpha does not contain. Use the
[matching release docs](https://github.com/alexhawat/mergeCraft/tree/v0.1.0a5/docs)
for the installed version.

For intentional development testing, replace `<full-commit-sha>` below with
a verified 40-character commit SHA. This installs unreleased source; it is
separate from the published alpha above:

```bash
uv tool install "mergecraft-action @ git+https://github.com/alexhawat/mergeCraft@<full-commit-sha>"
```

Then authenticate and open a pull request — details in the README install steps
and [`docs/authentication.md`](authentication.md).

## Docker-only consumers

Follow [Path A](#path-a--github-action-no-local-python): the Action workflow plus
one provider secret in GitHub Actions. You do not need `uv tool install` on your laptop unless you want local
`mergecraft review` runs.

**See also:** [`docs/cli.md`](cli.md) · [`docs/action-reference.md`](action-reference.md) · [`docs/distribution.md`](distribution.md)
