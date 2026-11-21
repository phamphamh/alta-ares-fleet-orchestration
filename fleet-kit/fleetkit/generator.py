"""Seeded scenario generator for the four levels. Every number is synthetic."""
from __future__ import annotations

import math
import random
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from .model import Rules, Scenario

LEVELS: Dict[str, dict] = {
    "L1": dict(scouts=2, light=2, heavy=1, hostile=3, unknown=1, friendly=0, civilian=1,
               zones=1, area=3000.0, horizon=600.0, clusters=(1, 2), sigma=0.06, window=(0.25, 0.5)),
    "L2": dict(scouts=3, light=6, heavy=3, hostile=6, unknown=3, friendly=1, civilian=1,
               zones=2, area=3500.0, horizon=900.0, clusters=(2, 3), sigma=0.07, window=(0.2, 0.4)),
    "L3": dict(scouts=5, light=16, heavy=9, hostile=14, unknown=6, friendly=3, civilian=2,
               zones=4, area=4500.0, horizon=900.0, clusters=(3, 4), sigma=0.07, window=(0.2, 0.4)),
    "L4": dict(scouts=15, light=50, heavy=35, hostile=50, unknown=20, friendly=12, civilian=8,
               zones=8, area=7000.0, horizon=900.0, clusters=(4, 6), sigma=0.07, window=(0.2, 0.4)),
}
MIN_SPACING_M = 60.0


def _r(x: float, digits: int = 1) -> float:
    return round(x, digits)


