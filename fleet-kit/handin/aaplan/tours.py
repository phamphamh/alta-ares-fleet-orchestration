"""Scout tour optimisation: a team orienteering problem with time windows, solved by
greedy insertion + large neighbourhood search (ruin & recreate, simulated annealing).

The model is approximate (centre-to-centre path lengths minus observation reach) but
conservative; the exact routes are rebuilt and checked afterwards.
"""
from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Tuple

from .geo import World

J = 3600.0


class Cand:
    __slots__ = ("idx", "id", "cls", "x", "y", "lo", "hi", "latest", "value", "needs", "points")


class ScoutP:
    __slots__ = ("idx", "id", "v", "vup", "vdn", "p0", "kv", "ec", "usable", "home")


class Problem:
    def __init__(self, scenario, world: World, levels: List[float], eff_stats: dict, alpha: float = 0.5,
                 skip: Optional[set] = None, energy_margin: float = 0.95):
        sc = scenario
        self.sc = sc
        self.world = world
        r = sc.rules
        self.rules = r
        self.levels = levels
        self.alpha = alpha
        self.energy_margin = energy_margin
        self.lam = r.lambda_e
        self.dwell = r.obs_dwell_s
        self.horizon = sc.horizon_s
        scouts = [a for a in sc.aircraft if a.type == "scout"]
        bx = sum(a.home[0] for a in scouts) / max(1, len(scouts))
        by = sum(a.home[1] for a in scouts) / max(1, len(scouts))
        self.base = (bx, by)
        self.scouts: List[ScoutP] = []
        for k, a in enumerate(scouts):
            s = ScoutP()
            s.idx, s.id = k, a.id
            s.v = 0.96 * a.v_h_mps
            s.vup, s.vdn = 0.96 * a.v_up_mps, 0.96 * a.v_down_mps
            s.p0, s.kv, s.ec = a.power.p0_w, a.power.k_v, a.power.e_climb_wh_per_m
            s.usable = a.usable_wh
            s.home = a.home
            self.scouts.append(s)
        self.reach = {z: math.sqrt(max(0.0, (r.R_obs_m - 2.0) ** 2 - z * z)) - 1.0 for z in levels}
        friends = [c for c in sc.contacts if c.cls in ("friendly", "civilian")]
        self.cands: List[Cand] = []
        self.n_light = sum(1 for a in sc.aircraft if a.type == "effector" and a.subtype == "light")
        self.n_heavy = sum(1 for a in sc.aircraft if a.type == "effector" and a.subtype == "heavy")
        skip = skip or set()
        for c in sc.contacts:
            if c.cls not in ("hostile", "unknown") or c.window is None or c.id in skip:
                continue
            lo, hi = c.window
            k = Cand()
            k.id, k.cls, k.x, k.y = c.id, c.cls, c.pos[0], c.pos[1]
            k.lo, k.hi, k.points = lo + 0.05, hi, c.points
            k.needs = (0, 0)
            if c.cls == "hostile":
                if any(math.hypot(c.pos[0] - f.pos[0], c.pos[1] - f.pos[1]) < r.collateral_radius_m + 1e-3 for f in friends):
                    continue
                nl, nh = c.needs.get("light", 0), c.needs.get("heavy", 0)
                if nl > self.n_light or nh > self.n_heavy or nl + nh == 0:
                    continue
                if set(c.needs) - {"light", "heavy"}:
                    continue
                d = math.hypot(c.pos[0] - bx, c.pos[1] - by)
                cost = 0.0
                earliest = 0.0
                for sub, n in (("light", nl), ("heavy", nh)):
                    if n == 0:
                        continue
                    st = eff_stats[sub]
                    cost += n * (r.c_eff + self.lam * (st["jpm"] * d * 1.05 / J + st["climb"]))
                    earliest = max(earliest, st["t_climb"] + d * 1.05 / st["v"] + 12.0)
                k.value = c.points - cost
                k.needs = (nl, nh)
                k.latest = min(hi - self.dwell - r.confirm_margin_s - 3.0, hi - self.dwell - 3.0)
                if earliest > hi - 3.0:
                    continue
            else:
                k.value = c.points
                k.latest = hi - self.dwell - 0.1
            if k.value <= 0.5 or k.latest < k.lo:
                continue
            k.idx = len(self.cands) + 1
            self.cands.append(k)
        # distance matrices per level: node 0 = base, node i = cands[i-1]
        pts = [self.base] + [(k.x, k.y) for k in self.cands]
        n = len(pts)
        self.D: Dict[float, List[List[float]]] = {}
        for z in levels:
            M = [[0.0] * n for _ in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    res = world.path(pts[i], pts[j], z)
                    d = res[1] if res is not None else 1e9
                    M[i][j] = M[j][i] = d
            self.D[z] = M
        self.C = [None] + self.cands  # 1-based access

    # ------------------------------------------------------------------ evaluation
    def eval_tour(self, s: ScoutP, z: float, seq: List[int]) -> Optional[Tuple[float, float]]:
        """Returns (objective, energy Wh) of a tour or None if infeasible. Empty tour -> (0, 0)."""
        if not seq:
            return 0.0, 0.0
        D = self.D[z]
        C = self.C
        r = self.reach[z]
        ar = self.alpha * r
        v = s.v
        t = z / s.vup + 2.0
        prev = 0
        dist = 0.0
        cum = 0.0
        F = 1e18
        val = 0.0
        dwell = self.dwell
        for i in seq:
            d = D[prev][i] - (r if prev == 0 else ar)
            if d < 0.0:
                d = 0.0
            dist += d
            arr = t + d / v
            c = C[i]
            if arr > c.latest:
                return None
            if arr < c.lo:
                cum += c.lo - arr
                start = c.lo
            else:
                start = arr
            sl = cum + c.latest - start
            if sl < F:
                F = sl
            t = start + dwell
            val += c.value
            prev = i
        d = D[prev][0] + r
        dist += d
        land = t + d / v + z / s.vdn + 2.0
        if land > self.horizon - 3.0:
            return None
        delta = F if F < cum else cum
        air = land - delta
        e = (s.p0 * air + s.kv * v * dist) / J + s.ec * z
        if e > s.usable * self.energy_margin:
            return None
        return val - self.lam * e, e


class Sol:
    __slots__ = ("tours", "z", "obj", "objs", "nl", "nh", "served")

    def copy(self) -> "Sol":
        s = Sol()
        s.tours = [list(t) for t in self.tours]
        s.z = list(self.z)
        s.obj = self.obj
        s.objs = list(self.objs)
        s.nl, s.nh = self.nl, self.nh
        s.served = set(self.served)
        return s


class LNS:
    def __init__(self, prob: Problem, rng: random.Random):
        self.p = prob
        self.rng = rng

    def empty(self, z_init: List[float]) -> Sol:
        s = Sol()
        n = len(self.p.scouts)
        s.tours = [[] for _ in range(n)]
        s.z = list(z_init)
        s.obj = 0.0
        s.objs = [0.0] * n
        s.nl = s.nh = 0
        s.served = set()
        return s

    def _best_insert(self, sol: Sol, ci: int, si: int):
        p = self.p
        tour = sol.tours[si]
        s = p.scouts[si]
        z = sol.z[si]
        base = sol.objs[si]
        best = None
        for pos in range(len(tour) + 1):
            res = p.eval_tour(s, z, tour[:pos] + [ci] + tour[pos:])
            if res is None:
                continue
            d = res[0] - base
            if best is None or d > best[0]:
                best = (d, pos, res[0])
        return best

    def recreate(self, sol: Sol, noise: float = 0.0, mu=(0.0, 0.0)):
        p = self.p
        rng = self.rng
        muL, muH = mu
        n = len(p.scouts)
        unserved = [k.idx for k in p.cands if k.idx not in sol.served]
        cache: Dict[Tuple[int, int], Optional[tuple]] = {}
        for ci in unserved:
            for si in range(n):
                cache[(ci, si)] = self._best_insert(sol, ci, si)
        while True:
            best = None
            for (ci, si), b in cache.items():
                if b is None:
                    continue
                c = p.C[ci]
                if sol.nl + c.needs[0] > p.n_light or sol.nh + c.needs[1] > p.n_heavy:
                    continue
                score = b[0] - muL * c.needs[0] - muH * c.needs[1]
                if noise:
                    score *= 1.0 + noise * (rng.random() - 0.5)
                if b[0] > 1e-6 and (best is None or score > best[0]):
                    best = (score, ci, si, b)
            if best is None:
                break
            _, ci, si, b = best
            sol.tours[si].insert(b[1], ci)
            sol.obj += b[2] - sol.objs[si]
            sol.objs[si] = b[2]
            c = p.C[ci]
            sol.nl += c.needs[0]
            sol.nh += c.needs[1]
            sol.served.add(ci)
            for sj in range(n):
                cache.pop((ci, sj), None)
            for cj in unserved:
                if (cj, si) in cache:
                    cache[(cj, si)] = self._best_insert(sol, cj, si)
        return sol

    def _remove(self, sol: Sol, cis: List[int]):
        p = self.p
        touched = set()
        for ci in cis:
            for si, t in enumerate(sol.tours):
                if ci in t:
                    t.remove(ci)
                    touched.add(si)
                    break
            sol.served.discard(ci)
            c = p.C[ci]
            sol.nl -= c.needs[0]
            sol.nh -= c.needs[1]
        self._refresh(sol, touched)

    def _refresh(self, sol: Sol, touched):
        p = self.p
        for si in touched:
            # removing a node can make a tour infeasible only through the approximation; drop until ok
            while True:
                res = p.eval_tour(p.scouts[si], sol.z[si], sol.tours[si])
                if res is not None:
                    break
                ci = sol.tours[si].pop()
                sol.served.discard(ci)
                c = p.C[ci]
                sol.nl -= c.needs[0]
                sol.nh -= c.needs[1]
            sol.obj += res[0] - sol.objs[si]
            sol.objs[si] = res[0]

    def two_opt(self, sol: Sol):
        p = self.p
        for si, tour in enumerate(sol.tours):
            if len(tour) < 3:
                continue
            improved = True
            while improved:
                improved = False
                for i in range(len(tour) - 1):
                    for j in range(i + 1, len(tour)):
                        cand = tour[:i] + tour[i:j + 1][::-1] + tour[j + 1:]
                        res = p.eval_tour(p.scouts[si], sol.z[si], cand)
                        if res is not None and res[0] > sol.objs[si] + 1e-6:
                            tour[:] = cand
                            sol.obj += res[0] - sol.objs[si]
                            sol.objs[si] = res[0]
                            improved = True
                            break
                    if improved:
                        break

    def run(self, deadline: float, z_init: List[float]) -> Sol:
        p = self.p
        rng = self.rng
        cur = self.recreate(self.empty(z_init))
        self.two_opt(cur)
        best = cur.copy()
        T0 = max(1.0, 0.02 * max(1.0, cur.obj))
        it = 0
        t_start = time.monotonic()
        span = max(1e-3, deadline - t_start)
        while time.monotonic() < deadline:
            it += 1
            frac = (time.monotonic() - t_start) / span
            T = T0 * (1.0 - frac) + 1e-3
            sol = cur.copy()
            served = list(sol.served)
            mode = rng.random()
            if mode < 0.12 and p.levels and len(p.levels) > 1:
                si = rng.randrange(len(p.scouts))
                rem = list(sol.tours[si])
                sol.z[si] = rng.choice([z for z in p.levels if z != sol.z[si]])
                self._remove(sol, rem)
                self._refresh(sol, [si])
            elif mode < 0.25 and served:
                si = rng.randrange(len(p.scouts))
                self._remove(sol, list(sol.tours[si]))
            elif mode < 0.65 and served:
                seed = p.C[rng.choice(served)]
                k = rng.randint(2, min(10, max(2, len(served))))
                near = sorted(served, key=lambda ci: (p.C[ci].x - seed.x) ** 2 + (p.C[ci].y - seed.y) ** 2)[:k]
                self._remove(sol, near)
            elif served:
                k = rng.randint(1, min(6, len(served)))
                self._remove(sol, rng.sample(served, k))
            mu = (rng.uniform(0.0, 25.0) if rng.random() < 0.4 else 0.0,
                  rng.uniform(0.0, 25.0) if rng.random() < 0.4 else 0.0)
            self.recreate(sol, noise=0.3 if rng.random() < 0.5 else 0.0, mu=mu)
            if it % 10 == 0:
                self.two_opt(sol)
            if sol.obj > cur.obj - 1e-9 or rng.random() < math.exp((sol.obj - cur.obj) / T):
                cur = sol
                if cur.obj > best.obj + 1e-9:
                    best = cur.copy()
        self.iterations = it
        self.two_opt(best)
        return best
