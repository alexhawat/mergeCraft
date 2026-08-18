# DG9 SCM abstraction — test plan

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG9)
Worktree: `../mergecraft-dg9-scm-abstraction` @ `wave/dg9-scm-abstraction`
Authoring wave: **DG9.1** (tests-first — this file). Implementation: **DG9.2**.
xfail-reconciliation: **post-DG9.2** (remove `_DG9_2_XFAIL` markers).

D10 locks protocol-before-adapters: extract ``ScmProvider`` from
``utils/github.py`` and the GitHub ``mcp/`` tools, reimplement GitHub as the
first adapter with no behaviour change, then add at most one further adapter
that declares unsupported capabilities instead of emulating them.

Target API (DG9.2):

- ``ScmProvider`` protocol, ``ScmCapability``, ``protocol_operation_names``,
  ``validate_provider``, ``resolve_scm_provider`` on `src/mergecraft/scm/protocol.py`
- ``GitHubScmAdapter`` on `src/mergecraft/scm/github.py`
- ``GitLabScmAdapter`` (or demand-gated stub) on `src/mergecraft/scm/gitlab.py`
- ``UnsupportedScmCapability`` on `src/mergecraft/scm/errors.py`
- ``checkout_pull_request`` on `src/mergecraft/scm/checkout.py`
- ``ToolContext.scm: ScmProvider`` replaces direct ``github: GitHubClient`` in core

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **DG9.2** | `test_every_github_operation_is_expressible_through_the_protocol` | `green after DG9.2: ScmProvider protocol extraction` | pending |
| **DG9.2** | `test_no_github_specific_type_leaks_into_core` | same | pending |
| **DG9.2** | `test_review_publication_goes_through_the_protocol` | same | pending |
| **DG9.2** | `test_checkout_and_diff_semantics_are_preserved` | same | pending |
| **DG9.2** | `test_one_additional_provider_satisfies_the_protocol` | same | pending |
| **DG9.2** | `test_unsupported_capability_is_declared_not_faked` | same | pending |

`test_github_adapter_behaviour_is_unchanged` has **no** xfail — behavioural
snapshot over GitHub MCP tools captured on ``origin/pre-0.0.1`` before extraction.

## Contract matrix

| # | Decision / convention | Layer | Scenario | Primary test |
|---|----------------------|-------|----------|--------------|
| DG9.1a | D10 — protocol covers GitHub REST + MCP | unit | REST helpers + MCP tool names map to protocol ops | `test_every_github_operation_is_expressible_through_the_protocol` |
| DG9.1b | no behaviour change | integration | MCP tools produce same outputs + API call sequence | `test_github_adapter_behaviour_is_unchanged` |
| DG9.1c | D10 — no GitHub leak in core | unit | ``ToolContext.scm`` not ``github``; no ``ctx.github`` in core MCP | `test_no_github_specific_type_leaks_into_core` |
| DG9.1d | publication boundary | integration | ``publish_pull_request_review`` delegates to ``ScmProvider`` | `test_review_publication_goes_through_the_protocol` |
| DG9.1e | checkout semantics | unit/integration | incremental diff + ``lastReviewedSha`` preserved | `test_checkout_and_diff_semantics_are_preserved` |
| DG9.1f | D10 — second adapter | unit | non-GitHub adapter passes ``validate_provider`` | `test_one_additional_provider_satisfies_the_protocol` |
| DG9.1g | capability honesty | error | unsupported ops raise ``UnsupportedScmCapability`` | `test_unsupported_capability_is_declared_not_faked` |

## Acceptance (DG9.1)

- 7 tests collected
- 1 passes (`test_github_adapter_behaviour_is_unchanged`)
- 6 RED (`xfail(strict=False)`)
