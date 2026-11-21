"""Execution simulator for the link-loss part: a plan flown at 1 Hz, policies after the cut.

Until the cut every aircraft follows its plan exactly. After it, each aircraft calls the team's
policy every second and moves on its **route clock** `tau` (the planned time of the point it is
at): `continue` advances it, `hold` freezes it, `return` runs it backwards, `speed` slows it.
The realised trajectories are then checked with the same exact geometry as the validator.
"""
from __future__ import annotations

import bisect
import json
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..energy import piece_energy_wh
from ..geometry import EPS, INF, Piece, dist3, hdist, segment_enters_cylinder
from ..model import EFFECTOR, HOSTILE, SCOUT, UNKNOWN, Route, Scenario, parse_plan
from ..validator import separation_violation, valid_observation

STEP_S = 1.0
R_SENSE_M = 300.0          # range at which an aircraft senses an event (S)
MAX_MESSAGE_BYTES = 64     # largest message, compact JSON (S)
P_LOSS = 0.05              # base message loss (S)
SPEED_MIN = 0.5
ACTIONS = ("continue", "hold", "return", "speed")
Point = Tuple[float, float, float]


class RouteClock:
    """The planned position of one route at any planned time `tau`."""

    def __init__(self, route: Route):
        w = route.waypoints
        self.route = route
        self.arr = [x.t for x in w]
        self.dep = [x.depart for x in w]
        self.pos = [x.pos for x in w]
        self.start = self.arr[0]
        self.end = self.arr[-1]
        self.breaks = sorted(set(self.arr) | set(self.dep))

    def position(self, tau: float) -> Point:
        """Returns the planned position at planned time `tau` (home before takeoff, last point after)."""
        k = bisect.bisect_right(self.arr, tau) - 1
        if k < 0:
            return self.pos[0]
        if tau <= self.dep[k] or k == len(self.arr) - 1:
            return self.pos[k]
        span = self.arr[k + 1] - self.dep[k]
        if span <= 1e-12:
            return self.pos[k + 1]
        f = (tau - self.dep[k]) / span
        a, b = self.pos[k], self.pos[k + 1]
        return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]))

    def breakpoints(self, lo: float, hi: float) -> List[float]:
        """Returns the arrival and departure times strictly between lo and hi, in increasing order."""
        i = bisect.bisect_right(self.breaks, lo + 1e-12)
        j = bisect.bisect_left(self.breaks, hi - 1e-12)
        return self.breaks[i:j]

    def next_waypoint(self, tau: float) -> int:
        """Returns the index of the first waypoint not yet arrived at."""
        return bisect.bisect_right(self.arr, tau + 1e-12)


@dataclass
class Craft:
    """The state of one aircraft in a run."""

    id: str
    ac: Any
    route: Route
    clock: RouteClock
    tau: float = 0.0
    mode: str = "route"            # route | return
    alive: bool = True
    ended: Optional[float] = None  # real time it engaged, landed or was lost (None while airborne)
    end_kind: str = ""             # engaged | landed | lost | failed
    energy: float = 0.0
    pieces: List[Piece] = field(default_factory=list)
    pos: Point = (0.0, 0.0, 0.0)
    vel: Point = (0.0, 0.0, 0.0)
    engaged_at: Optional[float] = None
    obs_start: Dict[int, float] = field(default_factory=dict)
    obs_done: List[Tuple[int, float, float]] = field(default_factory=list)  # (waypoint, start, end)
    policy: Any = None

    @property
    def active(self) -> bool:
        return self.alive and self.ended is None


@dataclass
class RunResult:
    """What one simulated run produced."""

    failed: List[str]
    served: List[str]
    points: float
    messages: int
    messages_per_aircraft_per_min: float
    lost: List[str]
    engagements: Dict[str, List[Tuple[str, float]]]
    policy_calls: int = 0
    policy_seconds: float = 0.0
    invalid_actions: int = 0
    dropped_messages: int = 0
    crafts: Dict[str, Craft] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


def parse_events(events: Optional[dict]) -> Tuple[float, List[dict]]:
    """Returns (t_loss, event list) from an events dictionary."""
    if not events:
        return INF, []
    return float(events["t_loss"]), [dict(e) for e in events.get("events", [])]


def _piece_energy(piece: Piece, ac) -> float:
    return piece_energy_wh(piece, ac.power)


