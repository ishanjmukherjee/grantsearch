"""Draws the Prowl wordmark and the favicon's P, and writes both into the frontend.

    uv run --with numpy --with shapely python design/wordmark/draw.py

The letters are a humanist italic written with a broad-edged pen held at 30
degrees and slanted 9: the stress of the o, the thin horizontals and the
thick turn of the l's tail all come from the nib, none is drawn on. Three
things are then decided by hand rather than by the pen:

- The stance is low. Capitals and ascenders rise little over the x-height
  (630 and 690 over 500) and the letters are wide, so the word is long and
  close to the ground.
- Every stroke that starts at the top is cut on one line rising 27 degrees
  to the right, entered by a wedge (r, w, l) or a spur (P). Every stroke that
  ends on the baseline is cut flat, except the last: the l keeps its exit.
- The w is not written but constructed, its outline the crossings of its four
  strokes' edges, so its three points are sharp.

Round letters and points overshoot the lines they sit on by 10 units, as
they must to look level with flat ones. The favicon's P is the same letter
drawn with a heavier pen, for a size where the wordmark's would break up.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from fit import path
from pen import Pen, half_plane, round_crotches

X, CAP, ASC = 500, 630, 690
OVER = 10  # how far rounds and points pass the baseline, x-height and ascender line
SLANT = 9
NIB = 30  # the pen's angle
CUT = 27  # the rise of the cut across the top of a stroke
GAPS = [12, 12, 24, 28]  # between the ink of P r o w l, set by eye


@dataclass
class Weight:
    width: float  # the nib's
    thick: float
    w_thick: tuple  # the w's down strokes, measured across at the foot and at the x-height
    w_thin: tuple  # and its up strokes
    p_width: float  # the P, stem to the bowl's far side
    p_bowl: float  # and its bowl's height
    spur: float  # how far the P's spur reaches left of its stem


MARK = Weight(118, 29, (80, 88), (42, 48), 326, 372, 26)
ICON = Weight(160, 48, (108, 118), (58, 66), 368, 376, 31)

WEDGE = 40  # how far a wedge reaches left of its stem
WEDGE_DROP = 72  # and how far down the stem its underside joins
BRACKET = 0.5  # how far up from that join the underside turns toward the tip


def quad(p0, p1, p2, n=16):
    return [
        ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0], (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
        for t in np.linspace(0, 1, n)
    ]


def meet(l1, l2):
    """Where two lines cross; each is (x at y=0, dx/dy)."""
    (a, k), (b, m) = l1, l2
    y = (b - a) / (k - m)
    return (a + k * y, y)


class Hand:
    def __init__(self, weight):
        self.wt = weight
        self.pen = Pen(weight.width, NIB, weight.thick, SLANT)
        self.ex, self.ey = self.pen.extent()
        self.at = self.pen.at
        self.stroke = self.pen.stroke
        self.stemdir = 90 - SLANT
        t = math.tan(math.radians(CUT))
        self.cut_rise = t  # upright
        self.cut_angle = math.degrees(math.atan2(t, 1 + t * math.tan(math.radians(SLANT))))  # and once slanted
        across = self.stroke([(0, 600), (0, -100)]).intersection(box(-2000, 249, 2000, 251)).bounds
        self.stem = across[2] - across[0]

    def below(self, x, y, angle=0):
        return half_plane(self.at(x, y), angle, "right")

    def above(self, x, y):
        return half_plane(self.at(x, y), 0, "left")

    def left_of(self, x, y, lean=0):
        return half_plane(self.at(x, y), self.stemdir + lean, "left")

    def right_of(self, x, y):
        return half_plane(self.at(x, y), self.stemdir, "right")

    def bracket(self, tip, join, corner):
        """A wedge's underside: up the stem's edge from the join, turning to the tip."""
        turn = (join[0] + (corner[0] - join[0]) * BRACKET, join[1] + (corner[1] - join[1]) * BRACKET)
        return quad(join, turn, (tip[0], tip[1] - 5))

    def head(self, shape, top):
        """Cuts a stem at x=0 across its top, the cut reaching OVER above top
        at the stem's right edge, and adds the wedge it is entered by."""
        xl, xr = -self.stem / 2, self.stem / 2
        cut = shape.intersection(self.below(xr, top + OVER, self.cut_angle))
        y_left = top + OVER - self.stem * self.cut_rise
        y_tip = y_left - WEDGE * self.cut_rise
        tip = (xl - WEDGE, y_tip)
        wedge = [tip, (xl + 20, y_left + 20 * self.cut_rise), (xl + 20, y_tip - WEDGE_DROP - 20)]
        wedge += self.bracket(tip, (xl, y_tip - WEDGE_DROP), (xl, y_tip))
        return unary_union([cut, Polygon([self.at(*p) for p in wedge]).buffer(0)])

    def P(self):
        wt, ey, xl = self.wt, self.ey, -self.stem / 2
        stem = self.stroke([(0, CAP + 90), (0, -70)])
        # The bowl leaves the top of the stem thin, is thickest on its far
        # side, and comes back thin: the nib runs along both horizontals.
        bowl = self.stroke(
            [
                (-30 - wt.spur, CAP - ey),
                (110, CAP - ey),
                (wt.p_width - self.ex, CAP - wt.p_bowl / 2 + 2),
                (140, CAP - wt.p_bowl + ey),
                (-10, CAP - wt.p_bowl + ey + 6),
            ],
            dirs=[0, 0, 270, 180, 176],
            width=[1, 1, 1.03, 0.9, 0.8],
        )
        p = unary_union([stem, bowl]).intersection(self.below(0, CAP)).intersection(self.above(0, 0)).intersection(self.right_of(xl, 0))
        drop = 58
        tip = (xl - wt.spur, CAP)
        spur = [tip, (xl + 20, CAP), (xl + 20, CAP - drop - 20)] + quad((xl, CAP - drop), (xl, CAP - drop * (1 - BRACKET)), (tip[0], CAP - 5))
        return unary_union([p, Polygon([self.at(*q) for q in spur]).buffer(0)])

    def r(self):
        end, heading, weight = 236, -12, 0.92
        stem = self.head(self.stroke([(0, X + 90), (0, -70)]), X).intersection(self.above(0, 0))
        # The arm springs from low on the stem, as an italic's does, thin where
        # it leaves and full where it ends. It runs on past its end so that
        # the cut, parallel to the stems, crosses it at full weight.
        y_end = X + OVER - self.ey * weight
        arm = self.stroke(
            [(8, 120), (82, X - 112), (end - 4, y_end), (end + 60, y_end - 60 * math.tan(math.radians(-heading)) - 6)],
            dirs=[86, None, heading, heading - 8],
            angle=[10, 4, 0, 0],
            width=[0.55, 0.8, weight, weight],
        )
        return unary_union([stem, arm.intersection(self.left_of(end + 10, X))])

    def o(self):
        rx = 146
        top, bottom = (rx - 14, X + OVER - self.ey), (rx + 14, -OVER + self.ey)
        return self.stroke([top, (0, X / 2 - 8), bottom, (2 * rx, X / 2 + 8), top], dirs=[180, 270, 0, 90, 180])

    def w(self):
        """Drawn slanted as it stands: each edge is a line (x at y=0, dx/dy)."""
        (thick_foot, thick_top), (thin_foot, thin_top) = self.wt.w_thick, self.wt.w_thin
        down, up = -0.17, 0.44  # the lean of a down stroke and of an up stroke
        y_foot, y_apex = -OVER - 14, X + OVER + 14  # where the points would come, before they are blunted
        widen_thick = (thick_top - thick_foot) / (X - y_foot)
        widen_thin = (thin_top - thin_foot) / (X - y_foot)
        line = lambda x, y, k: (x - k * y, k)
        x_at = lambda l, y: l[0] + l[1] * y
        foot1 = -down * (X - y_foot)
        L1, R1 = line(foot1, y_foot, down), line(foot1 + thick_foot, y_foot, down + widen_thick)
        R2, L2 = line(foot1, y_foot, up), line(foot1 - thin_foot, y_foot, up - widen_thin)
        apex = x_at(L2, y_apex)
        R3 = line(apex, y_apex, down)
        L3 = line(apex - (thick_top + widen_thick * (y_apex - X)), y_apex, down - widen_thick)
        foot2 = x_at(L3, y_foot)
        R4, L4 = line(foot2, y_foot, up), line(foot2 - thin_foot, y_foot, up - widen_thin)
        high = X + 60
        outline = [
            (x_at(L1, high), high), (x_at(R1, high), high), meet(R1, L2), (apex, y_apex), meet(R3, L4),
            (x_at(L4, high), high), (x_at(R4, high), high), (foot2, y_foot), meet(L3, R2), (foot1, y_foot),
        ]  # fmt: skip
        w = Polygon(outline).intersection(half_plane((0, -OVER), 0, "left")).intersection(half_plane((0, X + OVER), 0, "right"))
        # The first and last strokes are cut across the top as the stems are.
        first, last = x_at(R1, X + OVER), x_at(R4, X + OVER)
        w = w.intersection(half_plane((first, X + OVER), self.cut_angle, "right").union(half_plane(((first + apex) / 2, 0), 90, "right")))
        w = w.intersection(half_plane((last, X + OVER), self.cut_angle, "right").union(half_plane(((last + apex) / 2, 0), 90, "left")))
        rise = math.tan(math.radians(self.cut_angle))
        y_left = (X + OVER - (first - L1[0]) * rise) / (1 - L1[1] * rise)  # where the cut meets the first stroke's left edge
        y_tip = y_left - WEDGE * rise
        tip = (x_at(L1, y_left) - WEDGE, y_tip)
        y_join = y_tip - WEDGE_DROP
        wedge = [tip, (x_at(L1, y_left) + 20, y_left + 20 * rise), (x_at(L1, y_join) + 20, y_join - 20)]
        wedge += self.bracket(tip, (x_at(L1, y_join), y_join), (x_at(L1, y_tip), y_tip))
        return unary_union([w, Polygon(wedge).buffer(0)])

    def l(self):
        # The one stroke that keeps its exit: the pen turns at the foot, where
        # it runs across the nib and so is at its thickest, and leaves along
        # the nib, at its thinnest.
        end = 112
        body = self.stroke(
            [(0, ASC + 90), (0, 100), (42, self.ey * 0.86 - OVER + 2), (end, 70)],
            dirs=[270, 270, 0, 38],
            width=[1, 1, 0.74, 0.42],
            thick=[1, 1, 0.9, 0.62],
        )
        return self.head(body.intersection(self.left_of(end - 4, 0, lean=-4)), ASC)


