"""One violating plan and one boundary plan per rule (the boundary stays valid)."""
import copy
import math

import pytest

from fleetkit.energy import route_energy_wh
from fleetkit.model import Scenario, parse_plan
from helpers import (exempt_plan_dict, exempt_scenario_dict, hop, l01_route, route_of, rules_hit,
                     s01_route, s02_route, set_route, violations)


def test_base_plan_is_valid(scenario, plan):
    assert violations(scenario, plan) == []


# ----- R1 well-formed -----------------------------------------------------------------------

def test_r1_wrong_seed(scenario, plan):
    plan["seed"] = 99
    assert rules_hit(scenario, plan) == {"R1"}


def test_r1_unknown_aircraft(scenario, plan):
    assert "R1" in rules_hit(scenario, set_route(plan, "X99", hop((0, 0))))


def test_r1_first_waypoint_not_home(scenario, plan):
    route_of(plan, "S01")["waypoints"][0]["x"] = 1
    assert "R1" in rules_hit(scenario, plan)


def test_r1_times_decreasing(scenario, plan):
    route_of(plan, "S01")["waypoints"][2]["t"] = 5
    assert "R1" in rules_hit(scenario, plan)


def test_r1_effector_must_end_with_engage(scenario, plan):
    route_of(plan, "L01")["waypoints"][-1].pop("action")
    route_of(plan, "L01")["waypoints"][-1].pop("target")
    assert "R1" in rules_hit(scenario, plan)


def test_r1_engage_must_be_last(scenario, plan):
    route_of(plan, "L01")["waypoints"].append({"t": 140, "x": 1500, "y": 0, "z": 10})
    assert "R1" in rules_hit(scenario, plan)


def test_r1_single_waypoint_route(scenario, plan):
    assert "R1" in rules_hit(scenario, set_route(plan, "S02", [{"t": 0, "x": 0, "y": 20, "z": 0}]))


def test_r1_non_finite_number(scenario, plan):
    route_of(plan, "S01")["waypoints"][1]["z"] = float("nan")
    assert "R1" in rules_hit(scenario, plan)


def test_r1_duplicate_route(scenario, plan):
    plan["routes"].append(copy.deepcopy(route_of(plan, "S01")))
    assert "R1" in rules_hit(scenario, plan)


def test_r1_time_beyond_horizon(scenario, plan):
    route_of(plan, "S01")["waypoints"][-1]["t"] = 900.5
    assert "R1" in rules_hit(scenario, plan)


def test_r1_boundary_arrival_exactly_at_horizon(scenario, plan):
    route_of(plan, "S01")["waypoints"][-1]["t"] = 900.0
    assert violations(scenario, plan) == []


def test_r1_not_an_object(scenario):
    assert rules_hit(scenario, [1, 2]) == {"R1"}


# ----- R2 kinematics ------------------------------------------------------------------------

def test_r2_leg_too_fast(scenario, plan):
    route_of(plan, "S01")["waypoints"][-1]["t"] = 180  # 1453 m in 60 s needs 72.7 s
    assert "R2" in rules_hit(scenario, plan)


def test_r2_climb_too_fast(scenario, plan):
    route_of(plan, "S01")["waypoints"][1]["t"] = 7.0   # 60 m at 8 m/s needs 7.5 s
    assert "R2" in rules_hit(scenario, plan)


def test_r2_altitude_too_low(scenario, plan):
    route_of(plan, "S01")["waypoints"][2]["z"] = 29.0
    assert "R2" in rules_hit(scenario, plan)


def test_r2_altitude_too_high(scenario, plan):
    plan = set_route(plan, "L01", l01_route(z=151.0, climb_s=19.0))
    assert "R2" in rules_hit(scenario, plan)


