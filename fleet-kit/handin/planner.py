"""Alta Ares hand-in. We run:  python3 planner.py scenario.json plan.json

Scout tours are a team orienteering problem with time windows, solved by large neighbourhood
search; effector strikes are then timed and deconflicted against every accepted route with the
exact separation check; the whole plan is validated with the official validator and repaired.
The greedy baseline is kept as a fallback, and the best valid plan is written.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fleetkit.model import Scenario, load_json, save_json  # noqa: E402
from fleetkit.scorer import evaluate  # noqa: E402

BUDGET_S = float(os.environ.get("AA_BUDGET", "36"))


def main() -> None:
    t0 = time.monotonic()
    scenario = Scenario.from_dict(load_json(sys.argv[1]))
    verbose = os.environ.get("AA_VERBOSE")
    log = (lambda *a: print(*a, file=sys.stderr)) if verbose else None
    best, best_score = {"seed": scenario.seed, "routes": []}, 0.0
    try:
        from aaplan.solve import plan_scenario
        plan, res = plan_scenario(scenario, BUDGET_S, log=log)
        if plan is not None and res is not None and res.valid and res.score > best_score:
            best, best_score = plan, res.score
            save_json(best, sys.argv[2])
    except Exception as exc:  # never lose the run: fall back below
        if log:
            import traceback
            traceback.print_exc()
    if time.monotonic() - t0 < 44.0:
        try:
            from fleetkit.baseline import greedy_plan
            base = greedy_plan(scenario)
            r = evaluate(scenario, base)
            if r.valid and r.score > best_score:
                best, best_score = base, r.score
                if log:
                    log(f"baseline better: {r.score:.1f}")
        except Exception:
            pass
    save_json(best, sys.argv[2])


if __name__ == "__main__":
    main()
