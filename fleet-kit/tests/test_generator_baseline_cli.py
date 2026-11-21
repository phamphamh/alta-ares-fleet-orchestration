"""Generator, baseline planner, visualiser and command line."""
import json
import math

import pytest

from fleetkit import cli
from fleetkit.baseline import greedy_plan
from fleetkit.generator import LEVELS, generate
from fleetkit.model import Scenario
from fleetkit.scorer import evaluate
from fleetkit.viz import render_svg


def scenario_for(level, seed, check=False):
    return Scenario.from_dict(generate(level, seed, ensure_feasible=check))


def test_generation_is_deterministic_and_seed_dependent():
    assert generate("L2", 5, ensure_feasible=False) == generate("L2", 5, ensure_feasible=False)
    assert generate("L2", 5, ensure_feasible=False) != generate("L2", 6, ensure_feasible=False)


@pytest.mark.parametrize("level", list(LEVELS))
def test_level_sizes(level):
    spec = LEVELS[level]
    s = scenario_for(level, 3)
    kinds = [(a.type, a.subtype) for a in s.aircraft]
    assert kinds.count(("scout", None)) == spec["scouts"]
    assert kinds.count(("effector", "light")) == spec["light"]
    assert kinds.count(("effector", "heavy")) == spec["heavy"]
    classes = [c.cls for c in s.contacts]
    assert classes.count("hostile") == spec["hostile"] and classes.count("unknown") == spec["unknown"]
    assert s.horizon_s <= 900.0                       # within a strike drone's autonomy of about 15 minutes
    assert len(s.zones) <= spec["zones"]


@pytest.mark.parametrize("level", ["L1", "L2", "L3"])
def test_scenario_invariants(level):
    for seed in range(6):
        s = scenario_for(level, seed)
        xs = [a.home[0] for a in s.aircraft]
        ys = [a.home[1] for a in s.aircraft]
        assert max(xs) - min(xs) <= 100.0 + 1e-6 and max(ys) - min(ys) <= 100.0 + 1e-6      # one shared launch site
        assert len({a.home for a in s.aircraft}) == len(s.aircraft)
        for c in s.contacts:
            for z in s.zones:
                assert math.hypot(c.pos[0] - z.center[0], c.pos[1] - z.center[1]) >= z.radius_m + 120.0 - 0.2
            assert 0 < c.pos[0] < LEVELS[level]["area"] and 0 < c.pos[1] < LEVELS[level]["area"] and c.pos[2] == 0
            if c.cls in ("hostile", "unknown"):
                lo, hi = c.window
                assert 0 <= lo < hi <= s.horizon_s and hi - lo >= LEVELS[level]["window"][0] * s.horizon_s - 0.2
        for a, b in [(p, q) for i, p in enumerate(s.contacts) for q in s.contacts[i + 1:]]:
            assert math.hypot(a.pos[0] - b.pos[0], a.pos[1] - b.pos[1]) >= 60.0 - 0.2
        n_light = sum(1 for a in s.aircraft if a.subtype == "light")
        n_heavy = sum(1 for a in s.aircraft if a.subtype == "heavy")
        for c in s.contacts:
            if c.cls == "hostile":
                assert 1 <= sum(c.needs.values()) <= 4
                assert c.needs.get("light", 0) <= n_light and c.needs.get("heavy", 0) <= n_heavy


def test_aircraft_autonomy_is_about_fifteen_minutes():
    s = scenario_for("L3", 1)
    for a in s.aircraft:
        v = min(a.v_h_mps, math.sqrt(a.power.p0_w / a.power.k_v))
        minutes = a.capacity_wh * 3600.0 / (a.power.p0_w + a.power.k_v * v * v) / 60.0
        assert 8.0 <= minutes <= 25.0, (a.id, minutes)


def test_collateral_traps_exist():
    found = 0
    for seed in range(12):
        s = scenario_for("L3", seed)
        for c in s.contacts:
            if c.cls == "hostile" and any(f.cls in ("friendly", "civilian") and
                                          math.hypot(c.pos[0] - f.pos[0], c.pos[1] - f.pos[1]) < 200.0
                                          for f in s.contacts):
                found += 1
    assert found >= 3


@pytest.mark.parametrize("level,seeds", [("L1", range(10)), ("L2", range(8)), ("L3", range(4))])
def test_baseline_plans_are_valid_and_never_negative(level, seeds):
    for seed in seeds:
        s = scenario_for(level, seed)
        result = evaluate(s, greedy_plan(s))
        assert result.valid, [str(v) for v in result.violations][:3]
        assert result.score >= 0.0


def test_baseline_is_deterministic():
    s = scenario_for("L2", 2)
    assert greedy_plan(s) == greedy_plan(s)


def test_checked_scenarios_have_a_positive_plan():
    for level in ("L1", "L2", "L3"):
        for seed in range(4):
            s = scenario_for(level, seed, check=True)
            assert evaluate(s, greedy_plan(s, max_contacts=3)).score > 0.0


def test_scarcity_the_baseline_does_not_serve_everything():
    shares = []
    for seed in range(8):
        s = scenario_for("L2", seed)
        r = evaluate(s, greedy_plan(s))
        potential = sum(c.points for c in s.contacts if c.cls in ("hostile", "unknown"))
        shares.append(r.points / potential)
    assert sum(shares) / len(shares) < 0.85


def test_visualiser_draws_contacts_zones_and_routes():
    s = scenario_for("L1", 2)
    svg = render_svg(s, greedy_plan(s))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert all(c.id in svg for c in s.contacts) and "polyline" in svg


def test_command_line_round_trip(tmp_path, capsys):
    scen, plan, svg = str(tmp_path / "s.json"), str(tmp_path / "p.json"), str(tmp_path / "v.svg")
    assert cli.main(["generate", "L1", "4", "-o", scen]) == 0
    assert cli.main(["baseline", scen, "-o", plan]) == 0
    assert cli.main(["validate", scen, plan]) == 0
    assert cli.main(["score", scen, plan, "--verify"]) == 0
    assert cli.main(["viz", scen, plan, "-o", svg]) == 0
    assert cli.main(["stats", "L1", "--seeds", "0-2"]) == 0
    out = capsys.readouterr().out
    assert "valid" in out and "score" in out and "baseline plans valid: 3/3" in out
    broken = json.load(open(plan))
    broken["routes"][0]["waypoints"][0]["x"] += 5
    json.dump(broken, open(plan, "w"))
    assert cli.main(["validate", scen, plan]) == 1


def test_optional_level_keys_change_nothing_unless_set(monkeypatch):
    from fleetkit import generator
    base = generator.generate("L2", 5, ensure_feasible=False)
    # unset keys: the scenario is exactly what it always was
    assert base == generator.generate("L2", 5, ensure_feasible=False)
    lo = {**generator.LEVELS["L2"], "battery": (40, 41)}
    monkeypatch.setitem(generator.LEVELS, "L2", lo)
    low = generator.generate("L2", 5, ensure_feasible=False)
    assert all(40 <= a["battery_pct"] <= 41 for a in low["aircraft"])
    tied = {**generator.LEVELS["L2"], "battery": (70, 100), "points_per_need": 15}
    monkeypatch.setitem(generator.LEVELS, "L2", tied)
    sc = generator.generate("L2", 5, ensure_feasible=False)
    for c in sc["contacts"]:
        if c["class"] == "hostile":
            n = sum(c["engage_needs"].values())
            assert 40 + 15 * (n - 1) <= c["points"] <= 70 + 15 * (n - 1)
