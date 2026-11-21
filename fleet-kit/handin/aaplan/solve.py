"""Top level: search scout tours, build exact routes, place effector strikes, validate, repair."""
from __future__ import annotations

import math
import random
import statistics
import time
from typing import Dict, List, Optional

from fleetkit.scorer import evaluate

from fleetkit.energy import route_energy_wh

from .build import Cyl, ScoutBuilder, Sep, effector_energy_estimate, effector_route, to_wps
from .geo import World
from .tours import LNS, Problem

SCOUT_LEVELS = [35.0, 76.0, 121.0]
EFF_LEVELS = [35.0, 75.0, 115.0, 150.0]


def eff_stats(sc) -> dict:
    out = {}
    for sub in ("light", "heavy"):
        effs = [a for a in sc.aircraft if a.type == "effector" and a.subtype == sub]
        if not effs:
            out[sub] = {"jpm": 6.0, "climb": 1.0, "t_climb": 10.0, "v": 25.0}
            continue
        jpm = [(a.power.p0_w + a.power.k_v * (0.96 * a.v_h_mps) ** 2) / (0.96 * a.v_h_mps) for a in effs]
        out[sub] = {
            "jpm": statistics.median(jpm),
            "climb": statistics.median(a.power.e_climb_wh_per_m * 60.0 for a in effs),
            "t_climb": statistics.median(60.0 / (0.96 * a.v_up_mps) for a in effs) + 8.0,
            "v": sorted(0.96 * a.v_h_mps for a in effs)[len(effs) // 3],
        }
    return out


class Planner:
    def __init__(self, sc, log=None):
        self.sc = sc
        self.log = log or (lambda *a: None)
        self.world = World(sc)
        self.cyl = Cyl(sc)
        self.contacts = sc.contact_by_id()
        self.aircraft = sc.aircraft_by_id()
        self.stats = eff_stats(sc)

    def latest(self) -> Dict[str, float]:
        r = self.sc.rules
        out = {}
        for c in self.sc.contacts:
            if c.window is None:
                continue
            lo, hi = c.window
            if c.cls == "hostile":
                out[c.id] = hi - r.obs_dwell_s - r.confirm_margin_s - 3.0
            else:
                out[c.id] = hi - r.obs_dwell_s - 0.1
        return out

    # -------------------------------------------------------------------------- search
    def search(self, deadline: float, seed: int, skip=None, alpha=0.5, levels=None):
        prob = Problem(self.sc, self.world, levels or SCOUT_LEVELS, self.stats, alpha=alpha, skip=skip)
        rng = random.Random(seed)
        lns = LNS(prob, rng)
        z0 = [prob.levels[k % 2] if len(prob.levels) > 1 else prob.levels[0] for k in range(len(prob.scouts))]
        sol = lns.run(deadline, z0)
        self.log(f"  LNS it={lns.iterations} obj={sol.obj:.1f} served={len(sol.served)} light={sol.nl} heavy={sol.nh}")
        tours = []
        for si, t in enumerate(sol.tours):
            tours.append((prob.scouts[si].id, sol.z[si], [prob.C[ci].id for ci in t], sol.objs[si]))
        return tours

    # -------------------------------------------------------------------------- build
    def build(self, tours, deadline: float):
        sc = self.sc
        sb = ScoutBuilder(sc, self.world, self.cyl)
        sep = Sep(sc)
        latest = self.latest()
        routes: Dict[str, List[dict]] = {}
        obs_end: Dict[str, float] = {}
        obs_by: Dict[str, str] = {}
        for sid, z, seq, _ in sorted(tours, key=lambda x: -x[3]):
            if not seq:
                continue
            a = self.aircraft[sid]
            got = self._place_scout(sb, sep, a, z, list(seq), latest)
            if got is None:
                continue
            r2, oe2 = got
            routes[sid] = r2
            for cid, te in oe2.items():
                if cid not in obs_end or te < obs_end[cid]:
                    obs_end[cid] = te
                    obs_by[cid] = sid
        self.log(f"  scouts placed: {len(routes)}  observed: {len(obs_end)}")
        # effectors
        r = sc.rules
        free = {sub: [a for a in sc.aircraft if a.type == "effector" and a.subtype == sub] for sub in ("light", "heavy")}
        hostiles = [self.contacts[cid] for cid in obs_end if self.contacts[cid].cls == "hostile"]
        H0 = (sum(a.home[0] for a in sc.aircraft) / len(sc.aircraft), sum(a.home[1] for a in sc.aircraft) / len(sc.aircraft))

        def est_value(c):
            d = math.hypot(c.pos[0] - H0[0], c.pos[1] - H0[1])
            cost = 0.0
            for sub, n in c.needs.items():
                st = self.stats[sub]
                cost += n * (r.c_eff + r.lambda_e * st["jpm"] * d / 3600.0)
            return c.points - cost

        hostiles.sort(key=lambda c: -est_value(c))
        groups: Dict[str, List[str]] = {}
        for c in hostiles:
            if time.monotonic() > deadline:
                break
            if est_value(c) <= 0:
                continue
            ok = self._place_group(c, obs_end[c.id], free, sep, routes, groups)
        self.log(f"  strikes placed: {len(groups)} / {len(hostiles)}")
        return routes, groups, obs_by

    def _place_scout(self, sb, sep, a, z0, seq, latest):
        levels = [z0] + [l for l in SCOUT_LEVELS if l != z0]
        lam = self.sc.rules.lambda_e
        while seq:
            best = None
            for z in levels:
                out = sb.plan(a, z, seq, latest)
                if out is None:
                    continue
                route, oe, info, kept, pts = out
                tries = [info["t0"]]
                for k in range(1, 15):
                    tries.append(info["t0"] - 2.5 * k)
                    tries.append(info["t0"] + 2.5 * k)
                for t0 in tries:
                    if t0 < 0:
                        continue
                    if t0 != info["t0"]:
                        o2 = sb.build(a, z, kept, pts, t0, latest)
                        if o2[0] is None or o2[2]["energy"] > a.usable_wh - 0.05:
                            continue
                        r2, oe2, inf2 = o2
                    else:
                        r2, oe2, inf2 = route, oe, info
                    if not self.cyl.route_ok(r2):
                        continue
                    made = sep.make(a.id, r2)
                    if sep.first_conflict(made) is None:
                        val = sum(self.contacts[c].points for c in oe2) - lam * inf2["energy"]
                        if best is None or val > best[0]:
                            best = (val, r2, oe2, made)
                        break
                if best is not None and len(best[2]) == len(seq):
                    break
            if best is not None:
                sep.add(a.id, best[3])
                return best[1], best[2]
            seq.pop()
        return None

    def _place_group(self, c, t_obs, free, sep, routes, groups) -> bool:
        sc = self.sc
        r = sc.rules
        lo, hi = c.window
        t_lo = max(t_obs + r.confirm_margin_s + 0.3, lo + 0.05)
        t_hi = hi - 0.05
        if t_lo > t_hi:
            return False
        d = math.hypot(c.pos[0] - 150.0, c.pos[1] - 150.0)
        members = []
        for sub in ("heavy", "light"):
            n = c.needs.get(sub, 0)
            if n == 0:
                continue
            pool = sorted(free[sub], key=lambda a: effector_energy_estimate(a, d) + a.power.e_climb_wh_per_m * 60)
            pool = [a for a in pool if 60.0 / a.v_up_mps + d * 1.05 / (0.96 * a.v_h_mps) + 15.0 < t_hi]
            if len(pool) < n:
                return False
            members.extend(pool[:n])
        if not members:
            return False
        home_b = math.atan2(150.0 - c.pos[1], 150.0 - c.pos[0])
        offs = [0.0, 0.6, -0.6, 1.2, -1.2, 0.3, -0.3, 0.9, -0.9]
        firsts = []
        t = t_lo
        steps = [0, 2, 5, 9, 14, 20, 28, 38, 50, 65, 85, 110, 140, 180, 230]
        for s in steps:
            if t_lo + s <= t_hi:
                firsts.append(t_lo + s)
        budget = 900
        for t_first in firsts:
            placed = []
            okall = True
            for i, a in enumerate(members):
                done = False
                for dt in (0.0, 3.0, 6.0, 10.0, 14.0, 18.0):
                    te = t_first + dt
                    if te > t_hi:
                        break
                    opts = []
                    for z in EFF_LEVELS:
                        for oi in range(len(offs)):
                            off = offs[(i + oi) % len(offs)]
                            budget -= 1
                            if budget < 0:
                                break
                            route = effector_route(a, c, te, z, home_b + off, self.world, self.cyl)
                            if route is None or not self.cyl.route_ok(route):
                                continue
                            made = sep.make(a.id, route)
                            if sep.first_conflict(made) is not None:
                                continue
                            opts.append((route_energy_wh(to_wps(route), a), route, made))
                            break
                        if budget < 0:
                            break
                    if opts:
                        opts.sort(key=lambda o: o[0])
                        _, route, made = opts[0]
                        sep.add(a.id, made)
                        placed.append((a, route))
                        done = True
                        break
                    if budget < 0:
                        break
                if not done:
                    okall = False
                    break
            if okall:
                for a, route in placed:
                    routes[a.id] = route
                    free[a.subtype].remove(a)
                groups[c.id] = [a.id for a, _ in placed]
                return True
            for a, _ in placed:
                sep.remove(a.id)
            if budget < 0:
                return False
        return False

    # -------------------------------------------------------------------------- assemble
    def assemble(self, routes) -> dict:
        return {"seed": self.sc.seed, "routes": [{"aircraft": a, "waypoints": w} for a, w in routes.items()]}

    def repair(self, routes, groups, obs_by):
        """Validates; removes offending routes (and strikes that depend on them) until valid."""
        sc = self.sc
        for _ in range(60):
            plan = self.assemble(routes)
            res = evaluate(sc, plan)
            if res.valid:
                return plan, res
            bad = set()
            for v in res.violations:
                self.log(f"   violation: {v}")
                if v.aircraft:
                    bad.add(v.aircraft)
                if v.contact and v.contact in groups:
                    bad.update(groups[v.contact])
                if v.rule == "R8":
                    import re
                    ids = re.findall(r"^(\S+) and (\S+) come", v.message)
                    if ids:
                        a1, a2 = ids[0]
                        bad.add(a2 if self.aircraft[a2].type == "effector" else a1)
            if not bad:
                return None, res
            for aid in list(bad):
                if aid not in routes:
                    continue
                if self.aircraft[aid].type == "scout":
                    for cid, s in obs_by.items():
                        if s == aid and cid in groups:
                            for e in groups.pop(cid):
                                routes.pop(e, None)
                    routes.pop(aid, None)
                else:
                    for cid, mem in list(groups.items()):
                        if aid in mem:
                            for e in mem:
                                routes.pop(e, None)
                            groups.pop(cid)
                    routes.pop(aid, None)
        return None, None

    def prune(self, routes, groups, obs_by):
        """Drops scout tours that serve nothing (pure cost)."""
        served_by = {}
        for cid, s in obs_by.items():
            c = self.contacts[cid]
            if c.cls == "unknown" or cid in groups:
                served_by.setdefault(s, []).append(cid)
        for aid in list(routes):
            if self.aircraft[aid].type == "scout" and aid not in served_by:
                routes.pop(aid)


def plan_scenario(sc, budget_s: float = 36.0, log=None, seed: int = 0):
    t0 = time.monotonic()
    P = Planner(sc, log)
    n = len(sc.aircraft)
    best = None
    best_res = None
    alphas = [0.5, 0.3, 0.7, 0.4, 0.6, 0.5]
    attempts = 4
    per = max(1.0, min((budget_s - 3.0) / attempts, 1.0 + 0.09 * n))
    for attempt in range(attempts + 2):
        if time.monotonic() - t0 + per + 1.0 > budget_s:
            break
        if attempt >= attempts and best_res is not None:
            break
        tours = P.search(time.monotonic() + per, seed + attempt, alpha=alphas[attempt % len(alphas)])
        routes, groups, obs_by = P.build(tours, t0 + budget_s - 0.5)
        P.prune(routes, groups, obs_by)
        plan, res = P.repair(routes, groups, obs_by)
        if plan is not None and (best_res is None or res.score > best_res.score):
            best, best_res = plan, res
        if log:
            log(f" attempt {attempt}: {res.score if res else None}  t={time.monotonic() - t0:.1f}s")
    return best, best_res
