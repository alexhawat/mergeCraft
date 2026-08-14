# mergeCraft brand assets

Production SVGs built from the concepts in `.ignorelocal/styles/`. Every glyph is an
**outlined vector path** — no `<text>`, no webfont, no external request. They render
identically in GitHub READMEs, `<img>` tags, Figma, and print.

## Files

| File | Canvas | Use |
|------|--------|-----|
| `mark.svg` | 128×128 | **Default app icon.** Badge + `mC`, adapts to the viewer's colour scheme |
| `mark-dark.svg` | 128×128 | Icon pinned to the dark palette |
| `mark-light.svg` | 128×128 | Icon pinned to the light palette |
| `mark-mono.svg` | 128×128 | Single-colour `mC`, no plate — inherits `currentColor` |
| `lockup.svg` | 278×64 | **Default horizontal logo.** Icon + wordmark, theme-adaptive |
| `lockup-dark.svg` / `lockup-light.svg` | 278×64 | Pinned variants |
| `wordmark.svg` | 281×54 | Wordmark alone, theme-adaptive |
| `wordmark-dark.svg` / `wordmark-light.svg` | 281×54 | Pinned variants |
| `avatar.svg` | 400×400 | GitHub org / social avatar (dark, no hairline) |
| `favicon.svg` | 32×32 | Browser tab — no hairline, larger ink so it survives 16px |

`mark.svg`, `lockup.svg`, `wordmark.svg`, and `favicon.svg` carry an inline
`@media (prefers-color-scheme: light)` block: dark palette by default, light palette
when the viewer is in light mode. Use the pinned `-dark` / `-light` files when you
control the background and want it fixed.

## Palette

Same brand pair as sevn — blue carries the **m**, red carries the **C**, no third colour.

| Role | Dark | Light |
|------|------|-------|
| Blue (`m`) | `#5fb1f7` | `#2a7fc6` |
| Red (`C`) | `#ff3b3b` | `#ff3b3b` |
| Neutral letters | `#ece7e1` | `#1c1917` |
| Badge plate | `#181513` | `#fbf9f6` |
| Badge hairline | `#322c27` | `#ddd5c9` |

## Construction

- **Type:** Inter Tight — `mC` at weight 800, `mergeCraft` at weight 700, both tracked −0.02em.
- **Badge:** corner radius 20% of size; hairline 0.8% of size; `mC` ink 64% of badge width,
  centred on its ink bounds. The favicon overrides this to 80% ink / 22% radius.
- **Lockup:** badge height = 2.3× the wordmark cap height, gap = 0.30× badge width, with the
  wordmark's cap band optically centred on the badge.

## Usage notes

- Keep clear space of at least 25% of the badge height on all sides.
- Don't recolour, rotate, add effects to, or re-letter the mark. Use `mark-mono.svg` where a
  single colour is required.
- `mark-mono.svg` only picks up `currentColor` when the SVG is **inlined** in the document.
  Referenced through `<img src=…>` it falls back to black, since `currentColor` does not cross
  the image boundary. Inline it, or set the `fill` yourself.
- Below ~20px use `favicon.svg`, not `mark.svg` — the hairline disappears and the ink is too
  small in the standard mark.
- Need a raster? `rsvg-convert -w 512 avatar.svg > avatar.png` (GitHub org avatars want PNG).

### In a README

```html
<img src="assets/brand/lockup.svg" alt="mergeCraft" width="330">
```

For explicit control over GitHub's light/dark themes, use `<picture>` with the pinned files:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-dark.svg">
  <img src="assets/brand/lockup-light.svg" alt="mergeCraft" width="330">
</picture>
```

## Regenerating

```bash
uv run --with fonttools==4.63.0 python assets/brand/build_logo.py
```

`build_logo.py` fetches Inter Tight from a pinned `google/fonts` commit into
`assets/brand/.cache/` (gitignored), verifies it against a hardcoded SHA-256, and re-emits
every SVG. Output is deterministic — a clean rebuild is byte-identical, and the checksum
means that stays true even if the pinned commit is later garbage-collected upstream (the
download will fail loudly rather than silently substitute different bytes). Edit the
constants at the top of the script to change proportions or the palette; never hand-edit
the SVGs, they'll be overwritten. Bumping `fonttools` or the pinned font commit is a
deliberate choice — update both the version above and `_FONT_COMMIT`/`FONT_SHA256` in the
script together, and confirm the rebuild is still byte-identical before committing.

Inter Tight is licensed under the [SIL Open Font License 1.1](https://openfontlicense.org/).
The OFL permits embedding outlined glyphs in artwork like these logos; the font binary
itself is not redistributed here (hence the gitignored cache).
