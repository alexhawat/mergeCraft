# README and docs assets (operator-supplied)

Binary artwork for the root README and GitHub Pages is **not** checked into this
repository. Add the files below before removing the flagged `<img>` tags in
[`README.md`](../../README.md).

| File | Purpose |
|------|---------|
| `logo.svg` | mergeCraft logo (light/dark variants in one SVG or separate files) |
| `demo.gif` | ~30s screen capture: open PR → `@mergecraft review` → inline findings → approval check |

Do not invent placeholder binaries in CI — ship real assets or leave the README
comments in place until they exist.

See [`docs/distribution.md`](../distribution.md) for the full 0.0.1 operator checklist
([#141](https://github.com/alexhawat/mergeCraft/issues/141)).
