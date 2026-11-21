"""2D obstacle-aware shortest paths at a fixed altitude (visibility graph around discs)."""
from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Sequence, Tuple

INF = float("inf")
P2 = Tuple[float, float]

MARGIN = 9.0        # inflation used to build detour polygons
CHECK = 6.0         # clearance demanded from every leg (must stay < MARGIN)
NPOLY = 12


def seg_hits(ax: float, ay: float, bx: float, by: float, cx: float, cy: float, R: float) -> bool:
    """True if segment a-b comes strictly closer than R to (cx, cy)."""
    dx, dy = bx - ax, by - ay
    fx, fy = ax - cx, ay - cy
    a = dx * dx + dy * dy
    if a < 1e-12:
        return fx * fx + fy * fy < R * R
    t = -(fx * dx + fy * dy) / a
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    px, py = fx + t * dx, fy + t * dy
    return px * px + py * py < R * R


class World:
    """Static obstacles: zones (cylinders with a ceiling) and protected discs (infinite)."""

    def __init__(self, scenario):
        rules = scenario.rules
        self.obs: List[Tuple[float, float, float, float]] = []
        for z in scenario.zones:
            self.obs.append((z.center[0], z.center[1], z.radius_m, z.top_m))
        for c in scenario.contacts:
            if c.cls in ("friendly", "civilian"):
                self.obs.append((c.pos[0], c.pos[1], rules.protect_radius_m, INF))
        self._active: Dict[float, list] = {}
        self._verts: Dict[float, list] = {}
        self._cache: Dict[tuple, Optional[Tuple[List[P2], float]]] = {}

    def active(self, z: float):
        """Obstacles that forbid flying at altitude z (with 1 m of headroom over ceilings)."""
        got = self._active.get(z)
        if got is None:
            got = [o for o in self.obs if o[3] > z - 1.0]
            self._active[z] = got
        return got

    def point_free(self, x: float, y: float, z: float, extra: float = 0.0) -> bool:
        for cx, cy, r, _ in self.active(z):
            R = r + CHECK + extra
            if (x - cx) ** 2 + (y - cy) ** 2 < R * R:
                return False
        return True

    def seg_free(self, a: Sequence[float], b: Sequence[float], z: float, obs=None) -> bool:
        for cx, cy, r, _ in (obs if obs is not None else self.active(z)):
            if seg_hits(a[0], a[1], b[0], b[1], cx, cy, r + CHECK):
                return False
        return True

    def _hits(self, a, b, obs):
        return [o for o in obs if seg_hits(a[0], a[1], b[0], b[1], o[0], o[1], o[2] + CHECK)]

    def _poly(self, o, act):
        cx, cy, r, _ = o
        R = (r + MARGIN) / math.cos(math.pi / NPOLY)
        out = []
        for k in range(NPOLY):
            ang = 2.0 * math.pi * (k + 0.5) / NPOLY
            x, y = cx + R * math.cos(ang), cy + R * math.sin(ang)
            ok = True
            for o2 in act:
                if o2 is o:
                    continue
                RR = o2[2] + CHECK + 0.5
                if (x - o2[0]) ** 2 + (y - o2[1]) ** 2 < RR * RR:
                    ok = False
                    break
            if ok:
                out.append((x, y))
        return out

    def path(self, p: P2, q: P2, z: float) -> Optional[Tuple[List[P2], float]]:
        """Shortest polyline p -> q avoiding obstacles active at z; (points, length) or None."""
        key = (round(p[0], 1), round(p[1], 1), round(q[0], 1), round(q[1], 1), z)
        if key in self._cache:
            return self._cache[key]
        res = self._path(p, q, z)
        if len(self._cache) > 200000:
            self._cache.clear()
        self._cache[key] = res
        return res

    def _path(self, p, q, z):
        act = self.active(z)
        hits = self._hits(p, q, act)
        if not hits:
            return [p, q], math.hypot(q[0] - p[0], q[1] - p[1])
        S = list(hits)
        for _ in range(8):
            nodes = [p, q]
            for o in S:
                nodes.extend(self._poly(o, act))
            n = len(nodes)
            dist = [INF] * n
            prev = [-1] * n
            dist[0] = 0.0
            heap = [(math.hypot(q[0] - p[0], q[1] - p[1]), 0.0, 0)]
            done = [False] * n
            edge_cache = {}
            while heap:
                f, d, i = heapq.heappop(heap)
                if done[i]:
                    continue
                done[i] = True
                if i == 1:
                    break
                a = nodes[i]
                for j in range(1, n):
                    if done[j] or j == i:
                        continue
                    b = nodes[j]
                    k = (i, j) if i < j else (j, i)
                    ok = edge_cache.get(k)
                    if ok is None:
                        ok = True
                        for o in S:
                            if seg_hits(a[0], a[1], b[0], b[1], o[0], o[1], o[2] + CHECK):
                                ok = False
                                break
                        edge_cache[k] = ok
                    if not ok:
                        continue
                    nd = d + math.hypot(b[0] - a[0], b[1] - a[1])
                    if nd < dist[j] - 1e-9:
                        dist[j] = nd
                        prev[j] = i
                        heapq.heappush(heap, (nd + math.hypot(q[0] - b[0], q[1] - b[1]), nd, j))
            if dist[1] == INF:
                return None
            pts = []
            i = 1
            while i != -1:
                pts.append(nodes[i])
                i = prev[i]
            pts.reverse()
            new = []
            for k in range(len(pts) - 1):
                for o in self._hits(pts[k], pts[k + 1], act):
                    if o not in S and o not in new:
                        new.append(o)
            if not new:
                return pts, dist[1]
            S.extend(new)
        return None


def plen(pts: Sequence[Sequence[float]]) -> float:
    return sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(len(pts) - 1))
