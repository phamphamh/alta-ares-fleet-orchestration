"""Link-loss scoring: retention against the oracle, the leaderboard score and the sizing grid."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..model import Scenario
from .sim import simulate

MU = 0.002                       # cost per message per aircraft per minute (S)
THETA = 0.9                      # mean retention a grid cell must reach (S)
SEEDS = 5                        # communication seeds per setting (S)
RANGES = (250.0, 500.0, 1000.0, 2000.0)
CAPACITIES = (50.0, 100.0, 200.0, 400.0, 800.0)
LEADERBOARD = (1000.0, 200.0)

Case = Tuple[Scenario, dict, dict]   # scenario, plan, events


def oracle_points(scenario: Scenario, plan: dict, events: dict) -> float:
    """Points the full-information reference serves; the events are only usable if it does not fail."""
    result = simulate(scenario, plan, events, oracle=True)
    if result.failed or result.points <= 0:
        raise ValueError("the oracle fails or serves nothing on these events: " + "; ".join(result.failed[:2]))
    return result.points


def retention(points: float, failed: bool, v_oracle: float) -> float:
    """Returns min(1, V_exec / V_oracle), or 0 for a run that failed."""
    return 0.0 if failed else min(1.0, points / v_oracle)


def evaluate_cases(cases: Sequence[Case], factory: Callable, setting: Tuple[float, float] = LEADERBOARD,
                   seeds: int = SEEDS, max_seconds: Optional[float] = None,
                   oracles: Optional[Sequence[float]] = None) -> Dict[str, float]:
    """Runs a policy on every case and every communication seed at one setting.

    Returns mean retention, number of failed runs, messages per aircraft per minute, the
    leaderboard score `S_loss = retention - MU * messages`, and the policy compute per call.
    """
    oracles = list(oracles) if oracles is not None else [oracle_points(*c) for c in cases]
    rets: List[float] = []
    msgs: List[float] = []
    failures = 0
    calls = 0
    secs = 0.0
    reasons: List[str] = []
    for (sc, plan, ev), v_oracle in zip(cases, oracles):
        for k in range(seeds):
            run = simulate(sc, plan, ev, factory, setting=setting, run_seed=k, max_seconds=max_seconds)
            rets.append(retention(run.points, bool(run.failed), v_oracle))
            msgs.append(run.messages_per_aircraft_per_min)
            failures += bool(run.failed)
            calls += run.policy_calls
            secs += run.policy_seconds
            if run.failed and len(reasons) < 3:
                reasons.append(f"{sc.level}-{sc.seed}: {run.failed[0]}")
    mean_ret = sum(rets) / len(rets)
    mean_msgs = sum(msgs) / len(msgs)
    return {"retention": mean_ret, "failures": failures, "runs": len(rets), "messages_per_aircraft_per_min": mean_msgs,
            "s_loss": mean_ret - MU * mean_msgs, "ms_per_call": 1000.0 * secs / calls if calls else 0.0,
            "failure_examples": reasons}


def sizing(cases: Sequence[Case], factory: Callable, seeds: int = SEEDS, ranges: Sequence[float] = RANGES,
           capacities: Sequence[float] = CAPACITIES, max_seconds: Optional[float] = None) -> Dict[str, object]:
    """Evaluates a policy on the grid of settings; a cell meets the bar at mean retention >= THETA and no failure."""
    oracles = [oracle_points(*c) for c in cases]
    cells: Dict[str, Dict[str, float]] = {}
    for r in ranges:
        for cap in capacities:
            res = evaluate_cases(cases, factory, (r, cap), seeds, max_seconds, oracles)
            res["meets"] = res["retention"] >= THETA and res["failures"] == 0
            cells[f"{r:g}x{cap:g}"] = res
    meets = sum(1 for c in cells.values() if c["meets"])
    frontier = {}
    for r in ranges:
        ok = [cap for cap in capacities if cells[f"{r:g}x{cap:g}"]["meets"]]
        frontier[f"{r:g}"] = min(ok) if ok else None
    return {"cells": cells, "sizing_score": meets / len(cells), "frontier": frontier}