def test_r2_boundaries_stay_valid(scenario, plan):
    p = copy.deepcopy(plan)
    route_of(p, "S01")["waypoints"][1]["t"] = 7.5                 # climb exactly at the rate
    assert violations(scenario, p) == []
    p = set_route(plan, "S01", s01_route(obs_z=30.0))             # exactly the floor
    assert violations(scenario, p) == []
    p = set_route(plan, "L01", l01_route(z=150.0, climb_s=18.75)) # exactly the ceiling and the rate
    assert violations(scenario, p) == []
    p = copy.deepcopy(plan)
    wps = route_of(p, "S01")["waypoints"]
    wps[1]["t"] = 100.0 - math.hypot(1450.0, 100.0) / 20.0        # the leg at exactly the maximum speed
    assert violations(scenario, p) == []


# ----- R3 energy and return -----------------------------------------------------------------

def test_r3_not_enough_energy(scenario_dict, plan):
    scenario_dict["aircraft"][0]["battery_pct"] = 5
    assert "R3" in rules_hit(Scenario.from_dict(scenario_dict), plan)


def test_r3_scout_must_land_at_home(scenario, plan):
    route_of(plan, "S01")["waypoints"][-1]["z"] = 5
    assert "R3" in rules_hit(scenario, plan)


def test_r3_boundary_energy_exactly_at_the_limit(scenario_dict, plan):
    base = Scenario.from_dict(scenario_dict)
    route, _ = parse_plan(plan)
    need = route_energy_wh(route["S01"].waypoints, base.aircraft_by_id()["S01"])
    for delta, ok in ((0.0, True), (1e-4, True), (-1e-3, False)):
        scenario_dict["aircraft"][0]["battery_pct"] = (need + delta) / scenario_dict["aircraft"][0]["capacity_wh"] * 100
        hit = "R3" in rules_hit(Scenario.from_dict(scenario_dict), plan)
        assert hit is (not ok)


# ----- R4 confirm before engage -------------------------------------------------------------

def test_r4_engagement_without_observation(scenario, plan):
    plan["routes"] = [r for r in plan["routes"] if r["aircraft"] != "S01"]
    assert "R4" in rules_hit(scenario, plan)


def test_r4_engagement_too_soon_after_observation(scenario, plan):
    plan = set_route(plan, "L01", l01_route(engage_t=129.9))      # needs >= 120 + 10
    assert "R4" in rules_hit(scenario, plan)


def test_r4_observation_too_far(scenario, plan):
    plan = set_route(plan, "S01", s01_route(obs_x=1300.0))        # 232 m away in 3D
    assert "R4" in rules_hit(scenario, plan)


def test_r4_observation_dwell_too_short(scenario, plan):
    plan = set_route(plan, "S01", s01_route(dwell=19.9))
    assert "R4" in rules_hit(scenario, plan)


def test_r4_boundaries_stay_valid(scenario, plan):
    p = set_route(plan, "L01", l01_route(engage_t=130.0))         # exactly the margin
    assert violations(scenario, p) == []
    dx = math.sqrt(150.0 ** 2 - 100.0 ** 2 - 60.0 ** 2)           # observation exactly 150 m (3D) away
    p = set_route(plan, "S01", s01_route(obs_x=1500.0 - dx))
    assert violations(scenario, p) == []


# ----- R5 authorisation ---------------------------------------------------------------------

def test_r5_scout_cannot_engage(scenario, plan):
    wps = [{"t": 0, "x": 0, "y": 20, "z": 0}, {"t": 30, "x": 1500, "y": 0, "z": 10, "action": "engage", "target": "C01"}]
    assert "R5" in rules_hit(scenario, set_route(plan, "S02", wps))


def test_r5_effector_cannot_observe(scenario, plan):
    wps = l01_route()
    wps[2].update({"action": "observe", "target": "C02", "dwell_s": 20})
    wps[3]["t"] += 20
    assert "R5" in rules_hit(scenario, set_route(plan, "L01", wps))


def test_r5_cannot_engage_an_unknown_contact(scenario, plan):
    wps = l01_route(target="C02", end_xy=(1500, 600))
    assert "R5" in rules_hit(scenario, set_route(plan, "L01", wps))


def test_r5_cannot_observe_a_civilian(scenario, plan):
    wps = s02_route(point=(1450, 300), target="C03")
    assert "R5" in rules_hit(scenario, set_route(plan, "S02", wps))


# ----- R6 exclusion -------------------------------------------------------------------------

