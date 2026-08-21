# README demo asset (operator-supplied)

Demo capture path and rules — omit broken GIF/MP4 until a real asset exists.

**Audience:** satellite (scoped README for one directory)

The mergeCraft mark and wordmark are generated and tracked in
[`assets/brand/`](../../assets/brand/) — see
[`assets/brand/README.md`](../../assets/brand/README.md) for the file list and how to
regenerate them. Nothing to add there.

The one binary still missing is the demo capture for the landing README **Visuals** slot:

| File | Purpose |
|------|---------|
| `assets/demo.mp4` | Preferred ~30s screen capture: open PR → `@mergecraft review` → inline findings → approval check |
| `assets/demo.gif` | GIF fallback when MP4 is unavailable — same capture, shorter loop |

Do not invent a placeholder GIF or MP4 in CI — ship the real capture under `assets/`
(alongside `assets/brand/`), then wire the landing README visuals slot to the file.
Until then the README omits the demo `<img>` / `<video>` rather than showing a broken asset.

See [`docs/distribution.md`](../distribution.md) for the full 0.1.0 operator checklist
([#141](https://github.com/alexhawat/mergeCraft/issues/141)).

## See also

- [Landing README](../../README.md) — visuals slot that will reference the demo capture
- [assets/brand/README.md](../../assets/brand/README.md) — brand SVG inventory
- [docs/distribution.md](../distribution.md) — release operator checklist
