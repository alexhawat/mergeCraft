# Contributing

## Setup

```bash
make setup
```

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

## Checks

```bash
make lint
make typecheck
make test
make ci
```

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `chore:`, `test:`, `ci:`, `refactor:`. Subject ≤ 72 characters.

## Layout

- `src/mergecraft/` — package (src layout)
- `tests/` — mirrors package areas
- `Makefile` — single command surface (sevn-style)
- Docker Action via root `Dockerfile` + `action.yml`

## Notes

- Application code uses **loguru** only (no stdlib `logging` outside `src/mergecraft/logging/`).
- This is a standalone BYOK port — do not add proprietary SaaS clients.

## Naming (S1)

| Surface | Spelling |
|---------|----------|
| GitHub repo | `mergeCraft` (camelCase) |
| Python package / import | `mergecraft` (lowercase) |
| CLI binary | `mergecraft` (not `mc` — Midnight Commander collision) |
| PyPI distribution | `merge-craft` (reserved conceptually; no publish workflow) |
| Container image | `ghcr.io/alexhawat/mergecraft` (lowercase, hardcoded) |
| MCP server | `mergecraft` → `mcp__mergecraft__*` / `mergecraft_*` |
| Config directory | `.mergecraft/` |

Never interchange repo spelling with package spelling in code.