def test_r6_enters_zone_below_ceiling(scenario, plan):
    assert "R6" in rules_hit(scenario, set_route(plan, "S02", s02_route(z=79.0)))


def test_r6_overflying_at_exactly_the_ceiling_is_valid(scenario, plan):
    assert violations(scenario, set_route(plan, "S02", s02_route(z=80.0))) == []


def test_r6_protected_area_of_a_civilian(scenario, plan):
    wps = s02_route(point=(1400, 600), via=(1450, 300))           # passes 50 m from C03 at z = 80
    assert "R6" in rules_hit(scenario, set_route(plan, "S02", wps))


def test_r6_protected_area_applies_at_any_altitude(scenario, plan):
    wps = s02_route(z=140.0, point=(1500, 700), via=(1500, 300))
    assert "R6" in rules_hit(scenario, set_route(plan, "S02", wps))


# ----- R7 collateral ------------------------------------------------------------------------

def _with_civilian_at(scenario_dict, y):
    scenario_dict["contacts"][2]["pos"] = [1500, y, 0]
    return Scenario.from_dict(scenario_dict)


def test_r7_engaging_next_to_a_civilian(scenario_dict, plan):
    assert "R7" in rules_hit(_with_civilian_at(scenario_dict, 150), plan)


def test_r7_boundary_exactly_at_the_collateral_radius(scenario_dict, plan):
    assert violations(_with_civilian_at(scenario_dict, 200), plan) == []
    assert "R7" in rules_hit(_with_civilian_at(scenario_dict, 199.9), plan)


# ----- R8 separation ------------------------------------------------------------------------

def _two_scouts(scenario_dict, gap):
    scenario_dict["aircraft"][1]["home"] = [0, gap, 0]
    return Scenario.from_dict(scenario_dict)


def _two_hops(gap):
    return {"seed": 1, "routes": [{"aircraft": "S01", "waypoints": hop((0, 0))},
                                  {"aircraft": "S02", "waypoints": hop((0, gap))}]}


def test_r8_pads_too_close_launching_together(scenario_dict):
    assert rules_hit(_two_scouts(scenario_dict, 20), _two_hops(20)) == {"R8"}


def test_r8_boundary_exactly_40_m_apart_is_valid_and_39_9_is_not(scenario_dict):
    assert violations(_two_scouts(copy.deepcopy(scenario_dict), 40), _two_hops(40)) == []
    assert "R8" in rules_hit(_two_scouts(copy.deepcopy(scenario_dict), 39.9), _two_hops(39.9))


def test_r8_staggered_launch_resolves_the_conflict(scenario_dict):
    plan = {"seed": 1, "routes": [{"aircraft": "S01", "waypoints": hop((0, 0))},
                                  {"aircraft": "S02", "waypoints": hop((0, 20), depart=40.0)}]}
    # S02 leaves once S01 has flown away; S01 is airborne to t = 120, so it must also be far when S02 starts
    plan["routes"][1]["waypoints"] = hop((0, 20), depart=125.0)
    assert violations(_two_scouts(scenario_dict, 20), plan) == []


def test_r8_crossing_flights(scenario_dict):
    wps_a = [{"t": 0, "x": 0, "y": 0, "z": 0}, {"t": 10, "x": 0, "y": 0, "z": 60},
             {"t": 60, "x": 500, "y": 0, "z": 60}, {"t": 110, "x": 0, "y": 0, "z": 60},
             {"t": 120, "x": 0, "y": 0, "z": 0}]
    wps_b = [{"t": 0, "x": 0, "y": 200, "z": 0}, {"t": 10, "x": 0, "y": 200, "z": 60},
             {"t": 60, "x": 500, "y": -200, "z": 60}, {"t": 110, "x": 0, "y": 200, "z": 60},
             {"t": 120, "x": 0, "y": 200, "z": 0}]
    scenario_dict["aircraft"][1]["home"] = [0, 200, 0]
    scenario_dict["aircraft"][1]["v_h_mps"] = 40
    plan = {"seed": 1, "routes": [{"aircraft": "S01", "waypoints": wps_a}, {"aircraft": "S02", "waypoints": wps_b}]}
    assert "R8" in rules_hit(Scenario.from_dict(scenario_dict), plan)