def wordmark():
    hand = Hand(MARK)
    parts, x = [], 0.0
    for i, glyph in enumerate([hand.P(), hand.r(), hand.o(), hand.w(), hand.l()]):
        glyph = round_crotches(glyph, 3)
        left, _, right, _ = glyph.bounds
        parts.append(affinity.translate(glyph, x - left, 0))
        x += right - left + (GAPS[i] if i < len(GAPS) else 0)
    return unary_union(parts)


def favicon(size=32, height=0.64):
    """The P, white on the tile the site's icon has always had."""
    p = round_crotches(Hand(ICON).P(), 3)
    left, bottom, right, top = p.bounds
    scale = size * height / (top - bottom)
    dx, dy = (size - (right - left) * scale) / 2, size * (1 - height) / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="7" fill="#4e2a84"/>'
        f'<path fill="#fff" fill-rule="evenodd" transform="translate({dx:.2f} {dy:.2f}) scale({scale:.5f})" d="{path(p, left, top)}"/></svg>\n'
    )


if __name__ == "__main__":
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    mark = wordmark()
    left, bottom, right, top = mark.bounds
    out = {"width": round(right - left, 1), "height": round(top - bottom, 1), "path": path(mark, left, top)}
    (frontend / "src" / "wordmark.json").write_text(json.dumps(out, indent=2) + "\n")
    (frontend / "public" / "favicon.svg").write_text(favicon())
    print(f"wordmark {out['width']} x {out['height']}, {len(out['path'])} bytes of path; cap height is {CAP / out['height']:.3f} of its height")
