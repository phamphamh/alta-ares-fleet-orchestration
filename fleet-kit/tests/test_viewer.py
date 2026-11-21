"""Tests for the viewer: the view model is exactly what the kit computed, and the page is self-contained."""
import json
import re

import pytest

from fleetkit.baseline import greedy_plan
from fleetkit.cli import main as cli_main
from fleetkit.energy import route_energy_wh
from fleetkit.generator import generate
from fleetkit.model import Scenario, parse_plan
from fleetkit.scorer import evaluate
from fleetkit.viewer import Viewer, render_html
from fleetkit.viewer.model import build_model, violation_pair, violation_time
from fleetkit.validator import Violation


def sample_at(model, aid, t):
    k = int(round(t / model["time"]["dt"]))
    tr = model["tracks"][aid]
    return tr["p"][k], tr["s"][k], tr["e"][k]


def test_a_scenario_alone_has_a_world_and_no_plan(scenario):
    m = build_model(scenario)
    assert m["plan"] is None and m["tracks"] == {} and len(m["aircraft"]) == 5 and len(m["world"]["contacts"]) == 4
    assert m["world"]["zones"] == [{"id": "Z01", "x": 1000, "y": 500, "r": 200, "top": 80}]


def test_the_verdict_and_the_score_are_the_kits(scenario, plan):
    m = build_model(scenario, plan)
    want = evaluate(scenario, plan)
    assert m["plan"]["valid"] and m["plan"]["score"] == round(want.score, 1)
    assert m["plan"]["points"] == want.points and m["plan"]["served"] == sorted(want.served)
    parts = m["plan"]["score_parts"]
    assert parts["points"] == want.points and parts["effector_cost"] == 10.0
    assert m["plan"]["violations"] == []


def test_tracks_follow_the_plan_and_the_statuses_tell_the_story(scenario, plan):
    m = build_model(scenario, plan)
    assert m["time"]["dt"] == 1.0
    assert all(len(tr["p"]) == len(tr["s"]) == len(tr["e"]) for tr in m["tracks"].values())
    p, s, e = sample_at(m, "S01", 0)
    assert p == [0, 0, 0] and s == "g" and e == 100
    p, s, _ = sample_at(m, "S01", 100)
    assert p == [1450, 100, 60] and s == "o"                      # observing C01 from t = 100 s
    assert sample_at(m, "S01", 110)[1] == "o" and sample_at(m, "S01", 125)[1] == "f"
    assert sample_at(m, "S01", 110)[0][2] == 60 and 0 < sample_at(m, "S01", 150)[0][2] < 60   # descending home
    assert sample_at(m, "S01", 200)[1] == "l" and sample_at(m, "S01", 200)[0] == [0, 0, 0]
    assert sample_at(m, "L01", 134)[1] == "f" and sample_at(m, "L01", 136)[1] == "x" and sample_at(m, "L01", 136)[0] is None
    assert sample_at(m, "L02", 190)[1] == "g"                      # not in the plan: stays home
    kinds = {(x["kind"], x["aid"], x["contact"]) for x in m["marks"]}
    assert kinds == {("observe", "S01", "C01"), ("engage", "L01", "C01")}
    assert m["served"] == {"C01": 135.0}


def test_energy_runs_down_by_the_route_energy(scenario, plan):
    m = build_model(scenario, plan)
    routes, _ = parse_plan(plan)
    ac = scenario.aircraft_by_id()["S01"]
    used = route_energy_wh(routes["S01"].waypoints, ac)
    e = m["tracks"]["S01"]["e"]
    assert e[0] == 100 and e == sorted(e, reverse=True)
    assert abs((100 - e[-1]) - used) <= 0.51


def test_an_invalid_plan_is_still_drawn_with_its_violations(scenario, plan):
    bad = dict(plan, seed=999)
    m = build_model(scenario, bad)
    assert m["plan"]["valid"] is False and m["plan"]["score_parts"] is None
    assert any(v["rule"] == "R1" for v in m["plan"]["violations"])
    assert m["tracks"]["S01"]["p"][100] == [1450, 100, 60]


def test_violation_times_and_pairs_are_read_from_the_messages(scenario, plan):
    v = Violation("R8", "S01 and L01 come within 12.0 m of each other (limit 40 m) around t = 57.5 s")
    assert violation_time(v, {}) == 57.5 and violation_pair(v.message) == ["S01", "L01"]
    routes, _ = parse_plan(plan)
    leg = Violation("R6", "leg 3 enters zone Z01", aircraft="S01")
    assert violation_time(leg, routes) == routes["S01"].waypoints[2].depart
    wp = Violation("R2", "waypoint 2 altitude 300 m is outside", aircraft="S01")
    assert violation_time(wp, routes) == routes["S01"].waypoints[2].t
    assert violation_time(Violation("R10", "engaged by nobody"), routes) is None


def test_the_page_is_self_contained_and_carries_the_model(scenario, plan):
    page = Viewer(scenario, plan, title="a <b> title").html()
    assert "<title>a &lt;b&gt; title</title>" in page
    assert not re.search(r"(?:src|href)\s*=\s*[\"']?https?:", page) and "@import" not in page and "fetch(" not in page
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    assert json.loads(data)["plan"]["score"] == round(evaluate(scenario, plan).score, 1)


