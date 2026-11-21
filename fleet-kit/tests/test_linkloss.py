"""Tests for the link-loss part: the execution simulator, the oracle, events, scoring and sizing."""
import copy
import json
import random
from types import SimpleNamespace

import pytest

from fleetkit.baseline import greedy_plan
from fleetkit.cli import main as cli_main
from fleetkit.energy import route_energy_wh
from fleetkit.generator import generate
from fleetkit.linkloss import RouteClock, simulate
from fleetkit.linkloss import sim as simmod
from fleetkit.linkloss.events import make_events
from fleetkit.linkloss.policies import (BroadcastSensePolicy, ContinuePolicy, HoldPolicy, ReturnPolicy,
                                        load_policy)
from fleetkit.linkloss.score import evaluate_cases, oracle_points, retention, sizing
from fleetkit.model import Scenario, parse_plan
from fleetkit.scorer import evaluate

CUT = 50.0


def ev(*events, t_loss=CUT):
    return {"t_loss": t_loss, "events": list(events)}


def by_aircraft(table, default="continue"):
    """A policy factory: each aircraft follows its own entry of `table` (an action or a function of obs)."""
    class P:
        def __init__(self, scenario, plan, aid):
            self.what = table.get(aid, default)

        def step(self, obs):
            w = self.what(obs) if callable(self.what) else self.what
            return ({"kind": w} if isinstance(w, str) else w), None
    return P


@pytest.fixture
def sc(scenario):
    return scenario


def test_the_route_clock_gives_the_planned_position(scenario, plan):
    routes, _ = parse_plan(plan)
    clock = RouteClock(routes["S01"])
    assert clock.position(0) == (0, 0, 0)
    assert clock.position(-5) == (0, 0, 0)
    assert clock.position(10) == (0, 0, 60)
    assert clock.position(55) == pytest.approx((725, 50, 60))      # halfway along the leg 10 s to 100 s
    assert clock.position(100) == (1450, 100, 60)
    assert clock.position(110) == (1450, 100, 60)                  # dwelling
    assert clock.position(195) == (0, 0, 0)
    assert clock.position(500) == (0, 0, 0)                        # after the end
    late = RouteClock(routes["L01"])
    assert late.position(10) == (30, 0, 0) and late.start == 69    # waits at home before its first waypoint


def test_without_a_cut_the_plan_is_flown_exactly(scenario, plan):
    want = evaluate(scenario, plan)
    assert want.valid
    run = simulate(scenario, plan, None, ContinuePolicy)
    assert run.ok and run.points == want.points and sorted(run.served) == sorted(want.served)
    run = simulate(scenario, plan, ev(), ContinuePolicy)
    assert run.ok and run.points == want.points
    assert run.crafts["S01"].end_kind == "landed" and run.crafts["L01"].end_kind == "engaged"
    assert run.crafts["L01"].engaged_at == pytest.approx(135.0)


def test_energy_spent_equals_the_route_energy_of_the_plan(scenario, plan):
    routes, _ = parse_plan(plan)
    aircraft = scenario.aircraft_by_id()
    run = simulate(scenario, plan, ev(), ContinuePolicy)
    for aid in ("S01", "L01"):
        spent = aircraft[aid].usable_wh - run.crafts[aid].energy
        assert spent == pytest.approx(route_energy_wh(routes[aid].waypoints, aircraft[aid]), abs=1e-6)


def test_the_oracle_without_events_serves_the_whole_plan(scenario, plan):
    run = simulate(scenario, plan, ev(), oracle=True)
    assert run.ok and run.points == evaluate(scenario, plan).points


def test_hold_freezes_the_route_clock_and_serves_nothing_more(scenario, plan):
    run = simulate(scenario, plan, ev(), HoldPolicy)
    assert run.ok
    assert run.crafts["S01"].tau == pytest.approx(CUT) and run.points == 0.0
    s = run.crafts["S01"]
    assert s.pos == RouteClock(s.route).position(CUT)
    # hovering burns hover power: 80 W for the rest of the horizon
    assert s.energy < 100 - 80 * 800 / 3600.0 * 0.9


def test_return_retraces_the_route_and_lands(scenario, plan):
    run = simulate(scenario, plan, ev(t_loss=60.0), ReturnPolicy)
    assert run.ok and run.points == 0.0
    s = run.crafts["S01"]
    assert s.end_kind == "landed" and s.ended == pytest.approx(120.0)      # tau 60 back to 0 at one per second
    assert s.pos == (0, 0, 0)
    assert run.crafts["L01"].end_kind == "landed"                           # never took off


