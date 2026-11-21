"""Viewer tests that need the link-loss part (skipped when the kit ships without it)."""
import json

import pytest

pytest.importorskip("fleetkit.linkloss")

from fleetkit.cli import main as cli_main  # noqa: E402
from fleetkit.linkloss import simulate  # noqa: E402
from fleetkit.linkloss.policies import ContinuePolicy, HoldPolicy, ReturnPolicy  # noqa: E402
from fleetkit.viewer.model import build_model  # noqa: E402


def sample_at(model, aid, t):
    k = int(round(t / model["time"]["dt"]))
    tr = model["tracks"][aid]
    return tr["p"][k], tr["s"][k], tr["e"][k]


def test_a_link_loss_run_shows_actions_links_and_retention(scenario, plan):
    events = {"t_loss": 50.0, "events": [{"kind": "reclassify", "t": 70.0, "contact": "C01"}]}
    for policy, status, ret in ((HoldPolicy, "h", 0.0), (ReturnPolicy, "r", 0.0)):
        trace = {}
        run = simulate(scenario, plan, events, policy, trace=trace)
        m = build_model(scenario, plan, events=events, run=run, trace=trace, oracle_points=60.0)
        assert m["link"]["t_loss"] == 50.0 and m["link"]["retention"] == ret and m["link"]["events"] == events["events"]
        assert sample_at(m, "S01", 49)[1] == "f" and sample_at(m, "S01", 60)[1] == status
    trace = {}
    run = simulate(scenario, plan, events, ContinuePolicy, trace=trace)
    m = build_model(scenario, plan, events=events, run=run, trace=trace, oracle_points=60.0)
    assert m["plan"]["valid"] is False and m["link"]["retention"] == 0.0 and any("reclassified" in f for f in m["link"]["failed"])
    assert sample_at(m, "L01", 136)[1] == "x"


def test_the_trace_matches_what_the_run_did(scenario, plan):
    events = {"t_loss": 50.0, "events": []}

    class Talker(ContinuePolicy):
        def step(self, obs):
            return {"kind": "continue"}, {"hi": 1}
    trace = {}
    run = simulate(scenario, plan, events, Talker, trace=trace)
    assert len(trace["sent"]) == run.messages > 0
    assert all(t >= 50.0 for t, _ in trace["rates"]) and all(ok in (0, 1) for *_, ok, _ in trace["links"])
    assert {a for _, a, *_ in trace["links"]} <= {"S01", "L01"}
    run2 = simulate(scenario, plan, events, Talker, setting=(2000.0, 10000.0), trace=(t2 := {}))
    assert sum(ok for *_, ok, _ in t2["links"]) > 0.8 * len(t2["links"])          # 1 means delivered
    untouched = simulate(scenario, plan, events, Talker)
    assert untouched.messages == run.messages and untouched.points == run.points   # tracing changes nothing


def test_the_cli_replays_a_link_loss_run(tmp_path):
    sc_path, plan_path, ev_path = (tmp_path / n for n in ("s.json", "p.json", "e.json"))
    assert cli_main(["generate", "L2", "3", "-o", str(sc_path)]) == 0
    assert cli_main(["baseline", str(sc_path), "-o", str(plan_path)]) == 0
    assert cli_main(["events", str(sc_path), str(plan_path), "--seed", "2", "-o", str(ev_path)]) == 0
    out = tmp_path / "link.html"
    assert cli_main(["view", str(sc_path), str(plan_path), "--events", str(ev_path), "--policy", "broadcast", "-o", str(out)]) == 0
    assert '"link":{' in out.read_text()
    assert cli_main(["view", str(sc_path), str(plan_path), "--events", str(ev_path), "-o", str(tmp_path / "x.html")]) == 2