def test_r8_vertical_separation_counts_in_3d(scenario_dict):
    plan = _two_hops(20)
    plan["routes"][1]["waypoints"][1]["z"] = 130
    plan["routes"][1]["waypoints"][2]["z"] = 130
    plan["routes"][1]["waypoints"][3]["z"] = 130
    scenario = _two_scouts(scenario_dict, 20)
    scenario.aircraft_by_id()["S02"].v_up_mps = 20
    assert "R8" in rules_hit(scenario, plan)  # still close while both climb from pads 20 m apart


def test_r8_exemption_for_effectors_engaging_the_same_contact():
    scenario = Scenario.from_dict(exempt_scenario_dict())
    assert violations(scenario, exempt_plan_dict()) == []


def test_r8_exemption_depends_on_the_radius():
    d = exempt_scenario_dict()
    d["rules"] = {"exempt_radius_m": 50}
    assert "R8" in rules_hit(Scenario.from_dict(d), exempt_plan_dict())


def test_r8_no_exemption_for_other_targets():
    d = exempt_scenario_dict()
    d["contacts"].append({"id": "C02", "class": "hostile", "pos": [170, -15, 0], "points": 50,
                          "engage_needs": {"light": 1}, "window_s": [0, 800]})
    d["contacts"][0]["engage_needs"] = {"light": 1}
    plan = exempt_plan_dict()
    route_of(plan, "L02")["waypoints"][1].update({"x": 170, "y": -15, "target": "C02"})
    assert "R8" in rules_hit(Scenario.from_dict(d), plan)  # also needs a scout observation of C02 (R4)


# ----- R9 time windows ----------------------------------------------------------------------

def test_r9_observation_starting_before_the_window(scenario, plan):
    plan = set_route(plan, "S01", s01_route(observe_t=99.0))
    assert "R9" in rules_hit(scenario, plan)


def test_r9_engagement_after_the_window(scenario_dict, plan):
    scenario_dict["contacts"][0]["window_s"] = [100, 134.9]
    assert "R9" in rules_hit(Scenario.from_dict(scenario_dict), plan)


def test_r9_boundary_window_closing_exactly_at_the_engagement(scenario_dict, plan):
    scenario_dict["contacts"][0]["window_s"] = [100, 135]
    assert violations(Scenario.from_dict(scenario_dict), plan) == []


# ----- R10 all-or-nothing engagement --------------------------------------------------------

def test_r10_missing_a_heavy_effector(scenario_dict, plan):
    scenario_dict["contacts"][0]["engage_needs"] = {"light": 1, "heavy": 1}
    assert "R10" in rules_hit(Scenario.from_dict(scenario_dict), plan)


def test_r10_too_many_effectors():
    d = exempt_scenario_dict()
    d["contacts"][0]["engage_needs"] = {"light": 1}
    assert "R10" in rules_hit(Scenario.from_dict(d), exempt_plan_dict())


def test_r10_engagements_out_of_sync_and_boundary():
    scenario = Scenario.from_dict(exempt_scenario_dict())
    assert "R10" in rules_hit(scenario, exempt_plan_dict(t_l01=90.5))      # 20.5 s apart
    assert violations(scenario, exempt_plan_dict(t_l01=90.0)) == []        # exactly 20 s apart


def test_r10_engagement_too_far_and_boundary():
    scenario = Scenario.from_dict(exempt_scenario_dict())
    assert violations(scenario, exempt_plan_dict(engage_z=25.0)) == []     # exactly 25 m
    assert "R10" in rules_hit(scenario, exempt_plan_dict(engage_z=25.01))


def test_a_huge_integer_in_a_plan_is_a_structural_error_not_a_crash():
    from fleetkit.model import parse_plan
    plan = {"seed": 1, "routes": [{"aircraft": "S01", "waypoints": [{"t": 10 ** 400, "x": 0, "y": 0, "z": 50}]}]}
    routes, errors = parse_plan(plan)
    assert errors and "finite numbers" in errors[0]
