# Open issues sweep 2026-08-22b — Batch GE test plan

Maps **W9 RED** contracts for #415 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D11 — Hermes env names (#415) → W10

| Contract | Tests | Layer |
| --- | --- | --- |
| Hermes manifest lists `GEMINI_API_KEY` | `tests/docs/test_hermes_skill_env_vars.py::test_hermes_manifest_lists_gemini_api_key` | unit |
| Hermes manifest lists `NOUS_API_KEY` | `…::test_hermes_manifest_lists_nous_api_key` | unit |
| Hermes manifest excludes `GOOGLE_API_KEY` | `…::test_hermes_manifest_excludes_google_api_key` | unit |
| Generated Hermes SKILL.md lists `GEMINI_API_KEY` | `…::test_hermes_skill_md_lists_gemini_api_key` | functional |
| Generated Hermes SKILL.md lists `NOUS_API_KEY` | `…::test_hermes_skill_md_lists_nous_api_key` | functional |
| Generated Hermes SKILL.md excludes `GOOGLE_API_KEY` | `…::test_hermes_skill_md_excludes_google_api_key` | functional |
| Manifest env names match `docs/authentication.md` | `…::test_hermes_manifest_env_names_match_authentication_doc` | integration |
| SKILL.md env names match `docs/authentication.md` | `…::test_hermes_skill_md_env_names_match_authentication_doc` | integration |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W10 | all tests in `tests/docs/test_hermes_skill_env_vars.py` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/docs/test_hermes_skill_env_vars.py
uv run pytest -q tests/docs/test_hermes_skill_env_vars.py  # expect 8 XFAIL until W10
```

## W9 evidence (2026-08-22 ✅: 431b0518)

- `skills/harnesses.yaml` Hermes `required_environment_variables` lists `GOOGLE_API_KEY`, omits
  `GEMINI_API_KEY` and `NOUS_API_KEY` (`skills/harnesses.yaml:38-41`).
- Generated `skills/hermes/mergecraft/SKILL.md` frontmatter mirrors the same list.
- `docs/authentication.md` documents `GEMINI_API_KEY` for Google Gemini and `NOUS_API_KEY` for
  Nous Portal (`docs/authentication.md:7-8`).
