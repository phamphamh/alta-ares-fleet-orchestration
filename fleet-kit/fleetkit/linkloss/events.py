"""Draws the events of a link-loss scenario, against a given plan, and verifies them by simulation."""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from ..geometry import dist3
from ..model import EFFECTOR, HOSTILE, SCOUT, Scenario, parse_plan
from .policies import ContinuePolicy
from .sim import R_SENSE_M, RouteClock, simulate

VERSION = 1


def _timeline(scenario: Scenario, plan: dict):
    routes, _ = parse_plan(plan)
    aircraft = scenario.aircraft_by_id()
    clocks = {a: RouteClock(r) for a, r in routes.items()}
    engage: Dict[str, List[tuple]] = {}
    observe: List[tuple] = []
    for aid, r in routes.items():
        for wp in r.waypoints:
            if wp.action == "engage" and aircraft[aid].type == EFFECTOR:
                engage.setdefault(wp.target, []).append((aid, wp.t))
            elif wp.action == "observe" and aircraft[aid].type == SCOUT:
                observe.append((aid, wp.target, wp.t))
    return routes, clocks, engage, observe


def _draw(scenario: Scenario, plan: dict, rng: random.Random) -> Optional[dict]:
    routes, clocks, engage, observe = _timeline(scenario, plan)
    span = max(c.end for c in clocks.values())   # the plan's duration: its last landing or engagement
    t_loss = float(round(rng.uniform(0.25 * span, 0.5 * span)))
    n = rng.choice([2, 2, 3])
    events: List[dict] = []
    used_contacts, used_aircraft = set(), set()
    for _ in range(4 * n):
        if len(events) >= n:
            break
        kind = rng.choice(["reclassify", "popup_zone", "failure"])
        if kind == "reclassify":
            cands = [(c, max(t for _, t in lst)) for c, lst in engage.items()
                     if min(t for _, t in lst) >= t_loss + 45 and c not in used_contacts]
            if not cands:
                continue
            c, te = rng.choice(cands)
            events.append({"kind": "reclassify", "t": float(round(rng.uniform(t_loss + 5, te - 35))), "contact": c})
            used_contacts.add(c)
        elif kind == "failure":
            cands = []
            for aid, c, t in observe:
                if c in engage and t >= t_loss + 25 and aid not in used_aircraft:
                    cands.append((aid, t - 10))
            for c, lst in engage.items():
                if len(lst) >= 2:
                    for aid, t in lst:
                        if t >= t_loss + 30 and aid not in used_aircraft:
                            cands.append((aid, t - 15))
            if not cands:
                continue
            aid, last = rng.choice(cands)
            events.append({"kind": "failure", "t": float(round(rng.uniform(t_loss + 5, max(t_loss + 6, last)))), "aircraft": aid})
            used_aircraft.add(aid)
        else:
            aid = rng.choice(sorted(clocks))
            clock = clocks[aid]
            lo, hi = max(t_loss + 35, clock.start + 10), clock.end - 10
            if hi <= lo:
                continue
            tp = rng.uniform(lo, hi)
            center = clock.position(tp)
            if center[2] < 20.0:
                continue
            te = float(round(rng.uniform(t_loss + 5, tp - 25))) if tp - 25 > t_loss + 5 else None
            if te is None:
                continue
            radius = float(round(rng.uniform(60, 120)))
            if any(dist3((center[0], center[1], 0), (c.position(te)[0], c.position(te)[1], 0)) < radius + 15
                   for c in clocks.values()):
                continue  # nobody is inside when it appears
            events.append({"kind": "popup_zone", "t": te, "center": [round(center[0], 1), round(center[1], 1)],
                           "radius_m": radius, "top_m": 200.0})
    if not events:
        return None
    events.sort(key=lambda e: e["t"])
    return {"version": VERSION, "t_loss": t_loss, "events": events}


def make_events(scenario: Scenario, plan: dict, seed: int, tries: int = 300) -> dict:
    """Draws events for a plan and keeps a set only if the oracle copes and the blind plan fails.

    Args:
        scenario: The scenario.
        plan: A valid plan; the events are designed against its timeline.
        seed: Seed of the draw.
        tries: How many draws to attempt.

    Returns:
        The events dictionary, with `seed`, `t_loss`, `events` and `oracle_points`.
    """
    rng = random.Random(f"events:{scenario.seed}:{seed}")
    for _ in range(tries):
        ev = _draw(scenario, plan, rng)
        if ev is None:
            continue
        oracle = simulate(scenario, plan, ev, oracle=True)
        if oracle.failed or oracle.points <= 0:
            continue
        blind = simulate(scenario, plan, ev, ContinuePolicy)
        if not blind.failed:
            continue
        ev["seed"] = seed
        ev["oracle_points"] = oracle.points
        return ev
    raise RuntimeError("no event set found that the oracle survives and that breaks the blind plan")