def test_layers_are_normalised_and_cannot_break_out_of_the_page(scenario, plan):
    v = Viewer(scenario, plan)
    v.layer("mine", points=[(1, 2), (3, 4, "goal"), {"x": 5, "y": 6, "t0": 10}], lines=[[(0, 0), (5, 5)]],
            circles=[(10, 10, 50)], labels=[(0, 0, "</script><b>hi</b>")], color="#fff", t1=100)
    v.add_layers([{"name": "from json", "points": [[7, 8, "p"]]}])
    m = v.model()
    assert [l["name"] for l in m["layers"]] == ["mine", "from json"]
    assert {i["kind"] for i in m["layers"][0]["items"]} == {"point", "line", "circle", "label"}
    assert m["layers"][0]["items"][1] == {"kind": "point", "x": 3, "y": 4, "label": "goal"}
    assert m["layers"][0]["t1"] == 100
    page = render_html(m)
    assert page.count("</script>") == page.count("<script")          # the embedded label is escaped


def test_a_big_scenario_widens_the_time_step_and_stays_small():
    sc = Scenario.from_dict(generate("L4", 7))
    m = build_model(sc, greedy_plan(sc))
    assert m["time"]["dt"] == 2.0
    assert len(json.dumps(m)) < 2_000_000


def test_the_cli_writes_the_pages(tmp_path):
    sc_path, plan_path, layers = (tmp_path / n for n in ("s.json", "p.json", "l.json"))
    assert cli_main(["generate", "L2", "3", "-o", str(sc_path)]) == 0
    assert cli_main(["baseline", str(sc_path), "-o", str(plan_path)]) == 0
    layers.write_text(json.dumps([{"name": "mine", "lines": [[[0, 0], [100, 100]]]}]))
    out = tmp_path / "plan.html"
    assert cli_main(["view", str(sc_path), str(plan_path), "-o", str(out), "--layers", str(layers)]) == 0
    assert '"layers":[{"name":"mine"' in out.read_text()
    assert cli_main(["view", str(sc_path), "-o", str(tmp_path / "s.html")]) == 0


def test_a_contact_needing_two_effectors_is_served_when_the_last_one_engages(scenario):
    plan2 = greedy_plan(scenario)
    m = build_model(scenario, plan2)
    times = sorted(x["t"] for x in m["marks"] if x["kind"] == "engage" and x["contact"] == "C04")
    assert len(times) == 2 and times[0] < times[1]
    assert m["served"]["C04"] == times[1]


def test_the_animated_svg_is_well_formed_small_and_self_contained(tmp_path):
    import xml.etree.ElementTree as ET
    from fleetkit.viewer.hero import render_hero
    sc = Scenario.from_dict(generate("L3", 4))
    svg = render_hero(sc, greedy_plan(sc), title="A <b> & title")
    root = ET.fromstring(svg)                                          # well-formed XML
    ns = "{http://www.w3.org/2000/svg}"
    assert len(root.findall(f".//{ns}animate")) > 50 and "A &lt;b&gt; &amp; title" in svg
    assert not re.search(r"https?://(?!www\.w3\.org)", svg) and "<script" not in svg
    assert all(h.startswith("data:") for h in re.findall(r"<image[^>]*href=\"([^\"]*)\"", svg))     # only embedded images
    assert len(svg) < 400_000
    out = tmp_path / "hero.svg"
    s_path, p_path = tmp_path / "s.json", tmp_path / "p.json"
    cli_main(["generate", "L2", "3", "-o", str(s_path)])
    cli_main(["baseline", str(s_path), "-o", str(p_path)])
    assert cli_main(["viz", str(s_path), str(p_path), "--animate", "-o", str(out)]) == 0 and out.read_text().startswith("<svg")
    assert cli_main(["viz", str(s_path), "--animate", "-o", str(out)]) == 2


HOSTILE = '<img src=x onerror=alert(1)>'


def test_text_that_could_be_markup_is_refused_before_it_reaches_the_page(scenario, plan):
    from fleetkit.viewer.model import check_safe_text
    check_safe_text(scenario)                                          # the hand-written and generated ones pass
    for path, key in ((("contacts", 0), "id"), (("aircraft", 0), "id"), (("zones", 0), "id"), (("contacts", 0), "class")):
        from conftest import make_scenario_dict
        d = make_scenario_dict()
        d[path[0]][path[1]][key] = HOSTILE
        with pytest.raises(ValueError, match="viewer cannot show"):
            build_model(Scenario.from_dict(d), plan if key != "class" else None)
    d = make_scenario_dict()
    d["level"] = '"><script>x</script>'
    with pytest.raises(ValueError):
        build_model(Scenario.from_dict(d))
    with pytest.raises(ValueError, match="event kind"):
        build_model(scenario, events={"t_loss": 10, "events": [{"t": 1, "kind": HOSTILE}]})
    with pytest.raises(ValueError, match="event contact"):
        build_model(scenario, events={"t_loss": 10, "events": [{"t": 1, "kind": "reclassify", "contact": HOSTILE}]})


def test_the_svg_and_the_page_escape_what_a_scenario_file_says(scenario):
    from conftest import make_scenario_dict
    from fleetkit.viz import render_svg
    d = make_scenario_dict()
    d["contacts"][0]["id"] = HOSTILE
    d["zones"][0]["id"] = "<script>alert(1)</script>"
    svg = render_svg(Scenario.from_dict(d), None, title="<b>x</b>")
    assert "<img" not in svg and "<script" not in svg and "<b>" not in svg and "&lt;img" in svg
    page = render_html(build_model(scenario, title="</script><!-- x"))
    blob = page.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    assert "<!--" not in blob and "</" not in blob and json.loads(blob)["meta"]["title"] == "</script><!-- x"
    assert 'esc(s) { return String(s).replace(/[&<>"\']/g' in page                  # quotes are escaped too