def _append_piece(pieces: List[Piece], piece: Piece) -> None:
    """Appends a piece, merging it with the previous one when the motion simply continues."""
    if pieces:
        t0, t1, p0, p1 = pieces[-1]
        n0, n1, q0, q1 = piece
        if abs(n0 - t1) < 1e-9 and dist3(p1, q0) < 1e-6:
            d1, d2 = t1 - t0, n1 - n0
            if d1 > 0 and d2 > 0 and all(abs((p1[i] - p0[i]) / d1 - (q1[i] - q0[i]) / d2) < 1e-9 for i in range(3)):
                pieces[-1] = (t0, n1, p0, q1)
                return
    pieces.append(piece)


def trial_move(craft: Craft, rate: float, t: float, dt: float = STEP_S):
    """Computes one step of motion without changing the state.

    Returns (new tau, pieces of the step, crossings), crossings being (kind, waypoint, real time)
    with kind arr (arrived), dep (departed) or end (reached the end of the route going forward,
    or the start going back).
    """
    clock = craft.clock
    a = craft.tau
    b = a + rate * dt
    forward = rate >= 0
    crossings: List[Tuple[str, int, float]] = []
    if rate == 0.0:
        p = clock.position(a)
        return a, ([(t, t + dt, p, p)] if a > clock.start else []), crossings
    stop = None
    if forward and b >= clock.end:
        b, stop = clock.end, "end"
    elif not forward and b <= clock.start:
        b, stop = clock.start, "end"
    if abs(b - a) < 1e-12:
        return a, [], ([("end", -1, t)] if stop else [])
    lo, hi = (a, b) if forward else (b, a)
    inner = clock.breakpoints(lo, hi)
    if not forward:
        inner = inner[::-1]
    taus = [a] + inner + [b]
    pieces: List[Piece] = []
    for i in range(len(taus) - 1):
        t0 = t + (taus[i] - a) / rate
        t1 = t + (taus[i + 1] - a) / rate
        p0, p1 = clock.position(taus[i]), clock.position(taus[i + 1])
        on_ground = max(taus[i], taus[i + 1]) <= clock.start + 1e-12
        if not on_ground and t1 - t0 > 1e-12:
            pieces.append((t0, t1, p0, p1))
    if forward:
        for k, x in enumerate(clock.arr):
            if a < x <= b + 1e-12:
                crossings.append(("arr", k, t + (x - a) / rate))
        for k, x in enumerate(clock.dep):
            if a < x <= b + 1e-12:
                crossings.append(("dep", k, t + (x - a) / rate))
    if stop:
        crossings.append(("end", -1, t + (b - a) / rate))
    return b, pieces, crossings


def _commit(craft: Craft, new_tau: float, pieces: List[Piece], crossings, real_t: float) -> None:
    for piece in pieces:
        craft.energy -= _piece_energy(piece, craft.ac)
        _append_piece(craft.pieces, piece)
    for kind, k, when in crossings:
        if kind == "arr":
            wp = craft.route.waypoints[k]
            if wp.action == "observe":
                craft.obs_start[k] = when
            if wp.action == "engage" and craft.ac.type == EFFECTOR:
                craft.engaged_at = when
                craft.ended, craft.end_kind = when, "engaged"
        elif kind == "dep":
            if k in craft.obs_start:
                craft.obs_done.append((k, craft.obs_start.pop(k), when))
        elif kind == "end" and craft.ended is None:
            craft.ended, craft.end_kind = when, "landed"
    craft.tau = new_tau
    craft.pos = craft.clock.position(new_tau)
    if pieces:
        t0, t1, p0, p1 = pieces[-1]
        d = max(t1 - t0, 1e-9)
        craft.vel = tuple((p1[i] - p0[i]) / d for i in range(3))
    else:
        craft.vel = (0.0, 0.0, 0.0)
    if craft.ended is None and craft.energy < -1e-6:
        craft.ended, craft.end_kind = real_t + STEP_S, "lost"
        craft.alive = False


def _rate(action: dict) -> Optional[float]:
    """Route-clock rate of an action, or None when the action is invalid."""
    if not isinstance(action, dict):
        return None
    kind = action.get("kind")
    if kind == "continue":
        return 1.0
    if kind == "hold":
        return 0.0
    if kind == "return":
        return -1.0
    if kind == "speed":
        s = action.get("scale")
        if isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s):
            return min(1.0, max(SPEED_MIN, float(s)))
    return None


def zone_active(zone: dict, t: float) -> bool:
    return t >= zone["t"] - 1e-9


