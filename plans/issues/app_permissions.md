## Verified defect
Audited main `be9993367386b03f982c795ceb1d80e4a0bfcf1d` on 2026-09-22.

[`resolve_tokens`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/utils/token.py#L192) explicitly requests only `contents:read` when push is disabled, or `contents:write, workflows:write` otherwise. Lines 205-219 reuse this installation token as `mcp_token`. [Main](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/main.py#L844) then binds the SCM client to it.

The resulting token lacks reviewer permissions such as `pull_requests:write`, `issues:write`, and `checks:write` even when the App installation has them. Successful minting therefore replaces the job credential with a token that cannot perform review publication and related reviewer API operations. Pre-minted GH_TOKEN takes another path and does not reproduce this defect.

## Verification
A three-case isolated behavioral probe exercised the real `resolve_tokens` and `acquire_installation_token` using httpx MockTransport. With GH_TOKEN absent and synthetic App inputs, captured request bodies were:
```json
{"permissions":{"contents":"read"}}
{"permissions":{"contents":"write","workflows":"write"}}
```
Both selected the returned synthetic installation token for `mcp_token`. No real token was minted and no GitHub write occurred.

GitHub's [installation-token contract](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app) makes the permissions object a restriction, not an addition to all installation permissions. [Creating a PR review](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request) requires Pull requests write permission.

## Acceptance
- Separate git and reviewer token purposes or explicitly mint the minimum complete reviewer permission set appropriate to the enabled operations.
- Preserve push=disabled as read-only git access, trusted/untrusted separation, installation repo scoping and cleanup/revocation of every minted credential.
- Tests use MockTransport to assert wire permission bodies and reviewer operations, rather than pinning an insufficient dictionary.
- Missing App permissions produce a precise diagnostic without exposing credentials; no blanket all-permissions expansion.

Related: #797 covers behavioral testing/floors, not permission correctness; #550 owns the original App identity feature. Priority P1; effort M; fix risk high (authentication boundary). Implementation plan: `plans/003-app-reviewer-permissions.md`.
