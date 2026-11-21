"""Energy model and scoring."""
import math

from fleetkit.energy import best_range_speed, leg_energy_wh, route_energy_wh
from fleetkit.model import Power, Scenario, Waypoint, parse_plan
from fleetkit.scorer import evaluate
from helpers import l01_route, route_of, s01_route, s02_route, set_route


def test_cruise_leg_energy_by_hand():
    power = Power(p0_w=100, k_v=0.08, e_climb_wh_per_m=0.02)
    a = Waypoint(0, 0, 0, 60)
    b = Waypoint(50, 1000, 0, 60)                     # 20 m/s: P = 100 + 0.08 * 400 = 132 W for 50 s
    assert math.isclose(leg_energy_wh(a, b, power), 132 * 50 / 3600, rel_tol=1e-12)


def test_climb_costs_energy_and_descent_costs_nothing_extra():
    power = Power(100, 0.08, 0.02)
    up = leg_energy_wh(Waypoint(0, 0, 0, 0), Waypoint(10, 0, 0, 60), power)       # hovering while climbing 60 m
    down = leg_energy_wh(Waypoint(0, 0, 0, 60), Waypoint(10, 0, 0, 0), power)
    assert math.isclose(up - down, 60 * 0.02, rel_tol=1e-12)
    assert math.isclose(down, 100 * 10 / 3600, rel_tol=1e-12)


def test_best_range_speed_minimises_energy_per_metre():
    power = Power(100, 0.08, 0.02)
    vstar = best_range_speed(power)
    assert math.isclose(vstar, math.sqrt(100 / 0.08))
    per_metre = lambda v: (100 + 0.08 * v * v) / v
    assert per_metre(vstar) < per_metre(vstar - 3) and per_metre(vstar) < per_metre(vstar + 3)


def test_dwell_burns_hover_power(scenario):
    ac = scenario.aircraft_by_id()["S01"]
    wps = [Waypoint(0, 0, 0, 0), Waypoint(10, 0, 0, 0, "observe", "C01", 30.0)]
    assert math.isclose(route_energy_wh(wps, ac), 80 * 10 / 3600 + 80 * 30 / 3600, rel_tol=1e-12)


def test_base_plan_score_matches_a_hand_computation(scenario, plan):
    routes, _ = parse_plan(plan)
    ac = scenario.aircraft_by_id()
    s01, l01 = routes["S01"].waypoints, routes["L01"].waypoints
    by_hand = 0.0
    for k in range(3):
        a, b = s01[k], s01[k + 1]
        v = math.hypot(b.x - a.x, b.y - a.y) / (b.t - a.depart)
        by_hand += (80 + 0.25 * v * v) * (b.t - a.depart) / 3600 + 0.02 * max(0, b.z - a.z) + 80 * b.dwell_s / 3600
    for k in range(3):
        a, b = l01[k], l01[k + 1]
        v = math.hypot(b.x - a.x, b.y - a.y) / (b.t - a.depart)
        by_hand += (100 + 0.08 * v * v) * (b.t - a.depart) / 3600 + 0.015 * max(0, b.z - a.z)
    result = evaluate(scenario, plan)
    assert result.valid and result.served == ["C01"]
    assert math.isclose(result.energy_wh, by_hand, rel_tol=1e-9)
    assert math.isclose(result.score, 60 - 0.5 * by_hand - 10, rel_tol=1e-9)
    assert result.effectors_used == 1


def test_invalid_plan_scores_zero_and_lists_violations(scenario, plan):
    route_of(plan, "L01")["waypoints"][-1]["t"] = 129.0
    result = evaluate(scenario, plan)
    assert not result.valid and result.score == 0.0 and result.violations


def test_empty_plan_scores_zero(scenario):
    result = evaluate(scenario, {"seed": 1, "routes": []})
    assert result.valid and result.score == 0.0 and result.served == []


def test_observing_an_unknown_contact_earns_its_points(scenario, plan):
    base = evaluate(scenario, plan)
    plan = set_route(plan, "S02", s02_route(z=80.0))
    result = evaluate(scenario, plan)
    assert result.valid and "C02" in result.served
    assert math.isclose(result.points - base.points, 20.0)
    assert result.score < base.score + 20.0          # the second scout's energy is charged


def test_an_observation_without_range_earns_nothing(scenario, plan):
    plan = set_route(plan, "S02", s02_route(z=80.0, point=(1200.0, 600.0)))   # 300 m away: no points
    result = evaluate(scenario, plan)
    assert result.valid and "C02" not in result.served


def _second_observation(plan, start):
    """S01 observes C01 again from `start` for 20 s, then returns (the engagement is at t = 135 s)."""
    wps = s01_route(return_t=start + 20.0 + 80.0)
    wps.insert(3, {"t": start, "x": 1450, "y": 100, "z": 60, "action": "observe", "target": "C01", "dwell_s": 20})
    return set_route(plan, "S01", wps)


def test_verification_bonus_applies_only_when_asked(scenario, plan):
    plan = _second_observation(plan, 200.0)
    core = evaluate(scenario, plan)
    verified = evaluate(scenario, plan, verify=True)
    assert core.valid and verified.valid
    assert verified.verified == ["C01"]
    assert math.isclose(verified.score - core.score, 0.25 * 60.0)


def test_no_verification_means_no_bonus_and_no_penalty(scenario, plan):
    core = evaluate(scenario, plan)
    verified = evaluate(scenario, plan, verify=True)
    assert verified.verified == [] and math.isclose(core.score, verified.score)


def test_verification_window_boundaries(scenario, plan):
    # engagement at t = 135 s: the verifying observation must complete between 145 s and 255 s
    for start, expected in ((124.0, False), (125.0, True), (235.0, True), (235.5, False)):
        result = evaluate(scenario, _second_observation(plan, start), verify=True)
        assert result.valid, [str(v) for v in result.violations]
        assert (result.verified == ["C01"]) is expected, start
