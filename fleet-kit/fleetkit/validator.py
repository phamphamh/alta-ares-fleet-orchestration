"""The ten rules. A plan is valid only if no rule is violated."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .energy import route_energy_wh
from .geometry import (EPS, INF, Piece, close_intervals, dist3, hdist, min_distance,
                       overlapping_pieces, segment_enters_cylinder, within_radius_interval)
from .model import (CIVILIAN, EFFECTOR, FRIENDLY, HOSTILE, SCOUT, UNKNOWN, Aircraft, Contact,
                    Route, Scenario, Waypoint, parse_plan)

RULE_NAMES = {
    "R1": "well-formed", "R2": "kinematics", "R3": "energy and return",
    "R4": "confirm before engage", "R5": "authorisation", "R6": "exclusion",
    "R7": "collateral", "R8": "separation", "R9": "time windows",
    "R10": "all-or-nothing engagement",
}


@dataclass
class Violation:
    """One rule violation."""

    rule: str
    message: str
    aircraft: Optional[str] = None
    contact: Optional[str] = None

    def __str__(self) -> str:
        who = " ".join(x for x in (self.aircraft, self.contact) if x)
        return f"{self.rule} ({RULE_NAMES[self.rule]}){' [' + who + ']' if who else ''}: {self.message}"


def route_pieces(route: Route) -> List[Piece]:
    """Returns the airborne motion of a route as linear pieces, from first departure to last arrival."""
    w = route.waypoints
    pieces: List[Piece] = []
    for k in range(len(w) - 1):
        pieces.append((w[k].depart, w[k + 1].t, w[k].pos, w[k + 1].pos))
        if w[k + 1].dwell_s > 0:
            pieces.append((w[k + 1].t, w[k + 1].depart, w[k + 1].pos, w[k + 1].pos))
    return pieces


def valid_observation(wp: Waypoint, contact: Contact, scenario: Scenario) -> bool:
    """Tells whether an observe waypoint has the range and the dwell to count as an observation."""
    r = scenario.rules
    return dist3(wp.pos, contact.pos) <= r.R_obs_m + EPS and wp.dwell_s >= r.obs_dwell_s - EPS


def _r1(scenario: Scenario, routes: Dict[str, Route], plan: Any) -> List[Violation]:
    out: List[Violation] = []
    aircraft = scenario.aircraft_by_id()
    contacts = scenario.contact_by_id()
    if plan.get("seed") != scenario.seed:
        out.append(Violation("R1", f"plan seed {plan.get('seed')!r} does not match the scenario seed {scenario.seed}"))
    horizon = scenario.horizon_s
    for aid, route in routes.items():
        ac = aircraft.get(aid)
        if ac is None:
            out.append(Violation("R1", "unknown aircraft", aircraft=aid))
            continue
        w = route.waypoints
        if len(w) < 2:
            out.append(Violation("R1", "a route needs at least two waypoints; omit unused aircraft", aircraft=aid))
            continue
        first = w[0]
        if dist3(first.pos, ac.home) > EPS:
            out.append(Violation("R1", "the first waypoint must be the home position", aircraft=aid))
        if first.action is not None or first.dwell_s != 0.0:
            out.append(Violation("R1", "the first waypoint has no action and no dwell", aircraft=aid))
        for k, wp in enumerate(w):
            if wp.t < -EPS or wp.depart > horizon + EPS:
                out.append(Violation("R1", f"waypoint {k} lies outside [0, {horizon:g}] s", aircraft=aid))
            if k > 0 and wp.t < w[k - 1].depart - EPS:
                out.append(Violation("R1", f"waypoint {k} arrives before the previous departure", aircraft=aid))
            if wp.action is not None:
                if wp.target not in contacts:
                    out.append(Violation("R1", f"waypoint {k}: unknown target {wp.target!r}", aircraft=aid))
                if wp.action == "observe" and wp.dwell_s <= 0:
                    out.append(Violation("R1", f"waypoint {k}: an observation needs dwell_s > 0", aircraft=aid))
                if wp.action == "engage":
                    if k != len(w) - 1:
                        out.append(Violation("R1", "an engage waypoint must be the last of its route", aircraft=aid))
                    if wp.dwell_s != 0.0:
                        out.append(Violation("R1", "an engage waypoint has no dwell", aircraft=aid))
        if ac.type == EFFECTOR and w[-1].action != "engage":
            out.append(Violation("R1", "an effector route must end with an engagement; omit unused effectors", aircraft=aid))
    return out


def _r2(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    rules = scenario.rules
    aircraft = scenario.aircraft_by_id()
    for aid, route in routes.items():
        ac = aircraft[aid]
        w = route.waypoints
        for k in range(len(w) - 1):
            a, b = w[k], w[k + 1]
            duration = b.t - a.depart
            dh = math.hypot(b.x - a.x, b.y - a.y)
            dz = b.z - a.z
            need = dh / ac.v_h_mps
            need = max(need, dz / ac.v_up_mps if dz > 0 else -dz / ac.v_down_mps)
            if duration < need - EPS:
                out.append(Violation("R2", f"leg {k + 1} needs at least {need:.2f} s, the plan gives {duration:.2f} s", aircraft=aid))
        for k in range(1, len(w)):
            z = w[k].z
            low = 0.0 if k == len(w) - 1 else rules.z_min_m
            if z < low - EPS or z > rules.z_max_m + EPS:
                out.append(Violation("R2", f"waypoint {k} altitude {z:g} m is outside [{low:g}, {rules.z_max_m:g}]", aircraft=aid))
    return out


def _r3(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    aircraft = scenario.aircraft_by_id()
    for aid, route in routes.items():
        ac = aircraft[aid]
        energy = route_energy_wh(route.waypoints, ac)
        if energy > ac.usable_wh + EPS:
            out.append(Violation("R3", f"route needs {energy:.2f} Wh, usable energy is {ac.usable_wh:.2f} Wh", aircraft=aid))
        if ac.type == SCOUT and dist3(route.waypoints[-1].pos, ac.home) > EPS:
            out.append(Violation("R3", "a scout must end at its home at z = 0", aircraft=aid))
    return out


def _actions(routes: Dict[str, Route]):
    for aid, route in routes.items():
        for k, wp in enumerate(route.waypoints):
            if wp.action is not None:
                yield aid, k, wp


def _r5(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    aircraft, contacts = scenario.aircraft_by_id(), scenario.contact_by_id()
    for aid, k, wp in _actions(routes):
        ac, c = aircraft[aid], contacts.get(wp.target)
        if c is None:
            continue
        if wp.action == "engage":
            if ac.type != EFFECTOR:
                out.append(Violation("R5", "only effectors engage", aircraft=aid, contact=c.id))
            if c.cls != HOSTILE:
                out.append(Violation("R5", f"only hostile contacts may be engaged, this one is {c.cls}", aircraft=aid, contact=c.id))
        else:
            if ac.type != SCOUT:
                out.append(Violation("R5", "only scouts observe", aircraft=aid, contact=c.id))
            if c.cls not in (HOSTILE, UNKNOWN):
                out.append(Violation("R5", f"only hostile or unknown contacts may be observed, this one is {c.cls}", aircraft=aid, contact=c.id))
    return out


def _r4(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    aircraft, contacts = scenario.aircraft_by_id(), scenario.contact_by_id()
    margin = scenario.rules.confirm_margin_s
    observations: Dict[str, List[Waypoint]] = {}
    for aid, k, wp in _actions(routes):
        c = contacts.get(wp.target)
        if wp.action == "observe" and aircraft[aid].type == SCOUT and c is not None \
                and valid_observation(wp, c, scenario):
            observations.setdefault(c.id, []).append(wp)
    for aid, k, wp in _actions(routes):
        if wp.action != "engage" or aircraft[aid].type != EFFECTOR:
            continue
        c = contacts.get(wp.target)
        if c is None or c.cls != HOSTILE:
            continue
        confirmed = any(o.t + o.dwell_s <= wp.t - margin + EPS for o in observations.get(c.id, []))
        if not confirmed:
            out.append(Violation("R4", f"engagement at t = {wp.t:g} s has no completed scout observation at least {margin:g} s earlier", aircraft=aid, contact=c.id))
    return out


def _r6(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    cylinders = [(z.id, z.center, z.radius_m, z.top_m, f"zone {z.id}") for z in scenario.zones]
    for c in scenario.contacts:
        if c.cls in (FRIENDLY, CIVILIAN):
            cylinders.append((c.id, c.pos[:2], scenario.rules.protect_radius_m, INF, f"protected area of {c.id}"))
    for aid, route in routes.items():
        w = route.waypoints
        for k in range(len(w) - 1):
            for _, center, radius, top, label in cylinders:
                if segment_enters_cylinder(w[k].pos, w[k + 1].pos, center, radius, top):
                    out.append(Violation("R6", f"leg {k + 1} enters {label}", aircraft=aid))
    return out


def _r7(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    contacts = scenario.contact_by_id()
    seen = set()
    for aid, k, wp in _actions(routes):
        c = contacts.get(wp.target)
        if wp.action != "engage" or c is None or c.cls != HOSTILE or c.id in seen:
            continue
        seen.add(c.id)
        for f in scenario.contacts:
            if f.cls in (FRIENDLY, CIVILIAN) and hdist(c.pos, f.pos) < scenario.rules.collateral_radius_m - EPS:
                out.append(Violation("R7", f"{f.id} ({f.cls}) is {hdist(c.pos, f.pos):.0f} m away, inside the collateral radius", aircraft=aid, contact=c.id))
    return out


def _r9(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    contacts = scenario.contact_by_id()
    for aid, k, wp in _actions(routes):
        c = contacts.get(wp.target)
        if c is None:
            continue
        if c.window is None:
            if c.cls in (HOSTILE, UNKNOWN):
                out.append(Violation("R9", "the contact has no time window", aircraft=aid, contact=c.id))
            continue
        lo, hi = c.window
        start, end = wp.t, (wp.t + wp.dwell_s if wp.action == "observe" else wp.t)
        if start < lo - EPS or end > hi + EPS:
            out.append(Violation("R9", f"{wp.action} spans [{start:g}, {end:g}] s, outside the window [{lo:g}, {hi:g}] s", aircraft=aid, contact=c.id))
    return out


def _r10(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    aircraft, contacts = scenario.aircraft_by_id(), scenario.contact_by_id()
    groups: Dict[str, List[Tuple[str, Waypoint]]] = {}
    for aid, k, wp in _actions(routes):
        c = contacts.get(wp.target)
        if wp.action == "engage" and c is not None and c.cls == HOSTILE and aircraft[aid].type == EFFECTOR:
            groups.setdefault(c.id, []).append((aid, wp))
    for cid, engagements in groups.items():
        c = contacts[cid]
        counts: Dict[str, int] = {}
        for aid, wp in engagements:
            sub = aircraft[aid].subtype or "?"
            counts[sub] = counts.get(sub, 0) + 1
        want = {k: v for k, v in c.needs.items() if v > 0}
        if counts != want:
            out.append(Violation("R10", f"engaged by {counts or 'nobody'}, the contact needs exactly {want}", contact=cid))
        times = [wp.t for _, wp in engagements]
        if max(times) - min(times) > scenario.rules.sync_window_s + EPS:
            out.append(Violation("R10", f"engagements span {max(times) - min(times):.1f} s, more than the {scenario.rules.sync_window_s:g} s synchronisation window", contact=cid))
        for aid, wp in engagements:
            if dist3(wp.pos, c.pos) > scenario.rules.R_eng_m + EPS:
                out.append(Violation("R10", f"engagement point is {dist3(wp.pos, c.pos):.1f} m from the contact, the limit is {scenario.rules.R_eng_m:g} m", aircraft=aid, contact=cid))
    return out


def separation_item(aid: str, route: Route, aircraft: Aircraft):
    """Returns what the separation check needs from one route: pieces, time span, engage target."""
    pieces = route_pieces(route)
    if not pieces:
        return None
    last = route.waypoints[-1]
    target = last.target if (last.action == "engage" and aircraft.type == EFFECTOR) else None
    return (aid, pieces, pieces[0][0], pieces[-1][1], target)


def separation_violation(rules, contacts: Dict[str, Contact], item_a, item_b) -> Optional[Violation]:
    """Checks the separation rule (R8) for one pair of routes; returns the violation, if any."""
    d_sep = rules.d_sep_m - EPS
    aid_a, pa, s_a, e_a, tgt_a = item_a
    aid_b, pb, s_b, e_b, tgt_b = item_b
    if min(e_a, e_b) - max(s_a, s_b) <= 1e-12:
        return None
    exempt_center = None
    if tgt_a is not None and tgt_a == tgt_b and tgt_a in contacts:
        exempt_center = contacts[tgt_a].pos
    hit = None
    for a, b, lo, hi in overlapping_pieces(pa, pb):
        bad = close_intervals(a, b, lo, hi, d_sep)
        if bad is None:
            continue
        if exempt_center is not None:
            ea = within_radius_interval(a, lo, hi, exempt_center, rules.exempt_radius_m)
            eb = within_radius_interval(b, lo, hi, exempt_center, rules.exempt_radius_m)
            if ea is not None and eb is not None:
                e1, e2 = max(ea[0], eb[0]), min(ea[1], eb[1])
                if e1 <= e2:
                    parts = []
                    if e1 - bad[0] > 1e-6:
                        parts.append((bad[0], min(bad[1], e1)))
                    if bad[1] - e2 > 1e-6:
                        parts.append((max(bad[0], e2), bad[1]))
                    bad = parts[0] if parts else None
        if bad is not None and bad[1] - bad[0] > 1e-6:
            hit = (bad[0], min_distance(a, b, lo, hi))
            break
    if hit is None:
        return None
    return Violation("R8", f"{aid_a} and {aid_b} come within {hit[1]:.1f} m of each other (limit {rules.d_sep_m:g} m) around t = {hit[0]:.1f} s")


def _r8(scenario: Scenario, routes: Dict[str, Route]) -> List[Violation]:
    out: List[Violation] = []
    contacts = scenario.contact_by_id()
    aircraft = scenario.aircraft_by_id()
    items = []
    for aid, route in routes.items():
        item = separation_item(aid, route, aircraft[aid])
        if item is not None:
            items.append(item)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            v = separation_violation(scenario.rules, contacts, items[i], items[j])
            if v is not None:
                out.append(v)
    return out


def validate(scenario: Scenario, plan: Any) -> List[Violation]:
    """Checks a plan against the ten rules.

    Args:
        scenario: The scenario.
        plan: The decoded plan JSON.

    Returns:
        Every violation found; an empty list means the plan is valid. If the plan is not
        well-formed (R1), only the R1 violations are returned.
    """
    routes, errors = parse_plan(plan)
    if routes is None:
        return [Violation("R1", e) for e in errors]
    out = [Violation("R1", e) for e in errors] + _r1(scenario, routes, plan)
    if out:
        return out
    for check in (_r2, _r3, _r4, _r5, _r6, _r7, _r8, _r9, _r10):
        out.extend(check(scenario, routes))
    return out
