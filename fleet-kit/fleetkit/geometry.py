"""Exact geometry for piecewise-linear flights: segment versus cylinder, and closest approach.

All trajectories are piecewise linear in time, so every check has a closed form: no sampling.
"""
from __future__ import annotations

import math
from typing import Iterator, Optional, Sequence, Tuple

EPS = 1e-6
INF = float("inf")

Point = Tuple[float, float, float]
# A piece of a trajectory: (t0, t1, p0, p1), moving linearly from p0 at t0 to p1 at t1.
Piece = Tuple[float, float, Point, Point]


def dist3(a: Sequence[float], b: Sequence[float]) -> float:
    """Returns the 3D distance between two points."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def hdist(a: Sequence[float], b: Sequence[float]) -> float:
    """Returns the horizontal distance between two points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_enters_cylinder(p0: Point, p1: Point, center: Sequence[float],
                            radius: float, top: float = INF) -> bool:
    """Tells whether a straight segment enters the interior of a vertical cylinder.

    The cylinder is every point whose horizontal distance to `center` is below `radius`
    and whose altitude is below `top`. Touching the boundary (a tangent leg, flying exactly
    at `top`) is not entering.

    Args:
        p0: Start of the segment.
        p1: End of the segment.
        center: Horizontal centre (x, y).
        radius: Cylinder radius in metres.
        top: Ceiling of the cylinder; infinity for a full-height cylinder.

    Returns:
        True if some part of the segment of positive length lies inside the cylinder.
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    fx, fy = p0[0] - center[0], p0[1] - center[1]
    a = dx * dx + dy * dy
    c = fx * fx + fy * fy - radius * radius
    if a < 1e-12:
        return c < -EPS and min(p0[2], p1[2]) < top - EPS
    b = 2.0 * (fx * dx + fy * dy)
    disc = b * b - 4.0 * a * c
    if disc <= 0.0:
        return False
    root = math.sqrt(disc)
    lo = max((-b - root) / (2.0 * a), 0.0)
    hi = min((-b + root) / (2.0 * a), 1.0)
    if hi - lo <= 1e-9:
        return False
    z_lo = p0[2] + lo * (p1[2] - p0[2])
    z_hi = p0[2] + hi * (p1[2] - p0[2])
    return min(z_lo, z_hi) < top - EPS


def position_at(piece: Piece, t: float) -> Point:
    """Returns the position on a piece at time t."""
    t0, t1, p0, p1 = piece
    if t1 - t0 <= 1e-12:
        return p0
    f = (t - t0) / (t1 - t0)
    return (p0[0] + f * (p1[0] - p0[0]), p0[1] + f * (p1[1] - p0[1]), p0[2] + f * (p1[2] - p0[2]))


def overlapping_pieces(pieces_a: Sequence[Piece],
                       pieces_b: Sequence[Piece]) -> Iterator[Tuple[Piece, Piece, float, float]]:
    """Yields every pair of pieces that overlap in time, with the overlap interval."""
    i = j = 0
    while i < len(pieces_a) and j < len(pieces_b):
        a, b = pieces_a[i], pieces_b[j]
        lo, hi = max(a[0], b[0]), min(a[1], b[1])
        if hi - lo > 1e-12:
            yield a, b, lo, hi
        if a[1] < b[1]:
            i += 1
        else:
            j += 1


def _below_zero_interval(a: float, b: float, c: float, length: float,
                         closed: bool = False) -> Optional[Tuple[float, float]]:
    """Returns the part of [0, length] where a t^2 + b t + c is below zero (or at most zero)."""
    if a < 1e-12:
        inside = c <= 0.0 if closed else c < 0.0
        return (0.0, length) if inside else None
    disc = b * b - 4.0 * a * c
    if disc < 0.0 or (disc == 0.0 and not closed):
        return None
    root = math.sqrt(disc)
    lo = max((-b - root) / (2.0 * a), 0.0)
    hi = min((-b + root) / (2.0 * a), length)
    if hi - lo < (0.0 if closed else 1e-9):
        return None
    return (lo, hi)


def _relative_motion(a: Piece, b: Piece, lo: float):
    """Returns the relative position at `lo` and the relative velocity of b with respect to a."""
    pa, pb = position_at(a, lo), position_at(b, lo)
    va = _velocity(a)
    vb = _velocity(b)
    r0 = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
    w = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
    return r0, w


def _velocity(piece: Piece) -> Point:
    t0, t1, p0, p1 = piece
    if t1 - t0 <= 1e-12:
        return (0.0, 0.0, 0.0)
    k = 1.0 / (t1 - t0)
    return ((p1[0] - p0[0]) * k, (p1[1] - p0[1]) * k, (p1[2] - p0[2]) * k)


def close_intervals(a: Piece, b: Piece, lo: float, hi: float,
                    d_min: float) -> Optional[Tuple[float, float]]:
    """Returns the sub-interval (absolute times) where two pieces are closer than `d_min`."""
    r0, w = _relative_motion(a, b, lo)
    qa = w[0] ** 2 + w[1] ** 2 + w[2] ** 2
    qb = 2.0 * (r0[0] * w[0] + r0[1] * w[1] + r0[2] * w[2])
    qc = r0[0] ** 2 + r0[1] ** 2 + r0[2] ** 2 - d_min * d_min
    found = _below_zero_interval(qa, qb, qc, hi - lo)
    if found is None:
        return None
    return (lo + found[0], lo + found[1])


def min_distance(a: Piece, b: Piece, lo: float, hi: float) -> float:
    """Returns the minimum 3D distance between two linear pieces over [lo, hi]."""
    r0, w = _relative_motion(a, b, lo)
    qa = w[0] ** 2 + w[1] ** 2 + w[2] ** 2
    qb = 2.0 * (r0[0] * w[0] + r0[1] * w[1] + r0[2] * w[2])
    length = hi - lo
    if qa < 1e-12:
        t = 0.0
    else:
        t = min(max(-qb / (2.0 * qa), 0.0), length)
    return math.sqrt(sum((r0[i] + t * w[i]) ** 2 for i in range(3)))


def within_radius_interval(piece: Piece, lo: float, hi: float, center: Sequence[float],
                           radius: float) -> Optional[Tuple[float, float]]:
    """Returns the sub-interval (absolute times) where a piece is within `radius` of a point."""
    p = position_at(piece, lo)
    v = _velocity(piece)
    f = (p[0] - center[0], p[1] - center[1], p[2] - center[2])
    qa = v[0] ** 2 + v[1] ** 2 + v[2] ** 2
    qb = 2.0 * (f[0] * v[0] + f[1] * v[1] + f[2] * v[2])
    qc = f[0] ** 2 + f[1] ** 2 + f[2] ** 2 - radius * radius
    found = _below_zero_interval(qa, qb, qc, hi - lo, closed=True)
    if found is None:
        return None
    return (lo + found[0], lo + found[1])