def _sense(craft: Craft, scenario: Scenario, contacts, active: List[dict]) -> List[dict]:
    seen = []
    for e in active:
        if e["kind"] == "reclassify":
            c = contacts[e["contact"]]
            if hdist(craft.pos, c.pos) <= R_SENSE_M:
                seen.append(e)
        elif e["kind"] == "popup_zone":
            if hdist(craft.pos, e["center"]) - e["radius_m"] <= R_SENSE_M:
                seen.append(e)
    return seen


def _crafts(scenario: Scenario, plan: dict) -> Dict[str, Craft]:
    routes, errors = parse_plan(plan)
    if routes is None or errors:
        raise ValueError("the plan is not well-formed: " + "; ".join(errors))
    aircraft = scenario.aircraft_by_id()
    out = {}
    for aid in sorted(routes):
        ac = aircraft[aid]
        clock = RouteClock(routes[aid])
        c = Craft(aid, ac, routes[aid], clock, tau=0.0, energy=ac.usable_wh, pos=clock.pos[0])
        out[aid] = c
    return out


def simulate(scenario: Scenario, plan: dict, events: Optional[dict], policy_factory: Optional[Callable] = None,
             *, oracle: bool = False, setting: Tuple[float, float] = (1000.0, 200.0), run_seed: int = 0,
             max_seconds: Optional[float] = None, trace: Optional[dict] = None) -> RunResult:
    """Flies a plan with a policy per aircraft after the cut and reports what happened.

    Args:
        scenario: The scenario.
        plan: A valid plan (dictionary).
        events: Events dictionary (`t_loss` and `events`), or None for no cut.
        policy_factory: Called as `policy_factory(scenario, plan, aircraft_id)`; the policy it returns has
            `step(obs) -> (action, message or None)`. Ignored when `oracle` is true.
        oracle: Use the full-information reference instead of a policy.
        setting: (R_max in m, C in bytes per second per receiver).
        run_seed: Seed of the random message losses.
        max_seconds: Wall-clock cap for the whole run; exceeding it fails the run.
        trace: If a dictionary is given, it is filled for the viewer: `rates` (time, {aircraft: route-clock
            rate}) after the cut, `sent` (time, sender, payload, bytes) and `links` (time, sender, receiver,
            delivered, bytes). It changes nothing in the run.

    Returns:
        The run result: failures, points served, messages and per-run statistics.
    """
    from .oracle import oracle_actions  # local import: the oracle needs this module

    t_loss, evs = parse_events(events)
    contacts = scenario.contact_by_id()
    crafts = _crafts(scenario, plan)
    rng = random.Random(f"loss:{run_seed}")
    r_max, cap = setting
    failed: List[str] = []
    stats = dict(calls=0, secs=0.0, invalid=0, dropped=0, msgs=0)
    inbox: Dict[str, list] = {a: [] for a in crafts}
    heard: Dict[str, dict] = {a: {} for a in crafts}
    started = time.monotonic()
    if trace is not None:
        trace.update(rates=[], sent=[], links=[])
    if policy_factory is not None and not oracle and t_loss < INF:
        try:
            for aid, c in crafts.items():
                c.policy = policy_factory(scenario, plan, aid)
        except Exception as exc:  # a policy that cannot even be built fails the run
            failed.append(f"policy error at start: {type(exc).__name__}: {exc}")
    t = 0.0
    horizon = scenario.horizon_s
    removed_at: Dict[str, float] = {}
    while t < horizon - 1e-9 and not failed:
        active_events = [e for e in evs if e["t"] <= t + 1e-9]
        for e in active_events:
            if e["kind"] == "failure":
                c = crafts.get(e["aircraft"])
                if c is not None and c.active:
                    c.alive, c.ended, c.end_kind = False, t, "failed"
        airborne = [c for c in crafts.values() if c.active]
        if not airborne:
            break
        rates: Dict[str, float] = {}
        outgoing: List[Tuple[Craft, Any, int]] = []
        if t < t_loss - 1e-9:
            rates = {c.id: 1.0 for c in airborne}
        elif oracle:
            rates = oracle_actions(scenario, crafts, active_events, t)
        else:
            for c in airborne:
                sensed = _sense(c, scenario, contacts, active_events)
                obs = {"t": t, "t_loss": t_loss, "pos": c.pos, "vel": c.vel, "tau": c.tau, "mode": c.mode,
                       "next_wp": c.clock.next_waypoint(c.tau), "energy_left_wh": c.energy,
                       "own_observed": sorted({c.route.waypoints[k].target for k, _, _ in c.obs_done}),
                       "sensed": sensed, "inbox": inbox[c.id], "last_heard": heard[c.id]}
                begin = time.perf_counter()
                try:
                    action, message = c.policy.step(obs)
                except Exception as exc:
                    failed.append(f"policy error ({c.id}): {type(exc).__name__}: {exc}")
                    break
                stats["secs"] += time.perf_counter() - begin
                stats["calls"] += 1
                rate = _rate(action)
                if rate is None:
                    rate, stats["invalid"] = 0.0, stats["invalid"] + 1
                rates[c.id] = rate
                if rate < 0 and c.mode != "return":
                    c.mode = "return"
                elif rate > 0 and c.mode == "return":
                    c.mode = "route"
                if message is not None:
                    try:
                        size = len(json.dumps(message, separators=(",", ":")).encode())
                    except (TypeError, ValueError):
                        size = MAX_MESSAGE_BYTES + 1
                    if size <= MAX_MESSAGE_BYTES:
                        outgoing.append((c, message, size))
                        stats["msgs"] += 1
                    else:
                        stats["dropped"] += 1
            inbox = {a: [] for a in crafts}
            if failed:
                break
            _deliver(crafts, outgoing, inbox, heard, t, r_max, cap, rng, trace)
        if trace is not None and t >= t_loss - 1e-9:
            trace["rates"].append((t, dict(rates)))
        if max_seconds is not None and time.monotonic() - started > max_seconds:
            failed.append(f"run exceeded the wall-clock cap of {max_seconds:g} s")
            break
        for c in airborne:
            rate = rates.get(c.id, 1.0)
            new_tau, pieces, crossings = trial_move(c, rate, t)
            _commit(c, new_tau, pieces, crossings, t)
        t += STEP_S
    result = _assess(scenario, plan, crafts, evs, failed, stats, t_loss, horizon)
    return result


