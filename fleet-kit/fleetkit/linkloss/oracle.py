"""The full-information reference ("oracle") of the link-loss part.

It knows every event the moment it happens and every aircraft's state, uses only continue, hold
and return, and holds an aircraft whenever a move would break separation. A scenario's events are
kept only if this reference finishes them without a failure.
"""
from __future__ import annotations

import dataclasses
from typing import Dict

from ..geometry import INF, dist3, segment_enters_cylinder
from ..model import EFFECTOR, SCOUT
from ..validator import separation_violation, valid_observation

MARGIN_M = 2.0


def _route_hits_zone(craft, zone) -> bool:
    """True if the part of the route still ahead enters the disc."""
    clock = craft.clock
    k = clock.next_waypoint(craft.tau)
    pts = [clock.position(craft.tau)] + clock.pos[k:]
    for a, b in zip(pts, pts[1:]):
        if segment_enters_cylinder(a, b, tuple(zone["center"]), zone["radius_m"], zone["top_m"]):
            return True
    return False


def _has_observation(scenario, crafts, target) -> bool:
    c = scenario.contact_by_id()[target]
    for craft in crafts.values():
        if craft.ac.type != SCOUT:
            continue
        for k, _, _ in craft.obs_done:
            wp = craft.route.waypoints[k]
            if wp.target == target and valid_observation(wp, c, scenario):
                return True
    return False


def _observation_pending(crafts, target) -> bool:
    for craft in crafts.values():
        if craft.ac.type != SCOUT or not craft.active or craft.mode == "return":
            continue
        k0 = craft.clock.next_waypoint(craft.tau)
        for k in range(k0, len(craft.route.waypoints)):
            wp = craft.route.waypoints[k]
            if wp.action == "observe" and wp.target == target:
                return True
        # an observation in progress (arrived, dwell not done)
        for k in craft.obs_start:
            if craft.route.waypoints[k].target == target:
                return True
    return False


def oracle_actions(scenario, crafts, active_events, t) -> Dict[str, float]:
    """Returns the route-clock rate of every airborne aircraft for this step."""
    from .sim import trial_move
    reclass = {e["contact"] for e in active_events if e["kind"] == "reclassify"}
    zones = [e for e in active_events if e["kind"] == "popup_zone"]
    airborne = [c for c in crafts.values() if c.active]
    groups: Dict[str, list] = {}
    for c in crafts.values():
        if c.ac.type == EFFECTOR and c.route.waypoints[-1].action == "engage":
            groups.setdefault(c.route.waypoints[-1].target, []).append(c)
    for c in airborne:
        if c.mode == "return":
            continue
        if any(_route_hits_zone(c, z) for z in zones):
            c.mode = "return"
        elif c.ac.type == EFFECTOR:
            target = c.route.waypoints[-1].target
            if target in reclass:
                c.mode = "return"
            elif not _has_observation(scenario, crafts, target) and not _observation_pending(crafts, target):
                c.mode = "return"
    changed = True
    while changed:  # an effector of a group that cannot complete does not go in alone
        changed = False
        for members in groups.values():
            gone = any((m.engaged_at is None and not m.alive) or m.end_kind == "landed" or m.mode == "return"
                       for m in members)
            if gone:
                for m in members:
                    if m.active and m.mode != "return":
                        m.mode = "return"
                        changed = True
    rates = {c.id: (-1.0 if c.mode == "return" else 1.0) for c in airborne}
    rules = dataclasses.replace(scenario.rules, d_sep_m=scenario.rules.d_sep_m + MARGIN_M)
    contacts = scenario.contact_by_id()
    for _ in range(6):
        moves = {c.id: trial_move(c, rates[c.id], t) for c in airborne}
        stuck = None
        for i, a in enumerate(airborne):
            for b in airborne[i + 1:]:
                if dist3(a.pos, b.pos) > 130.0:
                    continue
                pa, pb = moves[a.id][1], moves[b.id][1]
                if not pa or not pb:
                    continue
                ia = (a.id, pa, pa[0][0], pa[-1][1], _target(a))
                ib = (b.id, pb, pb[0][0], pb[-1][1], _target(b))
                if separation_violation(rules, contacts, ia, ib) is not None:
                    # the lower id keeps its move, unless it would then run into one that already stands still
                    loser = b if rates[b.id] != 0.0 or rates[a.id] == 0.0 else a
                    stuck = loser
                    break
            if stuck:
                break
        if stuck is None:
            break
        rates[stuck.id] = 0.0
    return rates


def _target(craft):
    last = craft.route.waypoints[-1]
    return last.target if (last.action == "engage" and craft.ac.type == EFFECTOR) else None
