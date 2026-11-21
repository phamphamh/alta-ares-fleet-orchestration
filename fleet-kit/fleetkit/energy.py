"""The two-mode energy model: cruise power depends on speed, climbing costs energy per metre."""
from __future__ import annotations

import math
from typing import List

from .model import Aircraft, Power, Waypoint

J_PER_WH = 3600.0


def best_range_speed(power: Power) -> float:
    """Returns the cruise speed that minimises energy per metre, sqrt(p0 / k_v)."""
    return math.sqrt(power.p0_w / power.k_v)


def leg_energy_wh(a: Waypoint, b: Waypoint, power: Power) -> float:
    """Returns the energy in Wh of the leg from the departure of `a` to the arrival at `b`."""
    duration = b.t - a.depart
    if duration <= 0.0:
        return 0.0
    horizontal = math.hypot(b.x - a.x, b.y - a.y)
    speed = horizontal / duration
    cruise_j = (power.p0_w + power.k_v * speed * speed) * duration
    climb_wh = power.e_climb_wh_per_m * max(0.0, b.z - a.z)
    return cruise_j / J_PER_WH + climb_wh


def route_energy_wh(waypoints: List[Waypoint], aircraft: Aircraft) -> float:
    """Returns the total energy of a route: legs plus hovering during dwells.

    The wait on the ground before the first departure costs nothing.
    """
    power = aircraft.power
    total = 0.0
    for k in range(len(waypoints) - 1):
        total += leg_energy_wh(waypoints[k], waypoints[k + 1], power)
        if k + 1 < len(waypoints):
            total += power.p0_w * waypoints[k + 1].dwell_s / J_PER_WH
    return total


def piece_energy_wh(piece, power: Power) -> float:
    """Returns the energy in Wh of one linear piece of motion `(t0, t1, p0, p1)`, flown in the air.

    Cruise power at the real ground speed plus climb energy; a piece that stays on the ground costs nothing.
    """
    t0, t1, p0, p1 = piece
    d = t1 - t0
    if d <= 0.0 or (p0[2] <= 0.0 and p1[2] <= 0.0 and p0[:2] == p1[:2]):
        return 0.0
    v = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / d
    return (power.p0_w + power.k_v * v * v) * d / J_PER_WH + power.e_climb_wh_per_m * max(0.0, p1[2] - p0[2])
