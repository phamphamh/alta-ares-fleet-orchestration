"""Data model: scenarios and plans, parsed from JSON."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

HOSTILE, UNKNOWN, FRIENDLY, CIVILIAN = "hostile", "unknown", "friendly", "civilian"
SCOUT, EFFECTOR = "scout", "effector"
LIGHT, HEAVY = "light", "heavy"


@dataclass
class Power:
    """Two-mode energy model: cruise power p0 + k_v v^2 (W), climb energy per metre."""

    p0_w: float
    k_v: float
    e_climb_wh_per_m: float


@dataclass
class Aircraft:
    """One aircraft of the fleet."""

    id: str
    type: str
    subtype: Optional[str]
    home: Tuple[float, float, float]
    v_h_mps: float
    v_up_mps: float
    v_down_mps: float
    capacity_wh: float
    battery_pct: float
    power: Power

    @property
    def usable_wh(self) -> float:
        """Usable energy in Wh."""
        return self.capacity_wh * self.battery_pct / 100.0


@dataclass
class Contact:
    """A contact on the ground."""

    id: str
    cls: str
    pos: Tuple[float, float, float]
    points: float = 0.0
    needs: Dict[str, int] = field(default_factory=dict)
    window: Optional[Tuple[float, float]] = None


@dataclass
class Zone:
    """A no-fly cylinder: forbidden below `top_m`, overflyable above it."""

    id: str
    center: Tuple[float, float]
    radius_m: float
    top_m: float


@dataclass
class Rules:
    """Rule parameters (all synthetic)."""

    z_min_m: float = 30.0
    z_max_m: float = 150.0
    R_obs_m: float = 150.0
    obs_dwell_s: float = 20.0
    confirm_margin_s: float = 10.0
    protect_radius_m: float = 100.0
    collateral_radius_m: float = 200.0
    d_sep_m: float = 40.0
    exempt_radius_m: float = 100.0
    R_eng_m: float = 25.0
    sync_window_s: float = 20.0
    verify_window_s: float = 120.0
    verify_bonus: float = 0.25
    lambda_e: float = 0.5
    c_eff: float = 10.0


@dataclass
class Scenario:
    """A complete scenario."""

    version: str
    seed: int
    level: str
    horizon_s: float
    aircraft: List[Aircraft]
    contacts: List[Contact]
    zones: List[Zone]
    rules: Rules
    events: list = field(default_factory=list)

    def aircraft_by_id(self) -> Dict[str, Aircraft]:
        """Returns the aircraft indexed by id."""
        return {a.id: a for a in self.aircraft}

    def contact_by_id(self) -> Dict[str, Contact]:
        """Returns the contacts indexed by id."""
        return {c.id: c for c in self.contacts}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Scenario":
        """Builds a scenario from its JSON dictionary."""
        aircraft = []
        for a in d["aircraft"]:
            p = a["power"]
            aircraft.append(Aircraft(
                id=a["id"], type=a["type"], subtype=a.get("subtype"),
                home=tuple(float(v) for v in a["home"]),
                v_h_mps=float(a["v_h_mps"]), v_up_mps=float(a["v_up_mps"]),
                v_down_mps=float(a["v_down_mps"]), capacity_wh=float(a["capacity_wh"]),
                battery_pct=float(a["battery_pct"]),
                power=Power(float(p["p0_w"]), float(p["k_v"]), float(p["e_climb_wh_per_m"]))))
        contacts = []
        for c in d["contacts"]:
            w = c.get("window_s")
            contacts.append(Contact(
                id=c["id"], cls=c["class"], pos=tuple(float(v) for v in c["pos"]),
                points=float(c.get("points", 0.0)),
                needs={k: int(v) for k, v in (c.get("engage_needs") or {}).items()},
                window=(float(w[0]), float(w[1])) if w else None))
        zones = [Zone(z["id"], (float(z["center"][0]), float(z["center"][1])),
                      float(z["radius_m"]), float(z["top_m"])) for z in d.get("zones", [])]
        rules = Rules(**{k: v for k, v in d.get("rules", {}).items()
                         if k in Rules.__dataclass_fields__})
        return cls(version=str(d.get("version", "1")), seed=int(d["seed"]), level=str(d["level"]),
                   horizon_s=float(d["horizon_s"]), aircraft=aircraft, contacts=contacts,
                   zones=zones, rules=rules, events=list(d.get("events", [])))


@dataclass
class Waypoint:
    """One waypoint of a route."""

    t: float
    x: float
    y: float
    z: float
    action: Optional[str] = None
    target: Optional[str] = None
    dwell_s: float = 0.0

    @property
    def pos(self) -> Tuple[float, float, float]:
        """Returns the waypoint position."""
        return (self.x, self.y, self.z)

    @property
    def depart(self) -> float:
        """Returns the time the aircraft leaves the waypoint."""
        return self.t + self.dwell_s


@dataclass
class Route:
    """The route of one aircraft."""

    aircraft: str
    waypoints: List[Waypoint]


def _num(v: Any) -> bool:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:   # an integer too large for a float
        return False


def parse_plan(d: Any) -> Tuple[Optional[Dict[str, Route]], List[str]]:
    """Parses a plan dictionary into routes, reporting structural problems.

    Args:
        d: The decoded JSON of a plan.

    Returns:
        A pair (routes by aircraft id, list of structural error messages). The routes are None
        when the structure is not usable.
    """
    errors: List[str] = []
    if not isinstance(d, dict) or not isinstance(d.get("routes"), list):
        return None, ["the plan must be an object with a list `routes`"]
    routes: Dict[str, Route] = {}
    for i, r in enumerate(d["routes"]):
        if not isinstance(r, dict) or not isinstance(r.get("aircraft"), str) \
                or not isinstance(r.get("waypoints"), list):
            errors.append(f"route {i}: needs a string `aircraft` and a list `waypoints`")
            continue
        wps: List[Waypoint] = []
        ok = True
        for k, w in enumerate(r["waypoints"]):
            if not isinstance(w, dict) or not all(_num(w.get(key)) for key in ("t", "x", "y", "z")):
                errors.append(f"{r['aircraft']} waypoint {k}: t, x, y, z must be finite numbers")
                ok = False
                break
            dwell = w.get("dwell_s", 0.0)
            action, target = w.get("action"), w.get("target")
            if not _num(dwell) or dwell < 0:
                errors.append(f"{r['aircraft']} waypoint {k}: dwell_s must be a number >= 0")
                ok = False
                break
            if action not in (None, "observe", "engage") or (target is not None and not isinstance(target, str)):
                errors.append(f"{r['aircraft']} waypoint {k}: action must be observe or engage, target a string")
                ok = False
                break
            wps.append(Waypoint(float(w["t"]), float(w["x"]), float(w["y"]), float(w["z"]),
                                action, target, float(dwell)))
        if not ok:
            continue
        if r["aircraft"] in routes:
            errors.append(f"{r['aircraft']}: more than one route")
            continue
        routes[r["aircraft"]] = Route(r["aircraft"], wps)
    return routes, errors


def load_json(path: str) -> Any:
    """Loads a JSON file."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(obj: Any, path: str) -> None:
    """Writes a JSON file with stable formatting, creating the folder if needed."""
    folder = os.path.dirname(os.fspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=1)
        handle.write("\n")
