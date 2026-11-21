"""The Plan it score: points served minus energy and effector costs, zero for an invalid plan."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .energy import route_energy_wh
from .model import EFFECTOR, HOSTILE, SCOUT, UNKNOWN, Scenario, parse_plan
from .validator import Violation, valid_observation, validate


@dataclass
class ScoreResult:
    """The outcome of scoring a plan."""

    valid: bool
    score: float
    points: float = 0.0
    energy_wh: float = 0.0
    effectors_used: int = 0
    served: List[str] = field(default_factory=list)
    verified: List[str] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)


def evaluate(scenario: Scenario, plan: Any, verify: bool = False) -> ScoreResult:
    """Validates and scores a plan.

    Args:
        scenario: The scenario.
        plan: The decoded plan JSON.
        verify: If true, applies the optional verification bonus.

    Returns:
        The score result. An invalid plan scores 0 and lists its violations.
    """
    violations = validate(scenario, plan)
    if violations:
        return ScoreResult(False, 0.0, violations=violations)
    routes, _ = parse_plan(plan)
    rules = scenario.rules
    aircraft, contacts = scenario.aircraft_by_id(), scenario.contact_by_id()
    energy = sum(route_energy_wh(r.waypoints, aircraft[a]) for a, r in routes.items())
    n_eff = sum(1 for a in routes if aircraft[a].type == EFFECTOR)
    served: List[str] = []
    verified: List[str] = []
    engage_times: Dict[str, List[float]] = {}
    observations: Dict[str, list] = {}
    for aid, route in routes.items():
        for wp in route.waypoints:
            if wp.action == "engage":
                engage_times.setdefault(wp.target, []).append(wp.t)
            elif wp.action == "observe" and aircraft[aid].type == SCOUT:
                c = contacts[wp.target]
                if valid_observation(wp, c, scenario):
                    observations.setdefault(c.id, []).append(wp)
    points = 0.0
    for c in scenario.contacts:
        if c.cls == HOSTILE and c.id in engage_times:
            gain = c.points
            last = max(engage_times[c.id])
            if verify and any(last + rules.confirm_margin_s - 1e-6 <= o.t + o.dwell_s <= last + rules.verify_window_s + 1e-6
                              for o in observations.get(c.id, [])):
                gain *= 1.0 + rules.verify_bonus
                verified.append(c.id)
            points += gain
            served.append(c.id)
        elif c.cls == UNKNOWN and c.id in observations:
            points += c.points
            served.append(c.id)
    score = points - rules.lambda_e * energy - rules.c_eff * n_eff
    return ScoreResult(True, score, points, energy, n_eff, served, verified, [])