def test_a_slower_route_arrives_later_and_is_scored_on_real_times(scenario, plan):
    half = by_aircraft({"S01": {"kind": "speed", "scale": 0.5}, "L01": {"kind": "speed", "scale": 0.5}})
    run = simulate(scenario, plan, ev(), half)
    assert run.ok
    assert run.crafts["L01"].engaged_at == pytest.approx(50 + (135 - 50) / 0.5)
    assert run.points == 60.0
    # a scale below 0.5 is clipped to 0.5
    slow = by_aircraft({"S01": {"kind": "speed", "scale": 0.1}, "L01": {"kind": "speed", "scale": 0.1}})
    assert simulate(scenario, plan, ev(), slow).crafts["L01"].engaged_at == pytest.approx(220.0)


def test_a_window_missed_by_a_late_engagement_leaves_the_contact_unserved(scenario_dict, plan):
    scenario_dict["contacts"][0]["window_s"] = [100, 200]
    sc2 = Scenario.from_dict(scenario_dict)
    slow = by_aircraft({"S01": {"kind": "speed", "scale": 0.5}, "L01": {"kind": "speed", "scale": 0.5}})
    run = simulate(sc2, plan, ev(), slow)
    assert run.ok and run.points == 0.0 and run.engagements["C01"]


def test_an_observation_needs_its_full_dwell(scenario, plan):
    leave = by_aircraft({"S01": lambda o: "return" if o["t"] >= 110 else "continue"})
    run = simulate(scenario, plan, ev(t_loss=60.0), leave)
    assert not run.ok and any("R4" in f for f in run.failed)       # L01 engages with no completed observation


def test_a_failed_scout_leaves_the_engagement_unconfirmed(scenario, plan):
    events = ev({"kind": "failure", "t": 60.0, "aircraft": "S01"})
    run = simulate(scenario, plan, events, ContinuePolicy)
    assert any("R4" in f for f in run.failed)
    assert run.crafts["S01"].end_kind == "failed"
    ora = simulate(scenario, plan, events, oracle=True)
    assert ora.ok and ora.points == 0.0 and ora.crafts["L01"].end_kind == "landed"


def test_engaging_a_reclassified_contact_fails_unless_the_effector_senses_it(scenario, plan):
    events = ev({"kind": "reclassify", "t": 70.0, "contact": "C01"})
    assert any("reclassified" in f for f in simulate(scenario, plan, events, ContinuePolicy).failed)
    aware = simulate(scenario, plan, events, BroadcastSensePolicy)
    assert aware.ok and aware.points == 0.0                         # L01 senses it 300 m out and returns
    assert simulate(scenario, plan, events, oracle=True).ok


def test_a_popup_zone_on_the_route_fails_the_blind_plan_and_is_avoided_by_a_policy_that_senses_it(scenario, plan):
    zone = {"kind": "popup_zone", "t": 30.0, "center": [1000.0, 70.0], "radius_m": 100.0, "top_m": 200.0}
    blind = simulate(scenario, plan, ev(zone), ContinuePolicy)
    assert any("pop-up zone" in f for f in blind.failed)
    assert simulate(scenario, plan, ev(zone), BroadcastSensePolicy).ok
    assert simulate(scenario, plan, ev(zone), oracle=True).ok


def test_a_zone_that_appears_on_top_of_an_aircraft_is_a_failure(scenario, plan):
    zone = {"kind": "popup_zone", "t": 60.0, "center": [644.0, 44.0], "radius_m": 60.0, "top_m": 200.0}   # where S01 hovers
    assert any("pop-up zone" in f for f in simulate(scenario, plan, ev(zone), HoldPolicy).failed)


def test_a_zone_that_appears_above_the_ceiling_of_nobody_is_harmless(scenario, plan):
    zone = {"kind": "popup_zone", "t": 30.0, "center": [1000.0, 70.0], "radius_m": 100.0, "top_m": 20.0}
    assert simulate(scenario, plan, ev(zone), ContinuePolicy).ok     # overflown at 60 m, above its ceiling