def _aircraft(level: dict, rng: random.Random) -> List[dict]:
    specs = []
    for k in range(level["scouts"]):
        specs.append(("scout", None, f"S{k + 1:02d}"))
    for k in range(level["light"]):
        specs.append(("effector", "light", f"L{k + 1:02d}"))
    for k in range(level["heavy"]):
        specs.append(("effector", "heavy", f"H{k + 1:02d}"))
    n = len(specs)
    cols = math.ceil(math.sqrt(n))
    spacing = min(20.0, 100.0 / max(cols - 1, 1))
    origin = (150.0, 150.0)
    pads = [(origin[0] + (i % cols) * spacing, origin[1] + (i // cols) * spacing) for i in range(n)]
    rng.shuffle(pads)
    out = []
    for (kind, sub, ident), pad in zip(specs, pads):
        if kind == "scout":
            vh, vup, vdn = rng.uniform(15, 22), rng.uniform(5, 8), rng.uniform(5, 8)
            cap, p0, kv, ec = rng.uniform(35, 50), rng.uniform(60, 100), rng.uniform(0.2, 0.3), rng.uniform(0.015, 0.03)
        elif sub == "light":
            vh, vup, vdn = rng.uniform(28, 35), rng.uniform(8, 15), rng.uniform(15, 20)
            cap, p0, kv, ec = rng.uniform(40, 55), rng.uniform(80, 120), rng.uniform(0.06, 0.1), rng.uniform(0.01, 0.02)
        else:
            vh, vup, vdn = rng.uniform(18, 25), rng.uniform(5, 10), rng.uniform(10, 15)
            cap, p0, kv, ec = rng.uniform(55, 75), rng.uniform(120, 180), rng.uniform(0.1, 0.2), rng.uniform(0.03, 0.05)
        a = {"id": ident, "type": kind, "home": [_r(pad[0]), _r(pad[1]), 0.0],
             "v_h_mps": _r(vh), "v_up_mps": _r(vup), "v_down_mps": _r(vdn),
             "capacity_wh": _r(cap), "battery_pct": float(rng.randint(*level.get("battery", (70, 100)))),
             "power": {"p0_w": _r(p0), "k_v": _r(kv, 3), "e_climb_wh_per_m": _r(ec, 3)}}
        if sub:
            a["subtype"] = sub
        out.append(a)
    return out


def _far_enough(p: Tuple[float, float], placed: List[Tuple[float, float]], gap: float) -> bool:
    return all(math.hypot(p[0] - q[0], p[1] - q[1]) >= gap for q in placed)


def _place(rng: random.Random, area: float, home: Tuple[float, float], placed, min_home: float,
           around: Optional[Tuple[float, float, float]] = None) -> Optional[Tuple[float, float]]:
    margin = 300.0
    for _ in range(400):
        if around is None:
            p = (rng.uniform(margin, area - margin), rng.uniform(margin, area - margin))
        else:
            cx, cy, sigma = around
            p = (min(max(rng.gauss(cx, sigma), margin), area - margin),
                 min(max(rng.gauss(cy, sigma), margin), area - margin))
        if math.hypot(p[0] - home[0], p[1] - home[1]) >= min_home and _far_enough(p, placed, MIN_SPACING_M):
            return p
    return None


def _needs(level_name: str, rng: random.Random, n_light: int, n_heavy: int) -> Dict[str, int]:
    weights = [0.5, 0.35, 0.15] if level_name in ("L1", "L2") else [0.3, 0.3, 0.25, 0.15]
    total = rng.choices(range(1, len(weights) + 1), weights=weights)[0]
    heavy = rng.randint(1, min(2, total)) if rng.random() < 0.4 else 0
    heavy = min(heavy, n_heavy)
    light = min(total - heavy, n_light)
    if light + heavy == 0:
        light = 1
    needs = {}
    if light:
        needs["light"] = light
    if heavy:
        needs["heavy"] = heavy
    return needs


def _generate_once(level_name: str, seed: int, rng: random.Random) -> dict:
    level = LEVELS[level_name]
    area, horizon = level["area"], level["horizon"]
    aircraft = _aircraft(level, rng)
    home = (150.0, 150.0)
    placed: List[Tuple[float, float]] = []
    contacts: List[dict] = []

    def window() -> List[float]:
        lo = rng.uniform(0.0, 0.55 * horizon)
        hi = min(horizon, lo + rng.uniform(*level["window"]) * horizon)
        return [_r(lo), _r(hi)]

    n_h = level["hostile"]
    k_clusters = min(rng.randint(*level["clusters"]), n_h)
    centers = []
    for _ in range(k_clusters):
        c = _place(rng, area, home, centers, 0.35 * area)
        centers.append(c or (0.7 * area, 0.7 * area))
    hostile_pos = []
    for i in range(n_h):
        cx, cy = centers[i % k_clusters]
        p = _place(rng, area, home, placed, 0.3 * area, around=(cx, cy, level["sigma"] * area)) \
            or _place(rng, area, home, placed, 0.3 * area)
        placed.append(p)
        hostile_pos.append(p)
        ppn = level.get("points_per_need")
        if ppn is None:
            points = rng.randint(40, 100)
            needs = _needs(level_name, rng, level["light"], level["heavy"])
        else:  # a contact that needs more effectors is worth more, but less per effector
            needs = _needs(level_name, rng, level["light"], level["heavy"])
            points = rng.randint(40, 70) + int(ppn) * (sum(needs.values()) - 1)
        contacts.append({"id": f"C{len(contacts) + 1:02d}", "class": "hostile", "pos": [_r(p[0]), _r(p[1]), 0.0],
                         "points": points, "engage_needs": needs, "window_s": window()})
    for _ in range(level["unknown"]):
        p = _place(rng, area, home, placed, 0.2 * area)
        placed.append(p)
        contacts.append({"id": f"C{len(contacts) + 1:02d}", "class": "unknown", "pos": [_r(p[0]), _r(p[1]), 0.0],
                         "points": rng.randint(10, 30), "window_s": window()})
    for cls in ["friendly"] * level["friendly"] + ["civilian"] * level["civilian"]:
        p = None
        if hostile_pos and rng.random() < 0.4:
            hx, hy = rng.choice(hostile_pos)
            for _ in range(60):
                ang, dist = rng.uniform(0, 2 * math.pi), rng.uniform(110.0, 190.0)
                q = (hx + dist * math.cos(ang), hy + dist * math.sin(ang))
                if _far_enough(q, placed, MIN_SPACING_M) and 300 <= q[0] <= area - 300 and 300 <= q[1] <= area - 300:
                    p = q
                    break
        if p is None:
            for _ in range(300):
                q = _place(rng, area, home, placed, 0.15 * area)
                if q is not None and _far_enough(q, hostile_pos, 260.0):
                    p = q
                    break
        if p is None:
            p = _place(rng, area, home, placed, 0.15 * area) or (0.5 * area, 0.5 * area)
        placed.append(p)
        contacts.append({"id": f"C{len(contacts) + 1:02d}", "class": cls, "pos": [_r(p[0]), _r(p[1]), 0.0],
                         "window_s": None})

    zones: List[dict] = []
    contact_xy = [(c["pos"][0], c["pos"][1]) for c in contacts]

    def zone_ok(cx: float, cy: float, r: float) -> bool:
        if not (0.05 * area <= cx <= 0.95 * area and 0.05 * area <= cy <= 0.95 * area):
            return False
        if math.hypot(cx - home[0], cy - home[1]) < 400.0 + r:
            return False
        return all(math.hypot(cx - x, cy - y) >= r + 120.0 for x, y in contact_xy)

    def add_zone(cx: float, cy: float, r: float) -> None:
        zones.append({"id": f"Z{len(zones) + 1:02d}", "center": [_r(cx), _r(cy)], "radius_m": _r(r, 0),
                      "top_m": float(rng.randint(40, 120))})

    if level["zones"] >= 2 and hostile_pos and rng.random() < 0.7:
        tx, ty = centers[0]
        mx, my = 0.5 * (home[0] + tx), 0.5 * (home[1] + ty)
        ux, uy = tx - home[0], ty - home[1]
        n = math.hypot(ux, uy) or 1.0
        nx, ny = -uy / n, ux / n
        gap, r1, r2 = rng.uniform(150, 300), rng.uniform(150, 300), rng.uniform(150, 300)
        a = (mx + nx * (gap / 2 + r1), my + ny * (gap / 2 + r1))
        b = (mx - nx * (gap / 2 + r2), my - ny * (gap / 2 + r2))
        if zone_ok(a[0], a[1], r1) and zone_ok(b[0], b[1], r2):
            add_zone(a[0], a[1], r1)
            add_zone(b[0], b[1], r2)
    tries = 0
    while len(zones) < level["zones"] and tries < 400:
        tries += 1
        r = rng.uniform(150, 400)
        cx, cy = rng.uniform(0.1 * area, 0.9 * area), rng.uniform(0.1 * area, 0.9 * area)
        if zone_ok(cx, cy, r) and all(math.hypot(cx - z["center"][0], cy - z["center"][1]) >= r + z["radius_m"] + 50.0
                                      for z in zones):
            add_zone(cx, cy, r)

    return {"version": "1", "seed": seed, "level": level_name, "horizon_s": horizon,
            "aircraft": aircraft, "contacts": contacts, "zones": zones,
            "rules": asdict(Rules()), "events": []}


def generate(level: str, seed: int, ensure_feasible: bool = True) -> dict:
    """Generates a scenario.

    Args:
        level: One of L1, L2, L3, L4.
        seed: The seed; the same (level, seed) always gives the same scenario.
        ensure_feasible: If true, the scenario is regenerated (deterministically) until the
            greedy planner finds a valid plan with a positive score on its richest contacts.

    Returns:
        The scenario as a JSON-ready dictionary.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; choose from {', '.join(LEVELS)}")
    for attempt in range(40):
        rng = random.Random(f"fleetkit-{level}-{seed}-{attempt}")
        scenario = _generate_once(level, seed, rng)
        if not ensure_feasible:
            return scenario
        from .baseline import greedy_plan
        from .scorer import evaluate
        parsed = Scenario.from_dict(scenario)
        plan = greedy_plan(parsed, max_contacts=3)
        result = evaluate(parsed, plan)
        if result.valid and result.score > 0.0:
            return scenario
    raise RuntimeError(f"could not generate a feasible {level} scenario for seed {seed}")
