"""Command line: generate scenarios, validate and score plans, run the baseline, draw a plan."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from typing import List, Optional

from .baseline import greedy_plan
from .generator import LEVELS, generate
from .model import Scenario, load_json, save_json
from .scorer import evaluate
from .viz import render_svg

HAS_LINKLOSS = importlib.util.find_spec("fleetkit.linkloss") is not None   # the link-loss part ships separately


def _seeds(text: str) -> List[int]:
    if "-" in text:
        lo, hi = text.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in text.split(",")]


def _load(path: str) -> Scenario:
    return Scenario.from_dict(load_json(path))


def cmd_generate(args) -> int:
    scenario = generate(args.level, args.seed, ensure_feasible=not args.no_check)
    save_json(scenario, args.output) if args.output else print(json.dumps(scenario, indent=1))
    return 0


def cmd_validate(args) -> int:
    result = evaluate(_load(args.scenario), load_json(args.plan))
    if result.valid:
        print("valid")
        return 0
    for v in result.violations:
        print(v)
    print(f"INVALID: {len(result.violations)} violation(s); the plan scores 0")
    return 1


def cmd_score(args) -> int:
    r = evaluate(_load(args.scenario), load_json(args.plan), verify=args.verify)
    if not r.valid:
        for v in r.violations:
            print(v)
        print("INVALID: score 0")
        return 1
    print(f"score {r.score:.2f}  (points {r.points:.1f}, energy {r.energy_wh:.1f} Wh, effectors used {r.effectors_used})")
    print(f"served: {', '.join(r.served) or 'none'}" + (f"   verified: {', '.join(r.verified)}" if args.verify else ""))
    return 0


def cmd_baseline(args) -> int:
    plan = greedy_plan(_load(args.scenario))
    save_json(plan, args.output) if args.output else print(json.dumps(plan, indent=1))
    return 0


def cmd_viz(args) -> int:
    scenario = _load(args.scenario)
    plan = load_json(args.plan) if args.plan else None
    if args.animate:
        from .viewer.hero import render_hero
        if plan is None:
            print("--animate needs a plan")
            return 2
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(render_hero(scenario, plan, **({"title": args.title} if args.title else {})))
        print(f"wrote {args.output}")
        return 0
    title = ""
    if plan is not None:
        r = evaluate(scenario, plan)
        title = f"{scenario.level} seed {scenario.seed}: " + (f"score {r.score:.1f}" if r.valid else "INVALID plan")
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(render_svg(scenario, plan, title))
    print(f"wrote {args.output}")
    return 0


def cmd_stats(args) -> int:
    rows = []
    start = time.time()
    for seed in _seeds(args.seeds):
        scenario = Scenario.from_dict(generate(args.level, seed, ensure_feasible=False))
        r = evaluate(scenario, greedy_plan(scenario))
        potential = sum(c.points for c in scenario.contacts if c.cls in ("hostile", "unknown"))
        rows.append((seed, r.valid, r.score, r.points / potential if potential else 0.0, r.effectors_used))
    print(f"{args.level}: {len(rows)} scenarios in {time.time() - start:.1f}s")
    print(f"  baseline plans valid: {sum(1 for r in rows if r[1])}/{len(rows)}")
    print(f"  baseline score: mean {statistics.mean(r[2] for r in rows):.1f}, "
          f"min {min(r[2] for r in rows):.1f}, max {max(r[2] for r in rows):.1f}")
    print(f"  share of available points served: mean {statistics.mean(r[3] for r in rows):.2f}")
    return 0


def cmd_events(args) -> int:
    from .linkloss.events import make_events
    events = make_events(_load(args.scenario), load_json(args.plan), args.seed)
    save_json(events, args.output) if args.output else print(json.dumps(events, indent=1))
    return 0


def cmd_linkloss(args) -> int:
    from .linkloss.policies import load_policy
    from .linkloss.score import LEADERBOARD, evaluate_cases, sizing
    scenario, plan, events = _load(args.scenario), load_json(args.plan), load_json(args.events)
    factory = load_policy(args.policy)
    cases = [(scenario, plan, events)]
    if args.sizing:
        result = sizing(cases, factory, seeds=args.seeds)
        print("retention by range (rows) and capacity (columns, B/s); * = meets the bar (>= 0.9, no failure)")
        caps = sorted({float(k.split("x")[1]) for k in result["cells"]})
        print("range    " + "".join(f"{c:>9g}" for c in caps))
        for r in sorted({float(k.split("x")[0]) for k in result["cells"]}):
            row = "".join(f"{result['cells'][f'{r:g}x{c:g}']['retention']:>8.2f}{'*' if result['cells'][f'{r:g}x{c:g}']['meets'] else ' '}" for c in caps)
            print(f"{r:>6g}  {row}")
        print(f"sizing score {result['sizing_score']:.2f}; frontier (smallest capacity that meets the bar, per range): {result['frontier']}")
        return 0
    setting = LEADERBOARD if not args.setting else tuple(float(v) for v in args.setting.split(","))
    r = evaluate_cases(cases, factory, setting, seeds=args.seeds)
    print(f"setting {setting[0]:g} m, {setting[1]:g} B/s, {r['runs']} runs: retention {r['retention']:.3f}, "
          f"failed runs {r['failures']}, messages {r['messages_per_aircraft_per_min']:.1f} per aircraft per minute, "
          f"S_loss {r['s_loss']:.3f}, policy {r['ms_per_call']:.3f} ms per call")
    for line in r["failure_examples"]:
        print("  failure:", line)
    return 0


def cmd_view(args) -> int:
    from .viewer import Viewer
    scenario = _load(args.scenario)
    plan = load_json(args.plan) if args.plan else None
    events = load_json(args.events) if getattr(args, "events", None) else None
    policy = None
    if getattr(args, "policy", None):
        from .linkloss.policies import load_policy
        policy = load_policy(args.policy)
    if (events is None) != (policy is None):
        print("a link-loss replay needs both --events and --policy")
        return 2
    setting = tuple(float(v) for v in args.setting.split(",")) if getattr(args, "setting", None) else (1000.0, 200.0)
    viewer = Viewer(scenario, plan, events=events, policy=policy, setting=setting, run_seed=getattr(args, "run_seed", 0), title=args.title)
    if args.layers:
        viewer.add_layers(load_json(args.layers))
    path = viewer.save(args.output)
    print(f"wrote {path}")
    if args.open:
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(path))
    return 0


def cmd_validation_set(args) -> int:
    from .validation import VALIDATION_SET, scenario_id
    os.makedirs(args.output, exist_ok=True)
    for level, seed in VALIDATION_SET:
        name = scenario_id(level, seed)
        save_json(generate(level, seed), os.path.join(args.output, name + ".json"))
        print(f"wrote {os.path.join(args.output, name + '.json')}")
    print("Make a plan for each, then: python3 -m fleetkit submit-all <folder of plans named <scenario>.json>")
    return 0


def cmd_board_login(args) -> int:
    import getpass
    from .submit import save_config
    token = args.token or getpass.getpass("token (typed text stays hidden): ").strip()
    if not token:
        print("no token given")
        return 1
    print(f"saved to {save_config(args.server, args.team, token)}")
    return 0


def _submit_one(scenario_name: str, plan_path: str, cfg: dict, force: bool) -> bool:
    from .submit import post_plan
    from .validation import parse_scenario_id
    level, seed = parse_scenario_id(scenario_name)
    plan = load_json(plan_path)
    local = evaluate(Scenario.from_dict(generate(level, seed)), plan)
    if not local.valid and not force:
        print(f"{scenario_name}: not sent, your plan is invalid ({local.violations[0]}); use --force to send it anyway")
        return False
    answer = post_plan(cfg["server"], cfg["team"], cfg["token"], scenario_name, plan)
    if answer["valid"]:
        best = " (new best)" if answer.get("improved") else f" (your best stays {answer['best']:.1f})"
        print(f"{scenario_name}: score {answer['score']:.1f}{best}")
    else:
        print(f"{scenario_name}: rejected, {answer['violations'][0] if answer['violations'] else 'invalid plan'}")
    return bool(answer["valid"])


def _board_config(args) -> dict:
    from .submit import load_config
    cfg = load_config()
    for key in ("server", "team", "token"):
        if getattr(args, key, None):
            cfg[key] = getattr(args, key)
    missing = [k for k in ("server", "team", "token") if not cfg.get(k)]
    if missing:
        raise SystemExit("missing " + ", ".join(missing) + ": run `python3 -m fleetkit board-login --server URL --team NAME --token TOKEN`")
    return cfg


def cmd_submit(args) -> int:
    try:
        ok = _submit_one(args.scenario, args.plan, _board_config(args), args.force)
    except (RuntimeError, ValueError) as error:
        print(error)
        return 1
    return 0 if ok else 1


def cmd_submit_all(args) -> int:
    from .validation import validation_ids
    cfg = _board_config(args)
    sent = 0
    for name in validation_ids():
        path = os.path.join(args.folder, name + ".json")
        if not os.path.exists(path):
            print(f"{name}: no file {path}, skipped")
            continue
        try:
            sent += _submit_one(name, path, cfg, args.force)
        except (RuntimeError, ValueError) as error:
            print(f"{name}: {error}")
    print(f"{sent} plans accepted")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point of `python -m fleetkit`."""
    parser = argparse.ArgumentParser(prog="fleetkit", description="Fleet orchestration starter kit")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("generate", help="generate a scenario")
    p.add_argument("level", choices=list(LEVELS))
    p.add_argument("seed", type=int)
    p.add_argument("-o", "--output")
    p.add_argument("--no-check", action="store_true", help="skip the check that a positive plan exists")
    p.set_defaults(func=cmd_generate)
    p = sub.add_parser("validate", help="check a plan against the ten rules")
    p.add_argument("scenario")
    p.add_argument("plan")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("score", help="score a plan")
    p.add_argument("scenario")
    p.add_argument("plan")
    p.add_argument("--verify", action="store_true", help="apply the optional verification bonus")
    p.set_defaults(func=cmd_score)
    p = sub.add_parser("baseline", help="run the greedy baseline")
    p.add_argument("scenario")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_baseline)
    p = sub.add_parser("viz", help="draw a scenario (and a plan) as SVG")
    p.add_argument("scenario")
    p.add_argument("plan", nargs="?")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--animate", action="store_true", help="an animated SVG of the plan (a README hero)")
    p.add_argument("--title", help="heading of the animated SVG")
    p.set_defaults(func=cmd_viz)
    p = sub.add_parser("stats", help="run the baseline on many seeds of a level")
    p.add_argument("level", choices=list(LEVELS))
    p.add_argument("--seeds", default="0-9")
    p.set_defaults(func=cmd_stats)
    if HAS_LINKLOSS:
        p = sub.add_parser("events", help="draw link-loss events against a plan (verified by simulation)")
        p.add_argument("scenario")
        p.add_argument("plan")
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("-o", "--output")
        p.set_defaults(func=cmd_events)
        p = sub.add_parser("linkloss", help="fly a plan with a policy after the link is cut, and score the policy")
        p.add_argument("scenario")
        p.add_argument("plan")
        p.add_argument("events")
        p.add_argument("policy", help="path to policy.py, or a baseline: continue, hold, return, broadcast")
        p.add_argument("--setting", help="range in m and capacity in B/s, e.g. 1000,200 (default: the leaderboard setting)")
        p.add_argument("--seeds", type=int, default=5, help="communication seeds per setting")
        p.add_argument("--sizing", action="store_true", help="evaluate the whole grid of settings")
        p.set_defaults(func=cmd_linkloss)
    p = sub.add_parser("validation-set", help="write the public validation scenarios of the live board")
    p.add_argument("-o", "--output", default="validation")
    p.set_defaults(func=cmd_validation_set)
    p = sub.add_parser("board-login", help="save the server address, your team name and token for `submit`")
    p.add_argument("--server", required=True)
    p.add_argument("--team", required=True)
    p.add_argument("--token", help="your token (leave it out to be asked: it then stays out of your shell history)")
    p.set_defaults(func=cmd_board_login)
    for name, text in (("submit", "send one plan to the live validation board"), ("submit-all", "send every plan of a folder to the live board")):
        p = sub.add_parser(name, help=text)
        if name == "submit":
            p.add_argument("scenario", help="a validation scenario, like L3-301")
            p.add_argument("plan")
        else:
            p.add_argument("folder", help="plans named like the scenarios: L1-101.json, L2-201.json, ...")
        for key in ("server", "team", "token"):
            p.add_argument("--" + key, help="default: from board-login or FLEETKIT_BOARD_" + key.upper())
        p.add_argument("--force", action="store_true", help="send even a plan that is invalid locally")
        p.set_defaults(func=cmd_submit if name == "submit" else cmd_submit_all)
    p = sub.add_parser("view", help="a self-contained HTML viewer: replay a plan or a link-loss run")
    p.add_argument("scenario")
    p.add_argument("plan", nargs="?")
    p.add_argument("-o", "--output", default="view.html")
    if HAS_LINKLOSS:
        p.add_argument("--events", help="link-loss events (with --policy: replay the run)")
        p.add_argument("--policy", help="policy.py or a baseline name (continue, hold, return, broadcast)")
        p.add_argument("--setting", help="communication setting, e.g. 1000,200")
        p.add_argument("--run-seed", type=int, default=0, help="seed of the random message losses")
    p.add_argument("--layers", help="a JSON file of your own layers to draw (see the viewer notes)")
    p.add_argument("--title")
    p.add_argument("--open", action="store_true", help="open the page in the browser")
    p.set_defaults(func=cmd_view)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
