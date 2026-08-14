# README demo asset (operator-supplied)

The mergeCraft mark and wordmark are generated and tracked in
[`assets/brand/`](../../assets/brand/) — see
[`assets/brand/README.md`](../../assets/brand/README.md) for the file list and how to
regenerate them. Nothing to add there.

The one binary still missing is the demo capture:

| File | Purpose |
|------|---------|
| `assets/demo.gif` | ~30s screen capture: open PR → `@mergecraft review` → inline findings → approval check |

Do not invent a placeholder GIF in CI — ship the real capture, under `assets/` (alongside
`assets/brand/`), and add the `<img>` back to `README.md` once it exists. Until then the
README simply omits the demo section rather than showing a broken image.

See [`docs/distribution.md`](../distribution.md) for the full 0.1.0 operator checklist
([#141](https://github.com/alexhawat/mergeCraft/issues/141)).
