"""Outlines the site's name from Newsreader Italic, for the header and the favicon.

    uv run --with uharfbuzz --with fonttools python design/wordmark/outline.py Newsreader-Italic.ttf

The argument is Newsreader's variable italic, `Newsreader-Italic[opsz,wght].ttf`
(the README says where to get it). The word is shaped by HarfBuzz, so it is
spaced and kerned as the font's designers meant, then written out as one path:
the page needs no font file and the name cannot flash in a fallback face.

Writes frontend/src/wordmark.json and frontend/public/favicon.svg.
"""

import json
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

NAME = "Prowl"
# Where on the font's axes each drawing sits. The header takes the display
# cut. The favicon takes the cut for small text at a heavier weight: at 16px
# the display cut's thin strokes would vanish.
WORD = {"opsz": 72, "wght": 600}
ICON = {"opsz": 16, "wght": 800}
CAP = 700  # the capital's height in the units both drawings are written in


def outline(font_file, text, axes):
    """The text as an SVG path, y down, its left edge at 0 and its top at 0.

    Returns the path with its width and height.
    """
    font = hb.Font(hb.Face(hb.Blob.from_file_path(font_file)))
    font.set_variations(axes)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    glyphs = list(zip(buf.glyph_infos, buf.glyph_positions))

    flat = BoundsPen(None)
    font.draw_glyph_with_pen(font.get_nominal_glyph(ord("H")), flat)
    scale = CAP / flat.bounds[3]

    def draw(pen, dx=0.0, dy=0.0):
        x = 0
        for info, pos in glyphs:
            place = Transform(scale, 0, 0, -scale, (x + pos.x_offset) * scale + dx, -pos.y_offset * scale + dy)
            font.draw_glyph_with_pen(info.codepoint, TransformPen(pen, place))
            x += pos.x_advance

    bounds = BoundsPen(None)
    draw(bounds)
    left, top, right, bottom = bounds.bounds
    path = SVGPathPen(None, ntos=lambda v: f"{v:.1f}".removesuffix(".0"))
    draw(path, -left, -top)
    return path.getCommands(), round(right - left, 1), round(bottom - top, 1)


def favicon(font_file, size=32, height=0.62):
    """The P, white on the tile the site's icon has always had."""
    path, wide, tall = outline(font_file, NAME[0], ICON)
    scale = size * height / tall
    dx, dy = (size - wide * scale) / 2, size * (1 - height) / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="7" fill="#4e2a84"/>'
        f'<path fill="#fff" transform="translate({dx:.2f} {dy:.2f}) scale({scale:.5f})" d="{path}"/></svg>\n'
    )


if __name__ == "__main__":
    font_file = sys.argv[1]
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    path, wide, tall = outline(font_file, NAME, WORD)
    (frontend / "src" / "wordmark.json").write_text(json.dumps({"width": wide, "height": tall, "path": path}, indent=2) + "\n")
    (frontend / "public" / "favicon.svg").write_text(favicon(font_file))
    print(f"wordmark {wide} x {tall}, {len(path)} bytes of path; the capital is {CAP / tall:.3f} of its height")
