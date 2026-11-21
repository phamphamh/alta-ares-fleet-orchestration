"""A deliberately simple greedy planner: the baseline every team can beat.

For each hostile contact, richest first, it picks the nearest scout and the nearest effectors of
the needed subtypes, routes them at fixed altitude layers with detours around zones, and keeps
the assignment only if the whole plan stays valid and its score improves. Then it adds
observations of unknown contacts the same way. It uses no search, no optimisation and no
look-ahead.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .energy import best_range_speed
from .geometry import INF, hdist, segment_enters_cylinder
from .model import CIVILIAN, FRIENDLY, HOSTILE, SCOUT, UNKNOWN, Aircraft, Contact, Scenario
from .scorer import evaluate

Point = Tuple[float, float, float]
SCOUT_LAYERS = (70.0, 110.0)
EFFECTOR_LAYERS = (40.0, 85.0, 130.0)
ENGAGE_Z = 10.0
APPROACH_M = 300.0
OBS_OFFSET_M = 100.0
SPEED_FACTOR = 0.95


def _cylinders(scenario: Scenario):
    out = [(z.center, z.radius_m, z.top_m) for z in scenario.zones]
    for c in scenario.contacts:
        if c.cls in (FRIENDLY, CIVILIAN):
            out.append((c.pos[:2], scenario.rules.protect_radius_m, INF))
    return out


def _detour(points: List[Point], scenario: Scenario) -> Optional[List[Point]]:
    """Inserts waypoints so that no leg enters a zone or a protected area at its altitude."""
    cylinders = _cylinders(scenario)
    pts = list(points)
    for _ in range(12):
        changed = False
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            for center, radius, top in cylinders:
                if not segment_enters_cylinder(a, b, center, radius + 15.0, top):
                    continue
                dx, dy = b[0] - a[0], b[1] - a[1]
                length2 = dx * dx + dy * dy
                if length2 < 1e-9:
                    return None
                s = max(0.0, min(1.0, ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy) / length2))
                cx, cy = a[0] + s * dx, a[1] + s * dy
                ox, oy = cx - center[0], cy - center[1]
                norm = math.hypot(ox, oy)
                if norm < 1e-6:
                    ox, oy, norm = -dy, dx, math.sqrt(length2)
                reach = radius + 60.0
                z = a[2] + s * (b[2] - a[2])
                pts.insert(i + 1, (center[0] + ox / norm * reach, center[1] + oy / norm * reach, z))
                changed = True
                break
            if changed:
                break
        if not changed:
            return pts
    return None


def _length(points: List[Point]) -> float:
    return sum(hdist(points[i], points[i + 1]) for i in range(len(points) - 1))


def _wp(t: float, p: Point, **extra) -> dict:
    d = {"t": round(t, 3), "x": round(p[0], 3), "y": round(p[1], 3), "z": round(p[2], 3)}
    d.update(extra)
    return d


def _rotate(vx: float, vy: float, degrees: float) -> Tuple[float, float]:
    a = math.radians(degrees)
    return vx * math.cos(a) - vy * math.sin(a), vx * math.sin(a) + vy * math.cos(a)


def _toward_home(contact: Contact, home: Point, degrees: float) -> Tuple[float, float]:
    vx, vy = home[0] - contact.pos[0], home[1] - contact.pos[1]
    n = math.hypot(vx, vy) or 1.0
    return _rotate(vx / n, vy / n, degrees)


def _scout_route(scout: Aircraft, tasks: List[dict], depart: float, z: float,
                 scenario: Scenario) -> Optional[List[dict]]:
    """Builds a scout route: climb, visit each observation point in order, return and land."""
    rules = scenario.rules
    speed = min(SPEED_FACTOR * scout.v_h_mps, best_range_speed(scout.power))
    home = scout.home
    above = (home[0], home[1], z)
    t = depart
    wps = [_wp(t, home)]
    t += z / (SPEED_FACTOR * scout.v_up_mps) + 0.5
    wps.append(_wp(t, above))
    cur: Point = above
    for task in tasks:
        target: Point = (task["point"][0], task["point"][1], z)
        path = _detour([cur, target], scenario)
        if path is None:
            return None
        natural = _length(path) / speed
        lo, hi = task["window"]
        arrive = max(t + natural, lo)
        if arrive + rules.obs_dwell_s > hi:
            return None
        total = _length(path)
        for k in range(1, len(path) - 1):
            wps.append(_wp(t + (arrive - t) * _length(path[:k + 1]) / total, path[k]))
        wps.append(_wp(arrive, target, action="observe", target_id=task["cid"], dwell_s=rules.obs_dwell_s))
        t = arrive + rules.obs_dwell_s
        cur = target
    path = _detour([cur, above], scenario)
    if path is None:
        return None
    total = _length(path)
    arrive = t + total / speed
    for k in range(1, len(path) - 1):
        wps.append(_wp(t + (arrive - t) * _length(path[:k + 1]) / total, path[k]))
    wps.append(_wp(arrive, above))
    wps.append(_wp(arrive + z / (SPEED_FACTOR * scout.v_down_mps) + 0.5, home))
    for w in wps:
        if "target_id" in w:
            w["target"] = w.pop("target_id")
    return wps


def _effector_route(eff: Aircraft, contact: Contact, arrive: float, z: float, angle: float,
                    scenario: Scenario) -> Tuple[Optional[List[dict]], float]:
    """Builds an effector route arriving at `arrive`; returns (route, earliest feasible arrival)."""
    home = eff.home
    dist = hdist(home, contact.pos)
    reach = min(APPROACH_M, 0.5 * dist)
    ux, uy = _toward_home(contact, home, angle)
    a_pt: Point = (contact.pos[0] + ux * reach, contact.pos[1] + uy * reach, z)
    e_pt: Point = (contact.pos[0], contact.pos[1], ENGAGE_Z)
    over: Point = (home[0], home[1], z)
    path = _detour([over, a_pt], scenario)
    if path is None:
        return None, arrive
    v_h = SPEED_FACTOR * eff.v_h_mps
    t_final = max(hdist(a_pt, e_pt) / v_h, (z - ENGAGE_Z) / (SPEED_FACTOR * eff.v_down_mps)) + 0.2
    v_cruise = min(v_h, best_range_speed(eff.power))
    total = _length(path)
    t_cruise = total / v_cruise
    t_climb = z / (SPEED_FACTOR * eff.v_up_mps) + 0.5
    earliest = t_climb + t_cruise + t_final
    if arrive < earliest:
        return None, earliest
    t_a = arrive - t_final
    t_o = t_a - t_cruise
    wps = [_wp(t_o - t_climb, home), _wp(t_o, over)]
    for k in range(1, len(path) - 1):
        wps.append(_wp(t_o + t_cruise * _length(path[:k + 1]) / total, path[k]))
    wps.append(_wp(t_a, a_pt))
    wps.append(_wp(arrive, e_pt, action="engage", target=contact.id))
    return wps, earliest


class _Planner:
    def __init__(self, scenario: Scenario):
        self.sc = scenario
        self.routes: Dict[str, List[dict]] = {}
        self.tasks: Dict[str, List[dict]] = {s.id: [] for s in scenario.aircraft if s.type == SCOUT}
        self.used: set = set()
        self.score = 0.0

    def _plan(self, extra: Dict[str, List[dict]]) -> dict:
        routes = dict(self.routes)
        routes.update(extra)
        return {"seed": self.sc.seed, "routes": [{"aircraft": a, "waypoints": w} for a, w in routes.items()]}

    def _try(self, extra: Dict[str, List[dict]]) -> Optional[float]:
        result = evaluate(self.sc, self._plan(extra))
        return result.score if result.valid else None

    def _scout_candidates(self, contact: Contact, limit: int = 3) -> List[Aircraft]:
        scouts = [a for a in self.sc.aircraft if a.type == SCOUT]
        scouts.sort(key=lambda s: hdist(s.home, contact.pos))
        return scouts[:limit]

    def _obs_point(self, scout: Aircraft, contact: Contact, angle: float) -> Tuple[float, float]:
        ux, uy = _toward_home(contact, scout.home, angle)
        return contact.pos[0] + ux * OBS_OFFSET_M, contact.pos[1] + uy * OBS_OFFSET_M

    def _add_observation(self, scout: Aircraft, contact: Contact, z: float, angle: float,
                         dep_shift: float) -> Optional[Tuple[List[dict], List[dict]]]:
        task = {"cid": contact.id, "point": self._obs_point(scout, contact, angle), "window": contact.window}
        tasks = self.tasks[scout.id] + [task]
        first_lo = tasks[0]["window"][0]
        speed = min(SPEED_FACTOR * scout.v_h_mps, best_range_speed(scout.power))
        travel = hdist(scout.home, tasks[0]["point"]) / speed + z / scout.v_up_mps + 3.0
        route = _scout_route(scout, tasks, max(0.0, first_lo - travel) + dep_shift, z, self.sc)
        return (tasks, route) if route is not None else None

    def serve_hostile(self, contact: Contact) -> bool:
        sc = self.sc
        pool = {}
        for sub, n in contact.needs.items():
            free = [a for a in sc.aircraft if a.type != SCOUT and a.subtype == sub and a.id not in self.used]
            free.sort(key=lambda a: hdist(a.home, contact.pos))
            if len(free) < n:
                return False
            pool[sub] = free[:n]
        effectors = [a for sub in sorted(pool) for a in pool[sub]]
        for scout in self._scout_candidates(contact):
            for z in SCOUT_LAYERS:
                for angle in (0.0, 60.0, -60.0):
                    for dep_shift in (0.0, 7.0):
                        built = self._add_observation(scout, contact, z, angle, dep_shift)
                        if built is None:
                            continue
                        tasks, route = built
                        if self._try({scout.id: route}) is None:
                            continue
                        obs_end = max(w["t"] + w.get("dwell_s", 0.0) for w in route
                                      if w.get("target") == contact.id and w.get("action") == "observe")
                        if self._place_effectors(contact, effectors, obs_end, scout, tasks, route):
                            return True
        return False

    def _place_effectors(self, contact, effectors, obs_end, scout, tasks, scout_route) -> bool:
        lo, hi = contact.window
        base = max(obs_end + self.sc.rules.confirm_margin_s + 2.0, lo)
        for delay in (0.0, 8.0, 20.0, 45.0, 90.0):
            arrive = base + delay
            if arrive + 5.0 * len(effectors) > hi:
                break
            for angle in (0.0, 35.0, -35.0):
                for rotation in range(3):
                    extra = {scout.id: scout_route}
                    ok = True
                    for i, eff in enumerate(effectors):
                        z = EFFECTOR_LAYERS[(i + rotation) % len(EFFECTOR_LAYERS)]
                        route, earliest = _effector_route(eff, contact, arrive + 5.0 * i, z, angle, self.sc)
                        if route is None:
                            ok = False
                            break
                        extra[eff.id] = route
                    if not ok:
                        continue
                    new = self._try(extra)
                    if new is not None and new > self.score:
                        self.routes.update(extra)
                        self.tasks[scout.id] = tasks
                        self.used.update(e.id for e in effectors)
                        self.score = new
                        return True
        return False

    def serve_unknown(self, contact: Contact) -> bool:
        for scout in self._scout_candidates(contact):
            for z in SCOUT_LAYERS:
                for angle in (0.0, 60.0, -60.0):
                    for dep_shift in (0.0, 7.0):
                        built = self._add_observation(scout, contact, z, angle, dep_shift)
                        if built is None:
                            continue
                        tasks, route = built
                        new = self._try({scout.id: route})
                        if new is not None and new > self.score:
                            self.routes[scout.id] = route
                            self.tasks[scout.id] = tasks
                            self.score = new
                            return True
        return False


def greedy_plan(scenario: Scenario, max_contacts: Optional[int] = None) -> dict:
    """Builds a valid plan greedily.

    Args:
        scenario: The scenario.
        max_contacts: If given, only the richest hostile contacts up to this number are tried
            (used to check quickly that a scenario has a positive plan).

    Returns:
        A plan dictionary (valid by construction: an assignment is kept only if the whole plan
        stays valid and its score improves).
    """
    planner = _Planner(scenario)
    hostiles = sorted((c for c in scenario.contacts if c.cls == HOSTILE), key=lambda c: -c.points)
    unknowns = sorted((c for c in scenario.contacts if c.cls == UNKNOWN), key=lambda c: -c.points)
    if max_contacts is not None:
        hostiles = hostiles[:max_contacts]
        unknowns = unknowns[:max_contacts]
    for c in hostiles:
        planner.serve_hostile(c)
    for c in unknowns:
        planner.serve_unknown(c)
    return planner._plan({})
