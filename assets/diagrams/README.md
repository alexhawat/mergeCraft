# Architecture diagram assets

Committed SVGs for the landing README architecture hero (`<picture>` in `README.md`).

| File | Theme | Referenced from |
|------|-------|-----------------|
| `pipeline-light.svg` | Light (`d2 --theme 0`) | `README.md` `<img>` fallback |
| `pipeline-dark.svg` | Dark (`d2 --theme 200`) | `README.md` `<source media="(prefers-color-scheme: dark)">` |

**Source:** [`docs/diagrams/pipeline.d2`](../../docs/diagrams/pipeline.d2) — PR event → trust tier → analyzers → review agent → verifier → typed findings, with outputs for approval status, inline comments, and optional SARIF upload.

## Regenerate

Requires [`d2`](https://d2lang.com/) on PATH (not a Python dependency):

```bash
make diagrams
```

CI runs `make diagrams-check`, which asserts the committed SVGs exist, are non-empty, and are referenced from `README.md`. Set `MERGECRAFT_REQUIRE_D2=1` on a runner that has `d2` installed to fail when rendered output would drift from the source.

**See also:** [`assets/brand/README.md`](../brand/README.md) (brand palette used in the diagram).
