"""Strokes of a broad-edged pen.

A stroke is a centre line through knots, drawn as Hobby's splines (the curves
of METAFONT), and a nib: a rounded bar of some width, thickness and angle,
each of which may change from knot to knot. The ink a stroke leaves is the
union of the nib's positions along the line, so a stroke is thick where it
runs across the nib and thin where it runs along it.

Units are 1000 to the em, y up, the baseline at 0. Knots are given upright and
the centre line is slanted before the nib is drawn along it, so the slant
leans the letters without thinning their strokes as shearing an outline would.
"""

import math

import numpy as np
from shapely import affinity
from shapely.geometry import MultiPoint, MultiPolygon, box
from shapely.ops import unary_union


def _rho(theta, phi):
    """Hobby's velocity function: how far a control point sits along its tangent."""
    a = math.sqrt(2) * (math.sin(theta) - math.sin(phi) / 16) * (math.sin(phi) - math.sin(theta) / 16)
    num = 2 + a * (math.cos(theta) - math.cos(phi))
    den = 1 + 0.5 * (math.sqrt(5) - 1) * math.cos(theta) + 0.5 * (3 - math.sqrt(5)) * math.cos(phi)
    return num / den


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def hobby(knots, dirs=None):
    """Cubic segments through knots, as (p0, c1, c2, p3) complex tuples.

    dirs gives the heading in degrees at a knot, or None to leave it to the
    curve, which then keeps its curvature continuous there.
    """
    z = [complex(*k) for k in knots]
    n = len(z) - 1
    dirs = dirs or [None] * (n + 1)
    delta = [z[k + 1] - z[k] for k in range(n)]
    if n == 1 and dirs[0] is None and dirs[1] is None:
        return [(z[0], z[0] + delta[0] / 3, z[1] - delta[0] / 3, z[1])]
    d = [abs(x) for x in delta]
    psi = [0.0] * (n + 1)
    for k in range(1, n):
        psi[k] = _wrap(math.atan2(delta[k].imag, delta[k].real) - math.atan2(delta[k - 1].imag, delta[k - 1].real))
    A = np.zeros((n + 1, n + 1))
    b = np.zeros(n + 1)
    for k in range(n + 1):
        if dirs[k] is not None:
            ref = delta[k] if k < n else delta[n - 1]
            A[k, k] = 1
            b[k] = _wrap(math.radians(dirs[k]) - math.atan2(ref.imag, ref.real))
        elif k == 0:
            A[0, 0] = A[0, 1] = 1
            b[0] = -psi[1]
        elif k == n:
            A[n, n - 1] = A[n, n] = 1
        else:
            A[k, k - 1] = 1 / d[k - 1]
            A[k, k] = 2 / d[k - 1] + 2 / d[k]
            A[k, k + 1] = 1 / d[k]
            b[k] = -(2 / d[k - 1]) * psi[k] - (1 / d[k]) * psi[k + 1]
    theta = np.linalg.solve(A, b)
    segs = []
    for k in range(n):
        th = theta[k]
        ph = -theta[k + 1] - psi[k + 1]
        u = z[k] + delta[k] * complex(math.cos(th), math.sin(th)) * _rho(th, ph) / 3
        v = z[k + 1] - delta[k] * complex(math.cos(-ph), math.sin(-ph)) * _rho(ph, th) / 3
        segs.append((z[k], u, v, z[k + 1]))
    return segs


def _sample(segs, per=48):
    """Points along the segments, each with its place among the knots (a float)."""
    pts, ts = [], []
    for i, (p0, c1, c2, p3) in enumerate(segs):
        for j in range(per + (1 if i == len(segs) - 1 else 0)):
            t = j / per
            m = 1 - t
            pts.append(m**3 * p0 + 3 * m * m * t * c1 + 3 * m * t * t * c2 + t**3 * p3)
            ts.append(i + t)
    return pts, ts


def _eased(vals, ts):
    """One value per point: vals is a single number, or one per knot, eased between knots."""
    if not isinstance(vals, (list, tuple)):
        return [float(vals)] * len(ts)
    out = []
    for t in ts:
        k = min(int(t), len(vals) - 2)
        f = t - k
        f = f * f * (3 - 2 * f)
        out.append(vals[k] * (1 - f) + vals[k + 1] * f)
    return out


class Pen:
    def __init__(self, width, angle, thick, slant, squareness=2.2):
        self.width, self.angle, self.thick, self.slant = width, angle, thick, slant
        # The nib's outline is a superellipse: 2 is an ellipse, higher is squarer.
        e = 2.0 / squareness
        turn = np.linspace(0, 2 * math.pi, 40, endpoint=False)
        self.unit = [complex(math.copysign(abs(math.cos(t)) ** e, math.cos(t)), math.copysign(abs(math.sin(t)) ** e, math.sin(t))) for t in turn]

    def extent(self):
        """How far the nib reaches from its centre in x and in y."""
        a, b, t = self.width / 2, self.thick / 2, math.radians(self.angle)
        return math.hypot(a * math.cos(t), b * math.sin(t)), math.hypot(a * math.sin(t), b * math.cos(t))

    def at(self, x, y):
        """An upright point, slanted."""
        return (x + y * math.tan(math.radians(self.slant)), y)

    def stroke(self, knots, dirs=None, width=1.0, angle=0.0, thick=1.0):
        """The ink of one stroke. width and thick multiply the pen's, and
        angle is added to the pen's, in degrees; each may be one per knot."""
        segs = [tuple(complex(*self.at(p.real, p.imag)) for p in s) for s in hobby(knots, dirs)]
        pts, ts = _sample(segs)
        nibs = []
        for p, w, a, h in zip(pts, _eased(width, ts), _eased(angle, ts), _eased(thick, ts)):
            a = math.radians(a + self.angle)
            u = complex(math.cos(a), math.sin(a))
            nib = [p + u * complex(q.real * w * self.width / 2, q.imag * h * self.thick / 2) for q in self.unit]
            nibs.append([(q.real, q.imag) for q in nib])
        return unary_union([MultiPoint(nibs[i] + nibs[i + 1]).convex_hull for i in range(len(nibs) - 1)])


def half_plane(point, angle, keep, size=4000):
    """The side of a line through point, heading angle degrees: keep 'left' or 'right' of that heading."""
    b = box(-size, 0 if keep == "left" else -size, size, size if keep == "left" else 0)
    return affinity.translate(affinity.rotate(b, angle, origin=(0, 0)), point[0], point[1])


def round_crotches(shape, r):
    """Fills inside corners to radius r, leaving outside corners sharp."""
    return shape.buffer(r, join_style="mitre", mitre_limit=20).buffer(-r, quad_segs=24)


def rings(shape):
    out = []
    for p in shape.geoms if isinstance(shape, MultiPolygon) else [shape]:
        out.append(list(p.exterior.coords))
        out.extend(list(i.coords) for i in p.interiors)
    return out
