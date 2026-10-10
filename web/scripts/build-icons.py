"""Rasterise the Academious mark into the PNG and ICO assets in web/public.

The mark is simple geometry - a rounded tile, three round-capped lines and a
dot - so it is drawn here directly with Pillow rather than through an SVG
renderer, which keeps this to Pillow and numpy. The coordinates are the
ones in public/logo-mark.svg and src/components/Logo.tsx, on the same 32-unit
grid; change all three together.

    python web/scripts/build-icons.py [--font PATH]

--font is only used for the wordmark in og-image.png. It defaults to Segoe UI
Bold, which exists on Windows; pass any TrueType face elsewhere.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PUBLIC = Path(__file__).resolve().parent.parent / "public"
SUPERSAMPLE = 8

GRADIENT_START = (0x7D, 0x8A, 0xF0)
GRADIENT_END = (0x63, 0x59, 0xDC)
LINE = (0xFF, 0xFF, 0xFF)
DOT = (0xD4, 0xD0, 0xFB)
CANVAS = (0xF7, 0xF7, 0xFA)
NAVY = (0x17, 0x1B, 0x2E)
GREY = (0x5F, 0x63, 0x73)

# On the 32-unit grid: (x1, x2, y) per line. The favicon variant drops the dot
# and thickens the strokes, because at 16px both would blur away.
MARK_LINES = [(9, 23, 10.5), (9, 19.5, 16), (9, 15.5, 21.5)]
MARK_STROKE = 3.0
MARK_DOT = (22, 21.5, 2.0)
SMALL_LINES = [(8.5, 23.5, 10), (8.5, 19.5, 16), (8.5, 15, 22)]
SMALL_STROKE = 3.8


def _gradient(size: int) -> Image.Image:
    """A top-left to bottom-right linear gradient, matching the SVG's x1=y1=0, x2=y2=32."""
    axis = np.arange(size, dtype=np.float32)
    t = (axis[None, :] + axis[:, None]) / max(2 * (size - 1), 1)
    start = np.array(GRADIENT_START, dtype=np.float32)
    end = np.array(GRADIENT_END, dtype=np.float32)
    rgb = start + (end - start) * t[..., None]
    return Image.fromarray(np.rint(rgb).astype(np.uint8), "RGB")


def _round_line(draw: ImageDraw.ImageDraw, x1: float, x2: float, y: float, width: float, fill) -> None:
    """A horizontal line with round caps: a bar plus a disc at each end."""
    r = width / 2
    draw.rectangle((x1, y - r, x2, y + r), fill=fill)
    draw.ellipse((x1 - r, y - r, x1 + r, y + r), fill=fill)
    draw.ellipse((x2 - r, y - r, x2 + r, y + r), fill=fill)


def render_mark(size: int, *, small: bool = False, radius: float | None = None, full_bleed: bool = False, inset: float = 0.0) -> Image.Image:
    """Draw the mark at `size` pixels, transparent outside the tile.

    `full_bleed` fills the whole square (for maskable and apple-touch icons,
    where the platform applies its own mask). `inset` shrinks the glyph toward
    the centre, as a fraction of the size, to keep it inside a mask's safe zone.
    """
    big = size * SUPERSAMPLE
    unit = big / 32
    tile_radius = 0 if full_bleed else (radius if radius is not None else (7 if small else 8)) * unit

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=tile_radius, fill=255)
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    image.paste(_gradient(big), (0, 0), mask)

    scale = 1 - 2 * inset
    offset = inset * big

    def at(v: float) -> float:
        return offset + v * unit * scale

    draw = ImageDraw.Draw(image)
    lines, stroke = (SMALL_LINES, SMALL_STROKE) if small else (MARK_LINES, MARK_STROKE)
    for x1, x2, y in lines:
        _round_line(draw, at(x1), at(x2), at(y), stroke * unit * scale, LINE)
    if not small:
        cx, cy, r = MARK_DOT
        rr = r * unit * scale
        draw.ellipse((at(cx) - rr, at(cy) - rr, at(cx) + rr, at(cy) + rr), fill=DOT)

    return image.resize((size, size), Image.LANCZOS)


def render_og(font_path: Path) -> Image.Image:
    """The 1200x630 social card: mark, wordmark, one line of promise."""
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), CANVAS)
    mark = render_mark(144)
    image.paste(mark, (120, 190), mark)

    draw = ImageDraw.Draw(image)
    word = ImageFont.truetype(str(font_path), 104)
    tagline = ImageFont.truetype(str(font_path).replace("segoeuib", "segoeui"), 40)
    draw.text((300, 262), "academious", font=word, fill=NAVY, anchor="lm")
    draw.text((122, 420), "New research worth your attention, every morning.", font=tagline, fill=GREY)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/segoeuib.ttf"))
    args = parser.parse_args()

    render_mark(192).save(PUBLIC / "icon-192.png")
    render_mark(512).save(PUBLIC / "icon-512.png")
    # Platform masks cut maskable icons to as little as an 80% circle, so the
    # glyph sits inside that and the gradient runs to every edge.
    render_mark(512, full_bleed=True, inset=0.1).save(PUBLIC / "icon-maskable-512.png")
    # iOS rounds the corners itself and renders transparency as black.
    render_mark(180, full_bleed=True).convert("RGB").save(PUBLIC / "apple-touch-icon.png")

    ico_sizes = [16, 32, 48]
    ico_frames = [render_mark(s, small=s < 32) for s in ico_sizes]
    ico_frames[-1].save(PUBLIC / "favicon.ico", sizes=[(s, s) for s in ico_sizes], append_images=ico_frames[:-1])

    render_og(args.font).save(PUBLIC / "og-image.png", optimize=True)


if __name__ == "__main__":
    main()
