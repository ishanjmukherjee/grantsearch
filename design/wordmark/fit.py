"""Turns the pen's many-sided polygons into an SVG path of lines and cubic
Beziers: Schneider's curve fitting (Graphics Gems, 1990), with long straight
edges kept as lines and curves broken at corners."""

import math

import numpy as np

from pen import rings


def _bez(c, t):
    m = 1 - t
    return (m**3)[:, None] * c[0] + (3 * m * m * t)[:, None] * c[1] + (3 * m * t * t)[:, None] * c[2] + (t**3)[:, None] * c[3]


def _chord(pts):
    d = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return d / d[-1]


def _generate(pts, u, t1, t2):
    p0, p3 = pts[0], pts[-1]
    b0, b1, b2, b3 = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u**3
    a1 = b1[:, None] * t1
    a2 = b2[:, None] * t2
    c00 = (a1 * a1).sum()
    c01 = (a1 * a2).sum()
    c11 = (a2 * a2).sum()
    tmp = pts - ((b0 + b1)[:, None] * p0 + (b2 + b3)[:, None] * p3)
    x0 = (a1 * tmp).sum()
    x1 = (a2 * tmp).sum()
    det = c00 * c11 - c01 * c01
    seg = np.linalg.norm(p3 - p0)
    if abs(det) > 1e-12:
        al = (x0 * c11 - x1 * c01) / det
        ar = (c00 * x1 - c01 * x0) / det
    else:
        al = ar = 0
    if al < 1e-6 * seg or ar < 1e-6 * seg:
        al = ar = seg / 3
    return np.array([p0, p0 + t1 * al, p3 + t2 * ar, p3])


def _reparam(c, pts, u):
    d1 = 3 * (c[1:] - c[:-1])
    d2 = 2 * (d1[1:] - d1[:-1])
    out = u.copy()
    for i, (p, t) in enumerate(zip(pts, u)):
        m = 1 - t
        q = m**3 * c[0] + 3 * m * m * t * c[1] + 3 * m * t * t * c[2] + t**3 * c[3]
        q1 = m * m * d1[0] + 2 * m * t * d1[1] + t * t * d1[2]
        q2 = m * d2[0] + t * d2[1]
        num = ((q - p) * q1).sum()
        den = (q1 * q1).sum() + ((q - p) * q2).sum()
        if abs(den) > 1e-12:
            out[i] = min(1, max(0, t - num / den))
    return out


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n else v


def _fit(pts, t1, t2, err, out):
    if len(pts) == 2:
        d = np.linalg.norm(pts[1] - pts[0]) / 3
        out.append(np.array([pts[0], pts[0] + t1 * d, pts[1] + t2 * d, pts[1]]))
        return
    u = _chord(pts)
    best = None
    for _ in range(6):
        c = _generate(pts, u, t1, t2)
        dist = np.linalg.norm(_bez(c, u) - pts, axis=1)
        k = int(dist.argmax())
        if best is None or dist[k] < best[0]:
            best = (dist[k], k, c)
        if dist[k] < err:
            out.append(c)
            return
        u = _reparam(c, pts, u)
    k = min(max(best[1], 1), len(pts) - 2)
    tc = _unit(pts[k - 1] - pts[k + 1])
    _fit(pts[: k + 1], t1, tc, err, out)
    _fit(pts[k:], -tc, t2, err, out)


def fit_ring(ring, err, corner=22, straight=34):
    """A closed ring of (x, y) as its start point and commands ('L', p) or
    ('C', c1, c2, p). An edge longer than straight stays a line; a turn of
    more than corner degrees ends a curve; err is how far a curve may stray."""
    p = np.array(ring[:-1] if ring[0] == ring[-1] else ring, dtype=float)
    n = len(p)
    seglen = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1)  # edge i: p[i] -> p[i+1]
    isline = seglen > straight
    brk = np.zeros(n, bool)
    for i in range(n):
        a = p[i] - p[i - 1]
        b = p[(i + 1) % n] - p[i]
        ang = abs(math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], (a * b).sum())))
        if ang > corner or isline[i] or isline[i - 1]:
            brk[i] = True
    if not brk.any():
        brk[0] = True
    start = int(np.argmax(brk))
    idx = [(start + i) % n for i in range(n + 1)]
    cmds = []
    i = 0
    while i < n:
        a = idx[i]
        if isline[a]:
            cmds.append(("L", p[idx[i + 1]]))
            i += 1
            continue
        j = i + 1
        while j < n and not brk[idx[j]]:
            j += 1
        run = p[[idx[k] for k in range(i, j + 1)]]
        if len(run) == 2:
            cmds.append(("L", run[1]))
        else:
            # end tangents: along a neighbouring straight edge if the run leaves it smoothly, else from the run itself
            t1 = _unit(run[1] - run[0])
            t2 = _unit(run[-2] - run[-1])
            prev_a, prev_b = p[idx[i] - 1], p[idx[i]]
            if isline[idx[i] - 1]:
                d = _unit(prev_b - prev_a)
                if (d * t1).sum() > math.cos(math.radians(corner)):
                    t1 = d
            nxt = idx[j]
            if isline[nxt]:
                d = _unit(p[nxt] - p[(nxt + 1) % n])
                if (d * t2).sum() > math.cos(math.radians(corner)):
                    t2 = d
            out = []
            _fit(run, t1, t2, err, out)
            cmds.extend(("C", c[1], c[2], c[3]) for c in out)
        i = j
    return p[start], cmds


def path(shape, left, top, err=0.35):
    """The shape as SVG path data: x measured from left, y down from top, to a tenth of a unit."""
    f = lambda q: f"{q[0] - left:.1f} {top - q[1]:.1f}"
    d = []
    for ring in rings(shape.simplify(0.02)):
        start, cmds = fit_ring(ring, err)
        d.append("M" + f(start))
        for c in cmds:
            d.append("L" + f(c[1]) if c[0] == "L" else "C" + " ".join(f(q) for q in c[1:]))
        d.append("Z")
    return "".join(d)
