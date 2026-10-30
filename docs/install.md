# Installing mergeCraft

Consumer install paths for the GitHub Action and the local CLI. The landing
[Example 1](../README.md#example-1--auto-review-every-pr) workflow is the
minimal auto-review setup.

## Requirements

- **Python 3.11+** when installing the CLI locally ([`docs/dev/python-version-floor.md`](dev/python-version-floor.md))
- [uv](https://docs.astral.sh/uv/) for `uv tool install`
- An authenticated [GitHub CLI](https://cli.github.com) (`gh auth login`) for `mergecraft init` and `mergecraft provider auth`
- One provider credential (Claude Pro/Max, ChatGPT Plus/Pro, or an API key)

mergeCraft **0.1.0** supports **GitHub** repositories only. GitLab support is
planned via the `ScmProvider` abstraction.

## Path A — GitHub Action (no local Python)

Add a workflow that uses the Docker Action. Pin to an immutable ref — a git tag
when one exists, or a full commit SHA until the first release tag is cut
([`docs/distribution.md`](distribution.md)).

See [Example 1 in the README](../README.md#example-1--auto-review-every-pr).

For a pinned runtime without managing Python versions, the container image ships
a compatible interpreter; no local Python install is needed.

## Path B — local CLI

PyPI carries the pre-release `mergecraft-action` (the CLI binary stays
`mergecraft`):

```bash
uv tool install mergecraft-action==0.1.0a4
mergecraft --install-completion   # bash/zsh/fish — see --show-completion
mergecraft init   # writes .mergecraft/config.yaml + .github/workflows/mergecraft.yml
```

To run an unreleased commit, pin the distribution to the repository instead:

```bash
uv tool install "mergecraft-action @ git+https://github.com/alexhawat/mergeCraft"
```

Then authenticate and open a pull request — details in the README install steps
and [`docs/authentication.md`](authentication.md).

## Docker-only consumers

Use the Action workflow from Example 1 and set provider secrets in GitHub Actions.
You do not need `uv tool install` on your laptop unless you want local
`mergecraft review` runs.

**See also:** [`docs/cli.md`](cli.md) · [`docs/action-reference.md`](action-reference.md) · [`docs/distribution.md`](distribution.md)
