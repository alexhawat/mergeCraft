# Lane A AP1 — contract → test mapping for privilege & execution boundary

# Audit remediation — lane A (privilege & execution)

| Contract | Finding | Green wave | Test module |
| --- | --- | --- | --- |
| Root-side git ignores hostile `.git/config` | MCB-01 | AP2 | `tests/security/test_hostile_git_config.py` |
| `git_argv` pins safe config keys | MCB-01 | AP2 | `tests/utils/test_git_hardening.py` |
| `.git` not chowned to agent | D3 | AP2 | `tests/utils/test_privilege_chown.py` |
| Manifest rev leading-dash guard | MCB-33 | AP2 | `tests/xrepo/test_rev_parse_guards.py` |
| Bare `["git", …]` lint checker | D2 | AP2 | `tests/ci/test_git_argv_lint.py` |
| Capability probes not CI-gated | MCB-09 | AP3 | `tests/analyzers/test_sandbox_probes.py` |
| Skip finding visible | MCB-09 | AP3 | `tests/analyzers/test_sandbox_skip_visibility.py` |
| Unsandboxed shell fail-closed | MCB-07 | AP3 | `tests/mcp/test_shell_fallback.py` |
| Netns absence removes capability | MCB-10 | AP3 | `tests/mcp/test_network_namespace.py` |
| No secrets in argv | MCB-08 | AP4 | `tests/mcp/test_shell_spawn_argv.py` |
| Git invariant in every branch | MCB-25 | AP4 | `tests/mcp/test_shell_git_invariant.py` |
| OpenCode review permissions | MCB-06 | AP5 | `tests/agents/test_opencode_permissions.py` |
| Review integrity canaries | MCB-06 | AP5 | `tests/security/test_review_canary.py` |
| Image identity gate | MCB-24 | AP6 | `tests/utils/test_privilege_identity.py` |
| Hardened setpriv argv | MCB-32 | AP6 | `tests/utils/test_privilege_identity.py` |
| Uid-independent prep tests | MCB-24 | AP6 | `tests/prep/test_prep_fail_closed.py` |
| Prep env allowlist | MCB-22 | AP7 | `tests/prep/test_prep_env.py` |
| Lockfile selection order | MCB-22 | AP7 | `tests/prep/test_prep_selection.py` |
| Dedicated prep venv | MCB-22 | AP7 | `tests/prep/test_prep_venv.py` |

## Host vs container (D17 / D18)

| Suite | Host | Container (`mergecraft:lane-a`) |
| --- | --- | --- |
| AP1.1 git hardening | yes | optional |
| AP1.2 sandbox probes (real mount/unshare) | partial | yes for mount probes |
| AP1.3 shell argv | yes (mocked Popen) | yes for sudo branch |
| AP1.4 OpenCode | yes | no |
| AP1.5 privilege identity / setpriv | partial | yes |
| AP1.6 prep | yes | no |

Cross-wave reds use `@pytest.mark.xfail(strict=False)` until the greening wave lands.
