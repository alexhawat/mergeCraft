# Upgrading mergeCraft

How to move the CLI and the GitHub Action to a newer release together.

**Audience:** consumer (product and setup documentation)

mergeCraft has two pieces that you version separately, and they should agree:

| Piece | Where the version lives | Moves with |
|-------|-------------------------|------------|
| The `mergecraft` CLI | The `uv tool install mergecraft-action==<version>` you ran | `uv` |
| The GitHub Action | The `uses: alexhawat/mergeCraft@<full-sha> # v<version>` line in `.github/workflows/mergecraft.yml`, and the `MERGECRAFT_ACTION_SHA` env value beside it | Your workflow file |

The current published release is recorded in
[`consumer-release.json`](consumer-release.json). The CLI and the Action read
the same `.mergecraft/config.yaml`, so a key one of them does not know can break
the other: `trust` and the other security and runtime blocks reject unknown keys
and fail the whole config load ([config failure policy](config-failure-policy.md)).
That is why the order below matters.

## Steps

1. **Read the release notes first.** The [changelog](../CHANGELOG.md) lists
   breaking changes under a **Breaking — action required** heading, each with
   a **Fix**. Docs on `main` can
   describe unreleased behavior, so read the docs at the tag you are installing:
   `https://github.com/alexhawat/mergeCraft/tree/v<version>/docs`.

2. **Bump the Action pin.** In `.github/workflows/mergecraft.yml`, change the
   `uses:` ref to the full 40-character commit SHA of the release and update
   the trailing `# v<version>` comment. Set `MERGECRAFT_ACTION_SHA` to the same
   SHA: the container cannot read its own `uses:` ref, so that env value is how
   a run records which pin it ran. Keep the pin on a full SHA, not a tag, which
   can move ([distribution](distribution.md), [release process](release-process.md#action-manifest-and-consumer-pin-lifecycle)).

3. **Bump the CLI.** Re-run the install with the new version, then confirm it:

   ```bash
   uv tool install mergecraft-action==<version>
   mergecraft --version
   ```

   `mergecraft update` reinstalls from GitHub and, with no flag, installs the
   `main` branch, which is unreleased code. To use it for a release, pass the
   ref: `mergecraft update --branch <tag-or-sha>`.

4. **Re-sync the workflow.** A release can change the scaffolded workflow
   template and the credential wiring it expects:

   ```bash
   mergecraft workflow sync --check    # reports roster models that lack a credential step
   mergecraft workflow sync --apply    # wires the missing ones
   ```

   Review the diff before committing. `mergecraft init --force` overwrites
   scaffolded files and is not needed for an upgrade.

5. **Validate, then open a pull request.**

   ```bash
   mergecraft config validate
   mergecraft doctor
   ```

   Open a pull request with the pin and workflow changes. The first review on
   it runs the new Action against your existing configuration.

## Writing a new config key

Upgrade the Action pin before you add a key the new release introduced. A key
the pinned image does not know fails the whole config load, so a config that is
newer than the pin is a configuration error (exit code `30`), not a no-op. See
[trust policy](trust-policy.md) for an example of the ordering.

## Rolling back

Put the previous SHA back in `uses:` and `MERGECRAFT_ACTION_SHA`, reinstall the
previous CLI version, and remove any config key the older release does not
know. Credentials and the roster are unaffected.

## See also

- [Installing mergeCraft](install.md)
- [Troubleshooting](troubleshooting.md)
- [Release process](release-process.md)
- [Changelog](../CHANGELOG.md)
