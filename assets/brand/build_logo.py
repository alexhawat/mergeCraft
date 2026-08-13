"""Generate the mergeCraft brand SVG set from outlined Inter Tight glyphs.

Everything is emitted as vector paths — the output has no font dependency.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(__file__).parent
FONT = OUT / ".cache" / "InterTight[wght].ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/intertight/InterTight%5Bwght%5D.ttf"

# Palette lifted from .ignorelocal/styles concepts.
DARK = {"bg": "#181513", "bd": "#322c27", "blue": "#5fb1f7", "red": "#ff3b3b", "neutral": "#ece7e1"}
LIGHT = {
    "bg": "#fbf9f6",
    "bd": "#ddd5c9",
    "blue": "#2a7fc6",
    "red": "#ff3b3b",
    "neutral": "#1c1917",
}

RADIUS = 0.20  # corner radius as a fraction of badge size
INK_W = 0.64  # mC ink width as a fraction of badge size
BORDER = 0.008  # badge hairline as a fraction of badge size


def fetch_font() -> Path:
    """Inter Tight (SIL OFL 1.1). Cached locally; not committed."""
    if not FONT.exists():
        FONT.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["curl", "-sSfL", "-o", str(FONT), FONT_URL],
            check=True,
        )
    return FONT


def load(weight: int) -> tuple[TTFont, int]:
    f = instantiateVariableFont(TTFont(fetch_font()), {"wght": weight}, inplace=True)
    return f, f["head"].unitsPerEm


def layout(font: TTFont, text: str, tracking: float = -0.02):
    """Outline `text` on a y-down baseline at origin. Returns per-glyph paths + ink bounds."""
    upm = font["head"].unitsPerEm
    cmap, gs, hmtx = font.getBestCmap(), font.getGlyphSet(), font["hmtx"]
    glyphs, x = [], 0.0
    bp = BoundsPen(gs)
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}")
        t = Transform(1, 0, 0, -1, x, 0)
        gs[g].draw(TransformPen(pen, t))
        gs[g].draw(TransformPen(bp, t))
        glyphs.append((ch, pen.getCommands()))
        x += hmtx[g][0] + tracking * upm
    return glyphs, bp.bounds


def svg(w: float, h: float, body: str, *, title: str, style: str = "") -> str:
    s = f"<style>{style}</style>\n" if style else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" '
        f'width="{w:g}" height="{h:g}" role="img" aria-label="{title}">\n'
        f"<title>{title}</title>\n{s}{body}</svg>\n"
    )


def theme_style(extra: str = "") -> str:
    return (
        f".bg{{fill:{DARK['bg']}}}.bd{{stroke:{DARK['bd']}}}"
        f".b{{fill:{DARK['blue']}}}.r{{fill:{DARK['red']}}}.n{{fill:{DARK['neutral']}}}"
        "@media(prefers-color-scheme:light){"
        f".bg{{fill:{LIGHT['bg']}}}.bd{{stroke:{LIGHT['bd']}}}"
        f".b{{fill:{LIGHT['blue']}}}.n{{fill:{LIGHT['neutral']}}}}}" + extra
    )


# ---------------------------------------------------------------- mark / badge


def badge(
    size: float,
    mc,
    mc_bounds,
    *,
    cls: bool,
    pal=DARK,
    border=True,
    x=0.0,
    y=0.0,
    ink=INK_W,
    radius=RADIUS,
) -> str:
    """A rounded badge carrying the outlined `mC`."""
    ink_w = mc_bounds[2] - mc_bounds[0]
    s = (ink * size) / ink_w
    cx = x + size / 2 - s * (mc_bounds[0] + mc_bounds[2]) / 2
    cy = y + size / 2 - s * (mc_bounds[1] + mc_bounds[3]) / 2
    bw = BORDER * size
    bg_fill = 'class="bg"' if cls else f'fill="{pal["bg"]}"'
    bd = ""
    if border:
        bd_stroke = 'class="bd"' if cls else f'stroke="{pal["bd"]}"'
        bd = (
            f'<rect x="{x + bw / 2:g}" y="{y + bw / 2:g}" width="{size - bw:g}" height="{size - bw:g}" '
            f'rx="{radius * size - bw / 2:g}" fill="none" {bd_stroke} stroke-width="{bw:g}"/>\n'
        )
    blue = 'class="b"' if cls else f'fill="{pal["blue"]}"'
    red = 'class="r"' if cls else f'fill="{pal["red"]}"'
    paths = "".join(f'<path {blue if ch == "m" else red} d="{d}"/>' for ch, d in mc)
    return (
        f'<rect x="{x:g}" y="{y:g}" width="{size:g}" height="{size:g}" rx="{radius * size:g}" {bg_fill}/>\n'
        f"{bd}"
        f'<g transform="translate({cx:.3f} {cy:.3f}) scale({s:.6f})">{paths}</g>\n'
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    f800, _ = load(800)
    mc, mc_b = layout(f800, "mC", -0.02)

    f700, _ = load(700)
    wm, wm_b = layout(f700, "mergeCraft", -0.02)
    cap = f700["OS/2"].sCapHeight

    written = []

    def write(name: str, content: str) -> None:
        (OUT / name).write_text(content)
        written.append((name, len(content)))

    # --- marks -------------------------------------------------------------
    S = 128.0
    write(
        "mark.svg",
        svg(S, S, badge(S, mc, mc_b, cls=True), title="mergeCraft", style=theme_style()),
    )
    write(
        "mark-dark.svg",
        svg(S, S, badge(S, mc, mc_b, cls=False, pal=DARK), title="mergeCraft"),
    )
    write(
        "mark-light.svg",
        svg(S, S, badge(S, mc, mc_b, cls=False, pal=LIGHT), title="mergeCraft"),
    )

    # Single-colour: inherits `currentColor`, no badge plate.
    s = (0.86 * S) / (mc_b[2] - mc_b[0])
    dx = S / 2 - s * (mc_b[0] + mc_b[2]) / 2
    dy = S / 2 - s * (mc_b[1] + mc_b[3]) / 2
    mono = "".join(f'<path d="{d}"/>' for _, d in mc)
    write(
        "mark-mono.svg",
        svg(
            S,
            S,
            f'<g fill="currentColor" transform="translate({dx:.3f} {dy:.3f}) scale({s:.6f})">{mono}</g>\n',
            title="mergeCraft",
        ),
    )

    # --- favicon: no hairline, more ink, tuned for 16-32px ------------------
    F = 32.0
    fav = badge(F, mc, mc_b, cls=True, border=False, ink=0.80, radius=0.22)
    write("favicon.svg", svg(F, F, fav, title="mergeCraft", style=theme_style()))

    # --- social avatar (400, matches the concept) ---------------------------
    A = 400.0
    write(
        "avatar.svg",
        svg(A, A, badge(A, mc, mc_b, cls=False, pal=DARK, border=False), title="mergeCraft"),
    )

    # --- wordmark + lockup --------------------------------------------------
    def wordmark_paths(cls: bool, pal=DARK) -> str:
        blue = 'class="b"' if cls else f'fill="{pal["blue"]}"'
        red = 'class="r"' if cls else f'fill="{pal["red"]}"'
        neu = 'class="n"' if cls else f'fill="{pal["neutral"]}"'
        out = []
        for i, (ch, d) in enumerate(wm):
            attr = blue if i == 0 else red if ch == "C" else neu
            out.append(f'<path {attr} d="{d}"/>')
        return "".join(out)

    # Wordmark only: box the cap-height band, let the descender hang.
    CAP_PX = 40.0
    ws = CAP_PX / cap
    w_w = (wm_b[2] - wm_b[0]) * ws
    w_h = (wm_b[3] - wm_b[1]) * ws
    for name, cls, pal, style in (
        ("wordmark.svg", True, DARK, theme_style()),
        ("wordmark-dark.svg", False, DARK, ""),
        ("wordmark-light.svg", False, LIGHT, ""),
    ):
        g = (
            f'<g transform="translate({-ws * wm_b[0]:.3f} {-ws * wm_b[1]:.3f}) '
            f'scale({ws:.6f})">{wordmark_paths(cls, pal)}</g>\n'
        )
        write(name, svg(round(w_w, 2), round(w_h, 2), g, title="mergeCraft", style=style))

    # Lockup: badge + wordmark, badge = 2.3x cap height, gap = 0.30x badge.
    B = 64.0
    lcap = B / 2.3
    ls = lcap / cap
    gap = 0.30 * B
    lw_w = (wm_b[2] - wm_b[0]) * ls
    # Vertically centre the cap band (cap-top -> baseline) on the badge centre.
    baseline_y = B / 2 + (lcap / 2)
    tx = B + gap - ls * wm_b[0]
    total_w = B + gap + lw_w
    for name, cls, pal, style in (
        ("lockup.svg", True, DARK, theme_style()),
        ("lockup-dark.svg", False, DARK, ""),
        ("lockup-light.svg", False, LIGHT, ""),
    ):
        body = badge(B, mc, mc_b, cls=cls, pal=pal)
        body += (
            f'<g transform="translate({tx:.3f} {baseline_y:.3f}) '
            f'scale({ls:.6f})">{wordmark_paths(cls, pal)}</g>\n'
        )
        write(name, svg(round(total_w, 2), B, body, title="mergeCraft", style=style))

    for n, size in written:
        print(f"{n:24} {size:>6} B")


if __name__ == "__main__":
    main()
