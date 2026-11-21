"""Independent cross-check: the exact closed-form geometry against brute-force sampling."""
import math
import random

from fleetkit import geometry as g


def _sample(piece, t):
    return g.position_at(piece, t)


def test_exact_min_distance_matches_dense_sampling():
    rng = random.Random(7)
    for _ in range(300):
        t1 = rng.uniform(5, 40)
        a = (0.0, t1, tuple(rng.uniform(-300, 300) for _ in range(3)), tuple(rng.uniform(-300, 300) for _ in range(3)))
        b = (0.0, t1, tuple(rng.uniform(-300, 300) for _ in range(3)), tuple(rng.uniform(-300, 300) for _ in range(3)))
        exact = g.min_distance(a, b, 0.0, t1)
        sampled = min(g.dist3(_sample(a, t1 * i / 4000), _sample(b, t1 * i / 4000)) for i in range(4001))
        assert exact <= sampled + 1e-9
        assert sampled - exact < 0.5, (exact, sampled)


def test_close_interval_matches_sampling():
    rng = random.Random(11)
    for _ in range(200):
        t1 = rng.uniform(5, 40)
        a = (0.0, t1, tuple(rng.uniform(-200, 200) for _ in range(3)), tuple(rng.uniform(-200, 200) for _ in range(3)))
        b = (0.0, t1, tuple(rng.uniform(-200, 200) for _ in range(3)), tuple(rng.uniform(-200, 200) for _ in range(3)))
        d = rng.uniform(20, 80)
        found = g.close_intervals(a, b, 0.0, t1, d)
        inside = [i * t1 / 2000 for i in range(2001)
                  if g.dist3(_sample(a, i * t1 / 2000), _sample(b, i * t1 / 2000)) < d]
        if found is None:
            assert len(inside) <= 3
        else:
            lo, hi = found
            assert not inside or (min(inside) >= lo - 0.05 and max(inside) <= hi + 0.05)
            if hi - lo > 0.1:
                assert inside


def test_segment_cylinder_matches_sampling():
    rng = random.Random(3)
    for _ in range(400):
        p0 = (rng.uniform(-500, 500), rng.uniform(-500, 500), rng.uniform(0, 150))
        p1 = (rng.uniform(-500, 500), rng.uniform(-500, 500), rng.uniform(0, 150))
        center = (rng.uniform(-300, 300), rng.uniform(-300, 300))
        radius, top = rng.uniform(80, 250), rng.uniform(30, 140)
        exact = g.segment_enters_cylinder(p0, p1, center, radius, top)
        hit = False
        min_margin = 1e9
        for i in range(4001):
            s = i / 4000
            p = tuple(p0[k] + s * (p1[k] - p0[k]) for k in range(3))
            inside_xy = math.hypot(p[0] - center[0], p[1] - center[1]) < radius
            if inside_xy and p[2] < top:
                hit = True
            min_margin = min(min_margin, abs(math.hypot(p[0] - center[0], p[1] - center[1]) - radius), abs(p[2] - top))
        if min_margin > 1.0 or hit:
            assert exact == hit or min_margin <= 1.0, (p0, p1, center, radius, top)