def trailing_plan(plan):
    """The same plan plus S02 flying the first half of S01's route 12 s behind it, then home."""
    out = copy.deepcopy(plan)
    out["routes"].append({"aircraft": "S02", "waypoints": [
        {"t": 12, "x": 0, "y": 20, "z": 0}, {"t": 22, "x": 0, "y": 20, "z": 60},
        {"t": 72, "x": 800, "y": 56, "z": 60}, {"t": 125, "x": 0, "y": 20, "z": 0}]})
    return out


def test_holding_in_front_of_a_follower_breaks_separation(scenario, plan):
    two = trailing_plan(plan)
    assert simulate(scenario, two, ev(), ContinuePolicy).ok
    run = simulate(scenario, two, ev(), by_aircraft({"S01": "hold"}))
    assert any(f.startswith("R8") for f in run.failed)


def test_the_oracle_keeps_separation_when_one_aircraft_turns_back_into_another(scenario, plan):
    two = trailing_plan(plan)
    zone = {"kind": "popup_zone", "t": 35.0, "center": [1000.0, 70.0], "radius_m": 100.0, "top_m": 200.0}
    events = ev(zone, t_loss=30.0)
    assert any(f.startswith("R8") or "pop-up" in f for f in simulate(scenario, two, events, ContinuePolicy).failed)
    ora = simulate(scenario, two, events, oracle=True)
    assert ora.ok                                   # S01 retraces head-on into S02: one of them holds


def test_policy_errors_and_invalid_actions(scenario, plan):
    class Boom:
        def __init__(self, *a):
            pass

        def step(self, obs):
            raise RuntimeError("bug")
    run = simulate(scenario, plan, ev(), Boom)
    assert any("policy error" in f for f in run.failed)
    assert retention(run.points, bool(run.failed), 10.0) == 0.0
    silly = by_aircraft({"S01": "teleport", "L01": {"kind": "speed"}})
    run = simulate(scenario, plan, ev(), silly)
    assert run.invalid_actions >= 2 and run.crafts["S01"].tau == pytest.approx(CUT)   # an invalid action is a hold


def test_oversized_messages_are_dropped_and_not_counted(scenario, plan):
    class Chatty(ContinuePolicy):
        def step(self, obs):
            return {"kind": "continue"}, {"x": "y" * 70}
    run = simulate(scenario, plan, ev(), Chatty)
    assert run.messages == 0 and run.dropped_messages > 0


def make_craft(aid, pos):
    return SimpleNamespace(id=aid, pos=pos, active=True)


def test_message_delivery_follows_range_and_capacity():
    rng = random.Random(3)
    a, b = make_craft("A", (0, 0, 0)), make_craft("B", (400, 0, 0))
    crafts = {"A": a, "B": b}
    got = 0
    for _ in range(4000):
        inbox, heard = {"A": [], "B": []}, {"A": {}, "B": {}}
        simmod._deliver(crafts, [(a, {"p": 1}, 20)], inbox, heard, 0.0, 1000.0, 1000.0, rng)
        got += len(inbox["B"])
    assert got / 4000 == pytest.approx(0.95, abs=0.02)               # within half the range: base loss only
    got = 0
    for _ in range(4000):
        inbox, heard = {"A": [], "B": []}, {"A": {}, "B": {}}
        simmod._deliver(crafts, [(a, {"p": 1}, 20)], inbox, heard, 0.0, 533.3333, 1000.0, rng)
        got += len(inbox["B"])
    assert got / 4000 == pytest.approx(0.95 * 2 * (1 - 400 / 533.3333), abs=0.025)
    inbox, heard = {"A": [], "B": []}, {"A": {}, "B": {}}
    simmod._deliver(crafts, [(a, {"p": 1}, 20)], inbox, heard, 0.0, 399.0, 1000.0, rng)
    assert inbox["B"] == []                                           # beyond the range
    # capacity: 240 bytes offered to B at C = 60 B/s -> a quarter gets through
    senders = [make_craft(f"S{i}", (100 + i, 0, 0)) for i in range(4)]
    crafts = {s.id: s for s in senders}
    crafts["B"] = b
    b.pos = (100, 5, 0)
    got = 0
    for _ in range(3000):
        inbox, heard = {k: [] for k in crafts}, {k: {} for k in crafts}
        simmod._deliver(crafts, [(s, {"q": 2}, 60) for s in senders], inbox, heard, 0.0, 1000.0, 60.0, rng)
        got += len(inbox["B"])
    assert got / (3000 * 4) == pytest.approx(0.95 * 0.25, abs=0.02)


