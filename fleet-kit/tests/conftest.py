"""Shared fixtures: a small hand-written scenario and a valid plan for it."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleetkit.model import Scenario  # noqa: E402


def make_scenario_dict():
    """A small scenario: one scout, one light and one heavy effector, three contacts, one zone."""
    power_scout = {"p0_w": 80, "k_v": 0.25, "e_climb_wh_per_m": 0.02}
    power_light = {"p0_w": 100, "k_v": 0.08, "e_climb_wh_per_m": 0.015}
    power_heavy = {"p0_w": 150, "k_v": 0.15, "e_climb_wh_per_m": 0.04}
    return {
        "version": "1", "seed": 1, "level": "L1", "horizon_s": 900,
        "aircraft": [
            {"id": "S01", "type": "scout", "home": [0, 0, 0], "v_h_mps": 20, "v_up_mps": 8,
             "v_down_mps": 8, "capacity_wh": 100, "battery_pct": 100, "power": power_scout},
            {"id": "S02", "type": "scout", "home": [0, 20, 0], "v_h_mps": 20, "v_up_mps": 8,
             "v_down_mps": 8, "capacity_wh": 100, "battery_pct": 100, "power": power_scout},
            {"id": "L01", "type": "effector", "subtype": "light", "home": [30, 0, 0], "v_h_mps": 30,
             "v_up_mps": 8, "v_down_mps": 20, "capacity_wh": 100, "battery_pct": 100, "power": power_light},
            {"id": "L02", "type": "effector", "subtype": "light", "home": [30, 20, 0], "v_h_mps": 30,
             "v_up_mps": 8, "v_down_mps": 20, "capacity_wh": 100, "battery_pct": 100, "power": power_light},
            {"id": "H01", "type": "effector", "subtype": "heavy", "home": [60, 0, 0], "v_h_mps": 22,
             "v_up_mps": 6, "v_down_mps": 15, "capacity_wh": 100, "battery_pct": 100, "power": power_heavy},
        ],
        "contacts": [
            {"id": "C01", "class": "hostile", "pos": [1500, 0, 0], "points": 60,
             "engage_needs": {"light": 1}, "window_s": [100, 800]},
            {"id": "C02", "class": "unknown", "pos": [1500, 600, 0], "points": 20, "window_s": [0, 800]},
            {"id": "C03", "class": "civilian", "pos": [1500, 300, 0], "window_s": None},
            {"id": "C04", "class": "hostile", "pos": [1500, -400, 0], "points": 50,
             "engage_needs": {"light": 1, "heavy": 1}, "window_s": [100, 800]},
        ],
        "zones": [{"id": "Z01", "center": [1000, 500], "radius_m": 200, "top_m": 80}],
        "rules": {},
        "events": [],
    }


def make_plan_dict():
    """A valid plan: S01 observes C01 (t = 100 to 120 s) and lands; L01 engages C01 at t = 135 s."""
    return {"seed": 1, "routes": [
        {"aircraft": "S01", "waypoints": [
            {"t": 0, "x": 0, "y": 0, "z": 0},
            {"t": 10, "x": 0, "y": 0, "z": 60},
            {"t": 100, "x": 1450, "y": 100, "z": 60, "action": "observe", "target": "C01", "dwell_s": 20},
            {"t": 195, "x": 0, "y": 0, "z": 0}]},
        {"aircraft": "L01", "waypoints": [
            {"t": 69, "x": 30, "y": 0, "z": 0},
            {"t": 86, "x": 30, "y": 0, "z": 130},
            {"t": 125, "x": 1200, "y": 0, "z": 130},
            {"t": 135, "x": 1500, "y": 0, "z": 10, "action": "engage", "target": "C01"}]},
    ]}


@pytest.fixture
def scenario():
    return Scenario.from_dict(make_scenario_dict())


@pytest.fixture
def scenario_dict():
    return make_scenario_dict()


@pytest.fixture
def plan():
    return make_plan_dict()


@pytest.fixture
def clone():
    return copy.deepcopy
