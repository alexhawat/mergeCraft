# Open issues sweep 2026-08-22b — Batch GE test plan

Maps **W9 RED** contracts for #415 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D11 — Hermes env names (#415) → W10

| Contract | Tests | Layer |
| --- | --- | --- |
| Hermes manifest/skill env var contracts (parametrized) | `…::test_hermes_required_env_var[*]` | unit/functional |
| Manifest and SKILL.md env names match `docs/authentication.md` | `…::test_hermes_env_names_match_authentication_doc` | integration |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W10 | all tests in `tests/docs/test_hermes_skill_env_vars.py` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/docs/test_hermes_skill_env_vars.py
uv run pytest -q tests/docs/test_hermes_skill_env_vars.py  # green since W10 (808763ce)
```

## W9 evidence (2026-08-22 ✅: 431b0518)

- `skills/harnesses.yaml` Hermes `required_environment_variables` lists `GOOGLE_API_KEY`, omits
  `GEMINI_API_KEY` and `NOUS_API_KEY` (`skills/harnesses.yaml:38-41`).
- Generated `skills/hermes/mergecraft/SKILL.md` frontmatter mirrors the same list.
- `docs/authentication.md` documents `GEMINI_API_KEY` for Google Gemini and `NOUS_API_KEY` for
  Nous Portal (`docs/authentication.md:7-8`).
