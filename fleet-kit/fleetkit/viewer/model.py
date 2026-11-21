"""The view model: everything the HTML viewer shows, computed by the kit and embedded as JSON.

The viewer re-implements no rule. Verdicts come from the validator and the scorer, trajectories from the
plan or from the link-loss simulator, and the page only draws them.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..geometry import position_at
from ..energy import piece_energy_wh
from ..model import EFFECTOR, HOSTILE, SCOUT, UNKNOWN, Scenario, parse_plan
from ..scorer import evaluate
from ..validator import Violation, route_pieces, valid_observation, validate

MAX_SAMPLES = 60000          # aircraft x time samples before the step is widened
VERSION = 1


SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.:+\-]{0,59}$")


def check_safe_text(scenario: Scenario, events: Optional[dict] = None) -> None:
    """Refuses ids, classes and levels the page could mistake for markup (a hand-made scenario or events file).

    The page writes these into HTML; generated scenarios always pass. Everything else shown is escaped.

    Raises:
        ValueError: when a field holds characters other than letters, digits, space and `_ . : + -`.
    """
    fields = [("level", scenario.level)]
    fields += [("zone id", z.id) for z in scenario.zones]
    fields += [("contact id", c.id) for c in scenario.contacts] + [("contact class", c.cls) for c in scenario.contacts]
    fields += [("aircraft id", a.id) for a in scenario.aircraft]
    fields += [("aircraft type", a.type) for a in scenario.aircraft] + [("aircraft subtype", a.subtype) for a in scenario.aircraft if a.subtype]
    for e in (events or {}).get("events", []) or []:
        fields += [(f"event {key}", e[key]) for key in ("kind", "contact", "aircraft", "zone", "to") if isinstance(e, dict) and e.get(key) is not None]
    for what, value in fields:
        if not isinstance(value, str) or not SAFE_TEXT.match(value):
            raise ValueError(f"the viewer cannot show this file: {what} {str(value)[:40]!r} has characters other than letters, digits, space and _ . : + -")


def _r1(v: float) -> float:
    return round(float(v), 1)


def _m(v: float) -> int:
    """Whole metres: enough for a map, and it keeps the page small."""
    return int(round(float(v)))


def violation_pair(text: str) -> Optional[List[str]]:
    """The two aircraft of a separation message, if it names them."""
    m = re.search(r"(\w+) and (\w+) come within", text)
    return [m.group(1), m.group(2)] if m else None


def violation_time(v: Violation, routes) -> Optional[float]:
    """Best-effort time (s) of a violation: from its message, or from the leg or waypoint it names."""
    m = re.search(r"t = (\d+(?:\.\d+)?)", v.message)
    if m:
        return float(m.group(1))
    route = routes.get(v.aircraft) if routes and v.aircraft else None
    if route is not None:
        m = re.search(r"leg (\d+)", v.message)
        if m and int(m.group(1)) - 1 < len(route.waypoints):
            return float(route.waypoints[int(m.group(1)) - 1].depart)
        m = re.search(r"waypoint (\d+)", v.message)
        if m and int(m.group(1)) < len(route.waypoints):
            return float(route.waypoints[int(m.group(1))].t)
    return None


def _sample(pieces: Sequence[tuple], t: float, idx: List[int]) -> Optional[tuple]:
    """Position at time t on a list of pieces sorted in time, or None outside them. `idx` is a moving pointer."""
    while idx[0] < len(pieces) - 1 and pieces[idx[0]][1] < t - 1e-9:
        idx[0] += 1
    if not pieces:
        return None
    piece = pieces[idx[0]]
    if t < piece[0] - 1e-9 or t > piece[1] + 1e-9:
        return None
    return position_at(piece, min(max(t, piece[0]), piece[1]))


def _track(pieces, home, ac, times: Sequence[float], status_at, kind_end, end_t, last_pos) -> dict:
    """Samples one aircraft: positions, status characters and remaining energy (Wh) at every sample time."""
    idx = [0]
    pos: List[Optional[list]] = []
    stat: List[str] = []
    energy: List[float] = []
    cum_end = []
    total = 0.0
    for p in pieces:
        total += piece_energy_wh(p, ac.power)
        cum_end.append(total)
    first = pieces[0][0] if pieces else None
    j = 0
    for t in times:
        p = _sample(pieces, t, idx)
        used = 0.0
        if pieces:
            while j < len(pieces) - 1 and pieces[j][1] < t - 1e-9:
                j += 1
            before = cum_end[j - 1] if j > 0 else 0.0
            piece = pieces[j]
            if t >= piece[1] - 1e-9:
                used = cum_end[j]
            elif t > piece[0]:
                span = piece[1] - piece[0]
                used = before + (cum_end[j] - before) * ((t - piece[0]) / span if span > 0 else 1.0)
            else:
                used = before
        energy.append(_m(max(0.0, ac.usable_wh - used)))
        if p is not None:
            pos.append([_m(p[0]), _m(p[1]), _m(p[2])])
            stat.append(status_at(t, p))
        elif first is None or t < first - 1e-9:
            pos.append([_m(home[0]), _m(home[1]), _m(home[2])])
            stat.append("g")
        else:
            k = kind_end
            if k == "engaged":
                pos.append(None)
                stat.append("x")
            elif k in ("lost", "failed"):
                pos.append([_m(last_pos[0]), _m(last_pos[1]), _m(last_pos[2])] if last_pos else None)
                stat.append("L" if k == "lost" else "F")
            else:
                pos.append([_m(home[0]), _m(home[1]), _m(home[2])])
                stat.append("l")
    return {"p": pos, "s": "".join(stat), "e": energy}


def build_model(scenario: Scenario, plan: Optional[dict] = None, *, events: Optional[dict] = None,
                run: Any = None, trace: Optional[dict] = None, oracle_points: Optional[float] = None,
                setting: Tuple[float, float] = (1000.0, 200.0), layers: Optional[List[dict]] = None,
                title: Optional[str] = None) -> Dict[str, Any]:
    """Builds the JSON-able view model of a scenario, optionally with a plan and a link-loss run.

    Args:
        scenario: The scenario.
        plan: A plan dictionary, or None to show the scenario alone.
        events: The link-loss events dictionary (`t_loss`, `events`), when a run is shown.
        run: The `RunResult` of `fleetkit.linkloss.simulate` for the replay; its trajectories are shown instead
            of the plan's.
        trace: The trace filled by `simulate(..., trace=...)` (actions and message links).
        oracle_points: Points of the oracle on these events (for the retention shown).
        setting: The communication setting of the run (range, capacity).
        layers: Annotation layers (see `fleetkit.viewer.Viewer.layer`).
        title: Page title.

    Returns:
        A dictionary the page embeds.
    """
    check_safe_text(scenario, events)
    rules = scenario.rules
    xs = [c.pos[0] for c in scenario.contacts] + [a.home[0] for a in scenario.aircraft]
    ys = [c.pos[1] for c in scenario.contacts] + [a.home[1] for a in scenario.aircraft]
    for z in scenario.zones:
        xs += [z.center[0] - z.radius_m, z.center[0] + z.radius_m]
        ys += [z.center[1] - z.radius_m, z.center[1] + z.radius_m]
    model: Dict[str, Any] = {
        "version": VERSION,
        "meta": {"title": title or f"{scenario.level} seed {scenario.seed}", "level": scenario.level,
                 "seed": scenario.seed, "horizon": scenario.horizon_s},
        "world": {
            "bounds": [min(xs), max(xs), min(ys), max(ys)],
            "zones": [{"id": z.id, "x": z.center[0], "y": z.center[1], "r": z.radius_m, "top": z.top_m} for z in scenario.zones],
            "contacts": [{"id": c.id, "cls": c.cls, "x": c.pos[0], "y": c.pos[1], "points": c.points,
                          "needs": c.needs, "window": list(c.window) if c.window else None} for c in scenario.contacts],
            "rules": {"R_obs": rules.R_obs_m, "R_eng": rules.R_eng_m, "protect": rules.protect_radius_m,
                      "collateral": rules.collateral_radius_m, "d_sep": rules.d_sep_m, "z_min": rules.z_min_m,
                      "z_max": rules.z_max_m, "dwell": rules.obs_dwell_s}},
        "aircraft": [{"id": a.id, "type": a.type, "sub": a.subtype, "home": list(a.home), "wh": round(a.usable_wh, 1)}
                     for a in scenario.aircraft],
        "layers": layers or [], "plan": None, "tracks": {}, "marks": [], "served": {}, "link": None,
    }
    if plan is None:
        model["time"] = {"t0": 0.0, "t1": scenario.horizon_s, "dt": 1.0}
        return model

    routes, _ = parse_plan(plan)
    routes = routes or {}
    violations = validate(scenario, plan)
    result = evaluate(scenario, plan)
    aircraft = scenario.aircraft_by_id()
    contacts = scenario.contact_by_id()

    # which trajectories: the realised run, or the plan itself
    if run is not None:
        crafts = run.crafts
        piece_map = {aid: list(c.pieces) for aid, c in crafts.items()}
        t_end = max([p[-1][1] for p in piece_map.values() if p] + [events["t_loss"] if events else 0.0]) + 5.0
        end_kind = {aid: c.end_kind for aid, c in crafts.items()}
        last_pos = {aid: (c.pieces[-1][3] if c.pieces else None) for aid, c in crafts.items()}
    else:
        piece_map = {aid: route_pieces(r) for aid, r in routes.items()}
        t_end = max([p[-1][1] for p in piece_map.values() if p] + [0.0]) + 5.0
        end_kind = {aid: ("engaged" if (aircraft[aid].type == EFFECTOR and r.waypoints[-1].action == "engage") else "landed")
                    for aid, r in routes.items() if aid in aircraft}
        last_pos = {aid: None for aid in routes}
    t_end = min(t_end, scenario.horizon_s)
    n_tracks = max(1, len(scenario.aircraft))
    dt = 1.0
    while n_tracks * (t_end / dt) > MAX_SAMPLES:
        dt *= 2.0
    times = [k * dt for k in range(int(math.ceil(t_end / dt)) + 1)]

    # observation dwell intervals, used for the "observing" status and for the marks
    obs_intervals: Dict[str, List[Tuple[float, float, str]]] = {}
    marks: List[dict] = []
    served_at: Dict[str, float] = {}
    if run is not None:
        for aid, c in crafts.items():
            for k, start, end in c.obs_done:
                wp = c.route.waypoints[k]
                ok = valid_observation(wp, contacts[wp.target], scenario) if wp.target in contacts else False
                obs_intervals.setdefault(aid, []).append((start, end, wp.target))
                marks.append({"kind": "observe", "aid": aid, "contact": wp.target, "t0": _r1(start), "t1": _r1(end), "ok": ok})
            if c.engaged_at is not None:
                marks.append({"kind": "engage", "aid": aid, "contact": c.route.waypoints[-1].target, "t": _r1(c.engaged_at)})
    else:
        for aid, r in routes.items():
            for wp in r.waypoints:
                if wp.action == "observe" and aid in aircraft and aircraft[aid].type == SCOUT and wp.target in contacts:
                    ok = valid_observation(wp, contacts[wp.target], scenario)
                    obs_intervals.setdefault(aid, []).append((wp.t, wp.depart, wp.target))
                    marks.append({"kind": "observe", "aid": aid, "contact": wp.target, "t0": _r1(wp.t), "t1": _r1(wp.depart), "ok": ok})
                elif wp.action == "engage" and wp.target in contacts:
                    marks.append({"kind": "engage", "aid": aid, "contact": wp.target, "t": _r1(wp.t)})
    served = set(run.served if run is not None else result.served)
    for m in marks:
        if m["contact"] in served:
            if m["kind"] == "engage":
                served_at[m["contact"]] = max(served_at.get(m["contact"], 0.0), m["t"])
            elif contacts[m["contact"]].cls == UNKNOWN and m.get("ok"):
                served_at[m["contact"]] = min(served_at.get(m["contact"], 1e9), m["t1"])

    rates_at: Dict[str, List[Tuple[float, float]]] = {}
    if trace is not None:
        for t, rates in trace.get("rates", []):
            for aid, r in rates.items():
                rates_at.setdefault(aid, []).append((t, r))
    for aid, pieces in piece_map.items():
        if aid not in aircraft:
            continue
        ivs = obs_intervals.get(aid, [])
        rl = {int(round(t)): r for t, r in rates_at.get(aid, [])}

        def status_at(t, p, ivs=ivs, rl=rl):
            if p[2] <= 0.5:
                return "g"                       # standing on the ground (before takeoff)
            if any(a - 1e-9 <= t <= b + 1e-9 for a, b, _ in ivs):
                return "o"
            r = rl.get(int(t))
            if r is None:
                return "f"
            return "h" if r == 0 else ("r" if r < 0 else "f")
        model["tracks"][aid] = _track(pieces, aircraft[aid].home, aircraft[aid], times, status_at,
                                      end_kind.get(aid, "landed"), t_end, last_pos.get(aid))
    for ac in scenario.aircraft:
        if ac.id not in model["tracks"]:
            model["tracks"][ac.id] = {"p": [list(map(_m, ac.home))] * len(times), "s": "g" * len(times),
                                      "e": [_m(ac.usable_wh)] * len(times)}
    model["time"] = {"t0": 0.0, "t1": times[-1], "dt": dt}
    model["marks"] = marks
    model["served"] = {c: _r1(t) for c, t in served_at.items()}
    pts = run.points if run is not None else result.points
    model["plan"] = {
        "valid": result.valid if run is None else not run.failed,
        "score": _r1(result.score) if run is None else None,
        "points": _r1(pts), "energy": _r1(result.energy_wh) if run is None else None,
        "effectors": result.effectors_used if run is None else None, "served": sorted(served),
        "score_parts": None if run is not None or not result.valid else
        {"points": _r1(result.points), "energy_cost": _r1(rules.lambda_e * result.energy_wh),
         "effector_cost": _r1(rules.c_eff * result.effectors_used)},
        "violations": ([{"rule": v.rule, "msg": str(v), "aircraft": v.aircraft, "contact": v.contact,
                         "pair": violation_pair(v.message), "t": violation_time(v, routes)} for v in violations] if run is None else
                       [{"rule": (f.split(" ", 1)[0] if f[:1] == "R" else "run"), "msg": f, "aircraft": None, "contact": None,
                         "pair": violation_pair(f),
                         "t": (float(re.search(r"t = (\d+(?:\.\d+)?)", f).group(1)) if re.search(r"t = (\d+(?:\.\d+)?)", f) else None)}
                        for f in run.failed]),
    }
    if run is not None and events:
        links = trace.get("links", []) if trace else []
        sent = trace.get("sent", []) if trace else []
        retention = None
        if oracle_points:
            retention = 0.0 if run.failed else min(1.0, run.points / oracle_points)
        model["link"] = {
            "t_loss": events["t_loss"], "events": events.get("events", []), "setting": list(setting),
            "failed": list(run.failed), "points": _r1(run.points), "oracle_points": oracle_points,
            "retention": None if retention is None else round(retention, 3),
            "messages": run.messages, "per_min": round(run.messages_per_aircraft_per_min, 1),
            "lost": list(run.lost),
            "links": [[_r1(t), a, b, ok] for t, a, b, ok, _ in links],
            "sent": [[_r1(t), a, json_str(p), size] for t, a, p, size in sent],
        }
    return model


def json_str(payload: Any) -> str:
    import json
    return json.dumps(payload, separators=(",", ":"))