def test_messages_arrive_one_step_later_with_their_sender_and_time(scenario, plan):
    seen = []

    class Talker(ContinuePolicy):
        def __init__(self, scenario, plan, aid):
            self.aid = aid

        def step(self, obs):
            if self.aid == "L01":
                seen.extend((m["from"], m["sent_t"], obs["t"]) for m in obs["inbox"])
            return {"kind": "continue"}, ({"hi": 1} if self.aid == "S01" else None)
    simulate(scenario, plan, ev(), Talker, setting=(2000.0, 10000.0))
    assert seen and all(frm == "S01" and t_now == sent + 1 for frm, sent, t_now in seen)


def test_events_are_verified_by_simulation_and_deterministic():
    sc2 = Scenario.from_dict(generate("L2", 2))
    plan2 = greedy_plan(sc2)
    e1, e2 = make_events(sc2, plan2, 1), make_events(sc2, plan2, 1)
    assert e1 == e2 and make_events(sc2, plan2, 2) != e1
    assert all(e["t"] >= e1["t_loss"] for e in e1["events"])
    assert simulate(sc2, plan2, e1, oracle=True).ok
    assert not simulate(sc2, plan2, e1, ContinuePolicy).ok
    assert oracle_points(sc2, plan2, e1) == e1["oracle_points"]


def test_the_oracle_on_the_events_of_several_levels_never_fails():
    for level, seed in (("L1", 0), ("L2", 5), ("L3", 1)):
        s = Scenario.from_dict(generate(level, seed))
        plan_x = greedy_plan(s)
        events = make_events(s, plan_x, 3)
        assert simulate(s, plan_x, events, oracle=True).ok


def test_retention_is_capped_and_zero_after_a_failure():
    assert retention(50.0, False, 100.0) == 0.5
    assert retention(150.0, False, 100.0) == 1.0
    assert retention(80.0, True, 100.0) == 0.0


def test_evaluate_cases_and_the_leaderboard_score(scenario, plan):
    far_zone = {"kind": "popup_zone", "t": 60.0, "center": [3000.0, 3000.0], "radius_m": 100.0, "top_m": 200.0}
    cases = [(scenario, plan, ev(far_zone))]
    quiet = evaluate_cases(cases, ContinuePolicy, seeds=2)
    assert quiet["retention"] == 1.0 and quiet["failures"] == 0 and quiet["s_loss"] == 1.0
    chatty = evaluate_cases(cases, BroadcastSensePolicy, seeds=2)
    assert chatty["retention"] == 1.0 and chatty["messages_per_aircraft_per_min"] > 0
    assert chatty["s_loss"] == pytest.approx(1.0 - 0.002 * chatty["messages_per_aircraft_per_min"])
    hits = [(scenario, plan, ev({"kind": "reclassify", "t": 70.0, "contact": "C01"}))]
    blind = evaluate_cases(hits, ContinuePolicy, seeds=2, oracles=[60.0])
    assert blind["retention"] == 0.0 and blind["failures"] == 2 and blind["s_loss"] == 0.0


def test_sizing_grid_and_frontier(scenario, plan):
    far_zone = {"kind": "popup_zone", "t": 60.0, "center": [3000.0, 3000.0], "radius_m": 100.0, "top_m": 200.0}
    cases = [(scenario, plan, ev(far_zone))]
    grid = dict(seeds=1, ranges=(500.0, 1000.0), capacities=(100.0, 200.0))
    free = sizing(cases, ContinuePolicy, **grid)
    assert free["sizing_score"] == 1.0 and free["frontier"] == {"500": 100.0, "1000": 100.0}
    assert set(free["cells"]) == {"500x100", "500x200", "1000x100", "1000x200"}
    held = sizing(cases, HoldPolicy, **grid)
    assert held["sizing_score"] == 0.0 and held["frontier"] == {"500": None, "1000": None}