def _deliver(crafts, outgoing, inbox, heard, t, r_max, cap, rng, trace=None) -> None:
    """Delivers this step's messages for the next step, with range and capacity effects."""
    if not outgoing:
        return
    receivers = [c for c in crafts.values() if c.active]
    offered: Dict[str, float] = {}
    for sender, _, size in outgoing:
        for r in receivers:
            if r is not sender and dist3(sender.pos, r.pos) <= r_max:
                offered[r.id] = offered.get(r.id, 0.0) + size
    for sender, payload, size in outgoing:
        if trace is not None:
            trace["sent"].append((t, sender.id, payload, size))
        for r in receivers:
            if r is sender:
                continue
            d = dist3(sender.pos, r.pos)
            if d > r_max:
                continue
            p_range = 1.0 if d <= r_max / 2.0 else 2.0 * (1.0 - d / r_max)
            p_cap = min(1.0, cap / offered[r.id]) if offered.get(r.id, 0.0) > 0 else 1.0
            delivered = rng.random() < (1.0 - P_LOSS) * p_range * p_cap
            if trace is not None:
                trace["links"].append((t, sender.id, r.id, int(delivered), size))
            if delivered:
                msg = {"from": sender.id, "sent_t": t, "payload": payload}
                inbox[r.id].append(msg)
                heard[r.id][sender.id] = {"t": t, "payload": payload}


