"""Builders for plans and scenarios used by the rule tests."""
import copy

from fleetkit.model import Scenario
from fleetkit.validator import validate


def rules_hit(scenario, plan):
    """Returns the set of rule ids violated by a plan."""
    return {v.rule for v in validate(scenario, plan)}


def violations(scenario, plan):
    """Returns the violations as strings."""
    return [str(v) for v in validate(scenario, plan)]


def route_of(plan, aircraft):
    """Returns the route dictionary of an aircraft."""
    return next(r for r in plan["routes"] if r["aircraft"] == aircraft)


def set_route(plan, aircraft, waypoints):
    """Returns a copy of the plan with the route of an aircraft replaced or added."""
    out = copy.deepcopy(plan)
    out["routes"] = [r for r in out["routes"] if r["aircraft"] != aircraft]
    out["routes"].append({"aircraft": aircraft, "waypoints": waypoints})
    return out


def l01_route(engage_t=135.0, z=130.0, climb_s=17.0, engage_z=10.0, target="C01", end_xy=(1500, 0)):
    """The light effector's route to C01: climb, cruise 39 s, dive 10 s."""
    o_t = engage_t - 49.0
    return [
        {"t": o_t - climb_s, "x": 30, "y": 0, "z": 0},
        {"t": o_t, "x": 30, "y": 0, "z": z},
        {"t": engage_t - 10.0, "x": 1200, "y": 0, "z": z},
        {"t": engage_t, "x": end_xy[0], "y": end_xy[1], "z": engage_z, "action": "engage", "target": target},
    ]


def s01_route(observe_t=100.0, dwell=20.0, obs_x=1450.0, obs_y=100.0, obs_z=60.0, return_t=195.0, climb_t=10.0):
    """The scout's route: climb, cruise to an observation point offset from the effector's line, observe, return."""
    return [
        {"t": 0, "x": 0, "y": 0, "z": 0},
        {"t": climb_t, "x": 0, "y": 0, "z": 60},
        {"t": observe_t, "x": obs_x, "y": obs_y, "z": obs_z, "action": "observe", "target": "C01", "dwell_s": dwell},
        {"t": return_t, "x": 0, "y": 0, "z": 0},
    ]


def s02_route(z=80.0, depart=30.0, point=(1400.0, 600.0), target="C02", via=None):
    """Scout S02 observes the unknown contact C02, flying at altitude z (80 m clears the zone ceiling)."""
    wps = [
        {"t": depart, "x": 0, "y": 20, "z": 0},
        {"t": depart + 12.0, "x": 0, "y": 20, "z": z},
    ]
    if via:
        wps.append({"t": depart + 12.0 + 80.0, "x": via[0], "y": via[1], "z": z})
        t_obs = depart + 12.0 + 80.0 + 80.0
    else:
        t_obs = depart + 12.0 + 80.0
    wps.append({"t": t_obs, "x": point[0], "y": point[1], "z": z, "action": "observe", "target": target, "dwell_s": 20})
    wps.append({"t": t_obs + 20 + 80.0, "x": 0, "y": 20, "z": z})
    wps.append({"t": t_obs + 20 + 80.0 + 12.0, "x": 0, "y": 20, "z": 0})
    return wps


def hop(home, depart=0.0, z=60.0):
    """A harmless flight with no action: climb, fly 500 m east, come back, land."""
    x, y = home
    return [
        {"t": depart, "x": x, "y": y, "z": 0},
        {"t": depart + 10, "x": x, "y": y, "z": z},
        {"t": depart + 60, "x": x + 500, "y": y, "z": z},
        {"t": depart + 110, "x": x, "y": y, "z": z},
        {"t": depart + 120, "x": x, "y": y, "z": 0},
    ]


def exempt_scenario_dict():
    """A tiny scenario where the effectors' pads are 30 m apart and within 100 m of the contact."""
    power = {"p0_w": 100, "k_v": 0.08, "e_climb_wh_per_m": 0.015}
    scout_power = {"p0_w": 80, "k_v": 0.25, "e_climb_wh_per_m": 0.02}
    return {
        "version": "1", "seed": 2, "level": "L1", "horizon_s": 900,
        "aircraft": [
            {"id": "S01", "type": "scout", "home": [0, 0, 0], "v_h_mps": 20, "v_up_mps": 8, "v_down_mps": 8,
             "capacity_wh": 100, "battery_pct": 100, "power": scout_power},
            {"id": "L01", "type": "effector", "subtype": "light", "home": [100, 0, 0], "v_h_mps": 30,
             "v_up_mps": 8, "v_down_mps": 20, "capacity_wh": 100, "battery_pct": 100, "power": power},
            {"id": "L02", "type": "effector", "subtype": "light", "home": [100, 30, 0], "v_h_mps": 30,
             "v_up_mps": 8, "v_down_mps": 20, "capacity_wh": 100, "battery_pct": 100, "power": power},
        ],
        "contacts": [{"id": "C01", "class": "hostile", "pos": [170, 15, 0], "points": 50,
                      "engage_needs": {"light": 2}, "window_s": [0, 800]}],
        "zones": [], "rules": {}, "events": [],
    }


def exempt_plan_dict(t_l01=70.0, t_l02=70.0, engage_z=10.0):
    """Scout observes from t = 20 to 40 s; both light effectors depart at 60 s and engage."""
    return {"seed": 2, "routes": [
        {"aircraft": "S01", "waypoints": [
            {"t": 0, "x": 0, "y": 0, "z": 0},
            {"t": 10, "x": 0, "y": 0, "z": 60},
            {"t": 20, "x": 90, "y": 15, "z": 60, "action": "observe", "target": "C01", "dwell_s": 20},
            {"t": 70, "x": 0, "y": 0, "z": 0}]},
        {"aircraft": "L01", "waypoints": [
            {"t": t_l01 - 10, "x": 100, "y": 0, "z": 0},
            {"t": t_l01, "x": 170, "y": 15, "z": engage_z, "action": "engage", "target": "C01"}]},
        {"aircraft": "L02", "waypoints": [
            {"t": t_l02 - 10, "x": 100, "y": 30, "z": 0},
            {"t": t_l02, "x": 170, "y": 15, "z": engage_z, "action": "engage", "target": "C01"}]},
    ]}