def test_policy_files_load_and_the_cli_runs_end_to_end(tmp_path, capsys):
    sc_path, plan_path, ev_path = tmp_path / "s.json", tmp_path / "p.json", tmp_path / "e.json"
    assert cli_main(["generate", "L2", "3", "-o", str(sc_path)]) == 0
    assert cli_main(["baseline", str(sc_path), "-o", str(plan_path)]) == 0
    assert cli_main(["events", str(sc_path), str(plan_path), "--seed", "2", "-o", str(ev_path)]) == 0
    assert json.loads(ev_path.read_text())["events"]
    policy = tmp_path / "policy.py"
    policy.write_text("class Policy:\n    def __init__(self, scenario, plan, aircraft_id):\n        pass\n"
                      "    def step(self, obs):\n        return {'kind': 'return'}, None\n")
    assert load_policy(str(policy)) is not None
    assert cli_main(["linkloss", str(sc_path), str(plan_path), str(ev_path), str(policy), "--seeds", "1"]) == 0
    out = capsys.readouterr().out
    assert "retention" in out and "S_loss" in out
    assert cli_main(["linkloss", str(sc_path), str(plan_path), str(ev_path), "continue", "--seeds", "1",
                     "--setting", "500,100"]) == 0


def test_an_aircraft_that_runs_out_of_energy_is_lost_without_a_failure(scenario_dict, plan):
    scenario_dict["aircraft"][0]["battery_pct"] = 20          # 20 Wh: enough for the plan, not for hovering for ever
    sc2 = Scenario.from_dict(scenario_dict)
    assert evaluate(sc2, plan).valid
    run = simulate(sc2, plan, ev(), HoldPolicy)
    assert "S01" in run.lost and run.ok and run.crafts["S01"].end_kind == "lost"


def test_the_confirmation_margin_is_checked_on_real_times(scenario, plan):
    # S01 at 0.875 of its speed finishes the dwell at t = 130 s, only 5 s before L01 engages at 135 s
    late = by_aircraft({"S01": {"kind": "speed", "scale": 0.875}})
    run = simulate(scenario, plan, ev(), late)
    assert any("R4" in f for f in run.failed)
    early = by_aircraft({"S01": {"kind": "speed", "scale": 0.95}})        # done at 123 s, 12 s before
    assert simulate(scenario, plan, ev(), early).ok


def test_all_or_nothing_engagement_is_checked_on_real_times(scenario):
    plan2 = greedy_plan(scenario)
    assert evaluate(scenario, plan2).valid and "C04" in evaluate(scenario, plan2).served
    base = simulate(scenario, plan2, ev(), ContinuePolicy)
    assert base.ok and "C04" in base.served and len(base.engagements["C04"]) == 2
    partner = next(a for a, _ in base.engagements["C04"])
    # one of the two goes home: the other still engages, and nothing is served for the contact
    one_short = simulate(scenario, plan2, ev(t_loss=20.0), by_aircraft({partner: "return"}))
    assert one_short.ok and "C04" not in one_short.served and len(one_short.engagements["C04"]) == 1
    # one of the two arrives 30 s late: outside the 20 s synchronisation window
    late = simulate(scenario, plan2, ev(t_loss=20.0), by_aircraft({partner: lambda o: "hold" if o["t"] < 50 else "continue"}))
    assert "C04" not in late.served and len(late.engagements["C04"]) == 2


def test_events_hold_on_many_seeds():
    checked = 0
    for seed in range(12):
        s = Scenario.from_dict(generate("L2", seed))
        plan_x = greedy_plan(s)
        events = make_events(s, plan_x, 5)
        assert all(e["t"] >= events["t_loss"] + 5 - 1e-9 for e in events["events"])
        assert simulate(s, plan_x, events, oracle=True).ok
        assert not simulate(s, plan_x, events, ContinuePolicy).ok
        checked += 1
    assert checked == 12


def test_the_sizing_bar_is_a_retention_of_090_and_no_failed_run(scenario, plan, monkeypatch):
    from fleetkit.linkloss import score as scoremod
    answers = iter([
        {"retention": 0.90, "failures": 0},       # meets (>= 0.9)
        {"retention": 0.89, "failures": 0},       # below the bar
        {"retention": 0.97, "failures": 1},       # one failed run: does not meet
        {"retention": 1.00, "failures": 0},
    ])
    monkeypatch.setattr(scoremod, "evaluate_cases", lambda *a, **k: dict(next(answers)))
    monkeypatch.setattr(scoremod, "oracle_points", lambda *a: 1.0)
    res = scoremod.sizing([(scenario, plan, ev())], ContinuePolicy, seeds=1, ranges=(500.0, 1000.0), capacities=(100.0, 200.0))
    meets = {k: v["meets"] for k, v in res["cells"].items()}
    assert meets == {"500x100": True, "500x200": False, "1000x100": False, "1000x200": True}
    assert res["sizing_score"] == 0.5 and res["frontier"] == {"500": 100.0, "1000": 200.0}
