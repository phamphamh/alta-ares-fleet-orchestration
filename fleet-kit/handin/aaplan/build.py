"""Exact route construction (scouts and effectors) and separation deconfliction."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from fleetkit.energy import route_energy_wh
from fleetkit.geometry import INF, segment_enters_cylinder
from fleetkit.model import Route, Waypoint
from fleetkit.validator import separation_item, separation_violation

from .geo import World, plen


def wp(t, x, y, z, **kw):
    d = {"t": float(t), "x": float(x), "y": float(y), "z": float(z)}
    d.update(kw)
    return d


def to_wps(route: List[dict]) -> List[Waypoint]:
    return [Waypoint(w["t"], w["x"], w["y"], w["z"], w.get("action"), w.get("target"), w.get("dwell_s", 0.0))
            for w in route]


class Cyl:
    """3D exclusion check of whole routes, exactly as rule R6."""

    def __init__(self, sc):
        self.cyl = [(z.center, z.radius_m, z.top_m) for z in sc.zones]
        for c in sc.contacts:
            if c.cls in ("friendly", "civilian"):
                self.cyl.append((c.pos[:2], sc.rules.protect_radius_m, INF))

    def leg_ok(self, a, b) -> bool:
        for center, radius, top in self.cyl:
            if segment_enters_cylinder(a, b, center, radius + 2.0, top + 0.5 if top < INF else top):
                return False
        return True

    def route_ok(self, route: List[dict]) -> bool:
        for k in range(len(route) - 1):
            a, b = route[k], route[k + 1]
            if not self.leg_ok((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"])):
                return False
        return True


class Sep:
    """Incremental pairwise separation check (rule R8) with cheap time/box prefilters."""

    def __init__(self, sc):
        self.sc = sc
        self.rules = sc.rules
        self.contacts = sc.contact_by_id()
        self.aircraft = sc.aircraft_by_id()
        self.items: Dict[str, tuple] = {}

    def make(self, aid: str, route: List[dict]):
        r = Route(aid, to_wps(route))
        item = separation_item(aid, r, self.aircraft[aid])
        if item is None:
            return None
        d = self.rules.d_sep_m + 1.0
        xs = [w["x"] for w in route]
        ys = [w["y"] for w in route]
        zs = [w["z"] for w in route]
        box = (min(xs) - d, max(xs) + d, min(ys) - d, max(ys) + d, min(zs) - d, max(zs) + d)
        return (item, box)

    def first_conflict(self, made, ignore=()) -> Optional[str]:
        if made is None:
            return None
        item, box = made
        _, _, s, e, _ = item
        for aid, (it2, b2) in self.items.items():
            if aid in ignore:
                continue
            if it2[3] <= s or it2[2] >= e:
                continue
            if b2[1] < box[0] or b2[0] > box[1] or b2[3] < box[2] or b2[2] > box[3] or b2[5] < box[4] or b2[4] > box[5]:
                continue
            if separation_violation(self.rules, self.contacts, item, it2) is not None:
                return aid
        return None

    def add(self, aid, made):
        if made is not None:
            self.items[aid] = made

    def remove(self, aid):
        self.items.pop(aid, None)


# ---------------------------------------------------------------------------------------- scouts

class ScoutBuilder:
    def __init__(self, sc, world: World, cyl: Cyl):
        self.sc = sc
        self.world = world
        self.cyl = cyl
        self.rules = sc.rules
        self.contacts = sc.contact_by_id()

    def _obs_point(self, P, c, nxt, z, reach):
        cx, cy = c.pos[0], c.pos[1]
        w = self.world
        cands = []
        dpc = math.hypot(P[0] - cx, P[1] - cy)
        if dpc <= reach and w.point_free(P[0], P[1], z, 1.0):
            cands.append(P)
        dirs = []
        if dpc > 1e-6:
            dirs.append(math.atan2(P[1] - cy, P[0] - cx))
        if nxt is not None:
            dirs.append(math.atan2(nxt[1] - cy, nxt[0] - cx))
        dirs.extend(2 * math.pi * k / 24 for k in range(24))
        for ang in dirs:
            for rr in (reach, 0.75 * reach, 0.5 * reach):
                q = (cx + rr * math.cos(ang), cy + rr * math.sin(ang))
                if w.point_free(q[0], q[1], z, 1.0):
                    cands.append(q)
                    break
        if not cands:
            return None
        best, bv = None, INF
        for q in cands:
            v = math.hypot(q[0] - P[0], q[1] - P[1])
            if nxt is not None:
                v += math.hypot(nxt[0] - q[0], nxt[1] - q[1])
            if v < bv - 1e-9:
                best, bv = q, v
        return best

    def geometry(self, a, z: float, seq: List[str]):
        """Observation points and polylines (2D) for a scout tour; None if no path."""
        r = self.rules
        reach = math.sqrt(max(0.0, (r.R_obs_m - 1.5) ** 2 - z * z)) - 1.0
        home = a.home
        H = (home[0], home[1])
        cont = self.contacts
        pts = []
        P = H
        for k, cid in enumerate(seq):
            c = cont[cid]
            nxt = cont[seq[k + 1]].pos[:2] if k + 1 < len(seq) else H
            q = self._obs_point(P, c, nxt, z, reach)
            if q is None:
                return None
            pts.append(q)
            P = q
        return pts

    def build(self, a, z: float, seq: List[str], obs_pts, t0: float, latest: Dict[str, float]):
        """Builds the waypoint list with departure at t0. Returns (route, obs_end, info) or a failure
        tuple (None, index_of_failing_contact)."""
        r = self.rules
        w = self.world
        v = 0.96 * a.v_h_mps
        vup, vdn = 0.96 * a.v_up_mps, 0.96 * a.v_down_mps
        home = a.home
        H = (home[0], home[1])
        cont = self.contacts
        first = obs_pts[0]
        dx, dy = first[0] - H[0], first[1] - H[1]
        n = math.hypot(dx, dy) or 1.0
        dc = min(60.0, 0.5 * n)
        W1 = (H[0] + dx / n * dc, H[1] + dy / n * dc)
        last = obs_pts[-1]
        dx, dy = last[0] - H[0], last[1] - H[1]
        n2 = math.hypot(dx, dy) or 1.0
        dd = min(60.0, 0.5 * n2)
        Wd = (H[0] + dx / n2 * dd, H[1] + dy / n2 * dd)
        route = [wp(t0, home[0], home[1], 0.0)]
        t = t0 + max(dc / v, z / vup) + 0.5
        route.append(wp(t, W1[0], W1[1], z))
        cur = W1
        obs_end = {}
        waits = 0.0
        slack = INF
        cum = 0.0
        for k, cid in enumerate(seq):
            q = obs_pts[k]
            res = w.path(cur, q, z)
            if res is None:
                return None, k
            poly, L = res
            arr = t + L / v
            c = cont[cid]
            lo = c.window[0] + 0.05
            start = max(arr, lo)
            if start > latest[cid] + 1e-9:
                return None, k
            if start > arr:
                cum += start - arr
            slack = min(slack, cum + latest[cid] - start)
            dur = start - t
            acc = 0.0
            for j in range(1, len(poly) - 1):
                acc += math.hypot(poly[j][0] - poly[j - 1][0], poly[j][1] - poly[j - 1][1])
                route.append(wp(t + dur * acc / L if L > 0 else t, poly[j][0], poly[j][1], z))
            if len(poly) > 1 and math.hypot(q[0] - cur[0], q[1] - cur[1]) < 1e-9:
                pass
            route.append(wp(start, q[0], q[1], z, action="observe", target=cid, dwell_s=float(r.obs_dwell_s)))
            t = start + r.obs_dwell_s
            obs_end[cid] = t
            cur = q
        res = w.path(cur, Wd, z)
        if res is None:
            return None, len(seq) - 1
        poly, L = res
        for j in range(1, len(poly)):
            t += math.hypot(poly[j][0] - poly[j - 1][0], poly[j][1] - poly[j - 1][1]) / v
            route.append(wp(t, poly[j][0], poly[j][1], z))
        t += max(dd / v, z / vdn) + 0.5
        route.append(wp(t, home[0], home[1], 0.0))
        if t > self.sc.horizon_s - 0.5:
            return None, len(seq) - 1
        # drop zero-length duplicate non-action waypoints (keeps the route tidy)
        clean = [route[0]]
        for x in route[1:]:
            p = clean[-1]
            if x.get("action") is None and p.get("action") is None and len(clean) > 1 and \
                    abs(x["x"] - p["x"]) < 1e-9 and abs(x["y"] - p["y"]) < 1e-9 and abs(x["z"] - p["z"]) < 1e-9:
                clean[-1] = x if x["t"] >= p["t"] else p
                continue
            clean.append(x)
        e = route_energy_wh(to_wps(clean), a)
        return clean, obs_end, {"energy": e, "slack": slack, "waits": cum, "land": t}

    def plan(self, a, z: float, seq: List[str], latest: Dict[str, float]):
        """Builds the best departure for a tour, dropping contacts the exact model cannot fit.
        Returns (route, obs_end, info, seq_kept, obs_pts) or None."""
        seq = list(seq)
        while seq:
            pts = self.geometry(a, z, seq)
            if pts is None:
                seq.pop()
                continue
            out = self.build(a, z, seq, pts, 0.0, latest)
            if out[0] is None:
                seq.pop(out[1])
                continue
            route, obs_end, info = out
            delta = max(0.0, min(info["slack"], info["waits"]) - 0.05)
            if delta > 0:
                out2 = self.build(a, z, seq, pts, delta, latest)
                if out2[0] is not None:
                    route, obs_end, info = out2
                    info["t0"] = delta
            info.setdefault("t0", 0.0)
            if info["energy"] > a.usable_wh - 0.05:
                # drop the contact whose removal saves the most (approx: the farthest)
                far = max(range(len(seq)), key=lambda k: math.hypot(pts[k][0] - a.home[0], pts[k][1] - a.home[1]))
                seq.pop(far)
                continue
            return route, obs_end, info, seq, pts
        return None


# -------------------------------------------------------------------------------------- effectors

def effector_route(a, c, t_eng: float, z: float, theta: float, world: World, cyl: Cyl,
                   d_app: Optional[float] = None) -> Optional[List[dict]]:
    v = 0.96 * a.v_h_mps
    vup, vdn = 0.96 * a.v_up_mps, 0.96 * a.v_down_mps
    if d_app is None:
        d_app = max(40.0, min(110.0, 0.8 * z / vdn * v))
    A = (c.pos[0] + d_app * math.cos(theta), c.pos[1] + d_app * math.sin(theta))
    if not world.point_free(A[0], A[1], z, 1.0):
        return None
    if not cyl.leg_ok((A[0], A[1], z), (c.pos[0], c.pos[1], 0.0)):
        return None
    home = a.home
    H = (home[0], home[1])
    dx, dy = A[0] - H[0], A[1] - H[1]
    n = math.hypot(dx, dy) or 1.0
    dc = min(60.0, 0.5 * n)
    W1 = (H[0] + dx / n * dc, H[1] + dy / n * dc)
    res = world.path(W1, A, z)
    if res is None:
        return None
    poly, L = res
    t_dive = max(d_app / v, z / vdn) + 0.3
    t_climb = max(dc / v, z / vup) + 0.5
    t_dep = t_eng - t_dive - L / v - t_climb
    if t_dep < 0.0:
        return None
    route = [wp(t_dep, home[0], home[1], 0.0)]
    t = t_dep + t_climb
    route.append(wp(t, W1[0], W1[1], z))
    for j in range(1, len(poly)):
        t += math.hypot(poly[j][0] - poly[j - 1][0], poly[j][1] - poly[j - 1][1]) / v
        route.append(wp(t, poly[j][0], poly[j][1], z))
    route.append(wp(t_eng, c.pos[0], c.pos[1], 0.0, action="engage", target=c.id))
    if route[-1]["t"] < route[-2]["t"] + t_dive - 1e-6:
        return None
    e = route_energy_wh(to_wps(route), a)
    if e > a.usable_wh - 0.05:
        return None
    return route


def effector_energy_estimate(a, dist: float) -> float:
    v = 0.96 * a.v_h_mps
    return (a.power.p0_w + a.power.k_v * v * v) / v * dist / 3600.0