def _assess(scenario, plan, crafts, evs, failed, stats, t_loss, horizon) -> RunResult:
    """Checks the realised trajectories and counts the points served."""
    rules = scenario.rules
    contacts = scenario.contact_by_id()
    reclass = {e["contact"]: e["t"] for e in evs if e["kind"] == "reclassify"}
    popups = [e for e in evs if e["kind"] == "popup_zone"]
    # separation on the realised pieces
    items = []
    for aid, c in crafts.items():
        if c.pieces:
            last = c.route.waypoints[-1]
            tgt = last.target if (last.action == "engage" and c.ac.type == EFFECTOR) else None   # as in the plan check
            items.append((aid, c.pieces, c.pieces[0][0], c.pieces[-1][1], tgt, _box(c.pieces)))
    pad = rules.d_sep_m + 1.0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if min(a[3], b[3]) - max(a[2], b[2]) <= 1e-12 or _boxes_apart(a[5], b[5], pad):
                continue
            v = separation_violation(rules, contacts, a[:5], b[:5])
            if v is not None:
                failed.append(str(v))
    # zones
    cylinders = [(z.center, z.radius_m, z.top_m, f"zone {z.id}", 0.0) for z in scenario.zones]
    for c in scenario.contacts:
        if c.cls in ("friendly", "civilian"):
            cylinders.append((c.pos[:2], rules.protect_radius_m, INF, f"protected area of {c.id}", 0.0))
    for e in popups:
        cylinders.append((tuple(e["center"]), e["radius_m"], e["top_m"], "a pop-up zone", e["t"]))
    for aid, c in crafts.items():
        for (t0, t1, p0, p1) in c.pieces:
            for center, radius, top, label, since in cylinders:
                if t1 <= since + 1e-9:
                    continue
                q0 = p0
                if t0 < since:
                    f = (since - t0) / (t1 - t0)
                    q0 = tuple(p0[k] + f * (p1[k] - p0[k]) for k in range(3))
                if segment_enters_cylinder(q0, p1, center, radius, top):
                    failed.append(f"R6 (exclusion) [{aid}]: flew into {label} around t = {t0:.0f} s")
                    break
    # engagements, observations
    engagements: Dict[str, List[Tuple[str, float]]] = {}
    subtypes: Dict[str, Dict[str, int]] = {}
    for aid, c in crafts.items():
        if c.engaged_at is not None:
            tgt = c.route.waypoints[-1].target
            engagements.setdefault(tgt, []).append((aid, c.engaged_at))
            sub = c.ac.subtype or "?"
            subtypes.setdefault(tgt, {})[sub] = subtypes.get(tgt, {}).get(sub, 0) + 1
    observations: Dict[str, List[Tuple[float, float]]] = {}
    for aid, c in crafts.items():
        if c.ac.type != SCOUT:
            continue
        for k, start, end in c.obs_done:
            wp = c.route.waypoints[k]
            cc = contacts.get(wp.target)
            if cc is not None and valid_observation(wp, cc, scenario) and cc.cls in (HOSTILE, UNKNOWN):
                observations.setdefault(cc.id, []).append((start, end))
    for tgt, lst in engagements.items():
        for aid, te in lst:
            if tgt in reclass and te >= reclass[tgt] - 1e-9:
                failed.append(f"engaged {tgt} at t = {te:.0f} s after it was reclassified [{aid}]")
            elif not any(end <= te - rules.confirm_margin_s + EPS for _, end in observations.get(tgt, [])):
                failed.append(f"R4 (confirm before engage) [{aid} {tgt}]: engaged at t = {te:.0f} s with no completed observation")
    # points
    served: List[str] = []
    points = 0.0
    for c in scenario.contacts:
        if c.cls == HOSTILE and c.id in engagements:
            want = {k: v for k, v in c.needs.items() if v > 0}
            times = [te for _, te in engagements[c.id]]
            if subtypes[c.id] == want and max(times) - min(times) <= rules.sync_window_s + EPS \
                    and c.window and min(times) >= c.window[0] - EPS and max(times) <= c.window[1] + EPS:
                served.append(c.id)
                points += c.points
        elif c.cls == UNKNOWN and c.window and any(
                s >= c.window[0] - EPS and e <= c.window[1] + EPS for s, e in observations.get(c.id, [])):
            served.append(c.id)
            points += c.points
    per_min = 60.0 * stats["msgs"] / stats["calls"] if stats["calls"] else 0.0   # per aircraft-minute flown after the cut
    return RunResult(failed=failed, served=served, points=points, messages=stats["msgs"],
                     messages_per_aircraft_per_min=per_min,
                     lost=[a for a, c in crafts.items() if c.end_kind == "lost"], engagements=engagements,
                     policy_calls=stats["calls"], policy_seconds=stats["secs"], invalid_actions=stats["invalid"],
                     dropped_messages=stats["dropped"], crafts=crafts)


def _box(pieces):
    xs = [p[2][0] for p in pieces] + [pieces[-1][3][0]]
    ys = [p[2][1] for p in pieces] + [pieces[-1][3][1]]
    zs = [p[2][2] for p in pieces] + [pieces[-1][3][2]]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _boxes_apart(a, b, pad) -> bool:
    return a[0] > b[1] + pad or b[0] > a[1] + pad or a[2] > b[3] + pad or b[2] > a[3] + pad \
        or a[4] > b[5] + pad or b[4] > a[5] + pad
