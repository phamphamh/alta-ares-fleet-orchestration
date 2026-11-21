"""Runs your hand-in the way we will: fresh copy of this folder, `python3 planner.py scenario.json plan.json`,
60 s limit, then the validator and the score. Prints one line per scenario and the baseline for comparison.

    python3 check_handin.py                      # L1 to L4, seeds 0 and 1
    python3 check_handin.py --levels L3,L4 --seeds 0-4 --timeout 60

The real evaluation uses scenarios you have not seen, so do not tune to these seeds.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent  # the folder holding `fleetkit`
sys.path.insert(0, str(KIT))

from fleetkit.baseline import greedy_plan  # noqa: E402
from fleetkit.generator import generate  # noqa: E402
from fleetkit.model import Scenario, save_json  # noqa: E402
from fleetkit.scorer import evaluate  # noqa: E402


def seeds(text):
    if "-" in text:
        lo, hi = text.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in text.split(",")]


def run_one(data, timeout):
    """Returns (status, score, seconds, note) for one scenario."""
    with tempfile.TemporaryDirectory(prefix="handin-") as tmp:
        work = Path(tmp) / "team"
        shutil.copytree(HERE, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        save_json(data, work / "scenario.json")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(KIT), "PYTHONDONTWRITEBYTECODE": "1", "HOME": tmp}
        start = time.monotonic()
        try:
            proc = subprocess.run([sys.executable, "planner.py", "scenario.json", "plan.json"], cwd=work, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "timeout", 0.0, float(timeout), f"over {timeout:g} s"
        took = time.monotonic() - start
        if proc.returncode != 0:
            tail = proc.stdout.decode(errors="replace").strip().splitlines()[-3:]
            return "crash", 0.0, took, f"exit code {proc.returncode}: " + " | ".join(tail)
        plan_path = work / "plan.json"
        if not plan_path.exists():
            return "no_plan", 0.0, took, "plan.json was not written"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            return "bad_json", 0.0, took, str(exc)[:80]
    result = evaluate(Scenario.from_dict(data), plan)
    if not result.valid:
        return "invalid", 0.0, took, str(result.violations[0])[:120]
    return "ok", result.score, took, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="L1,L2,L3,L4")
    ap.add_argument("--seeds", default="0-1")
    ap.add_argument("--timeout", type=float, default=60.0)
    a = ap.parse_args()
    total = base_total = 0.0
    bad = 0
    for level in a.levels.split(","):
        for seed in seeds(a.seeds):
            data = generate(level, seed)
            status, score, took, note = run_one(data, a.timeout)
            base = evaluate(Scenario.from_dict(data), greedy_plan(Scenario.from_dict(data))).score
            total += score
            base_total += base
            bad += status != "ok"
            print(f"{level}-{seed:<3d} {status:8s} score {score:8.1f}  baseline {base:8.1f}  {took:5.1f}s  {note}")
    print(f"\ntotal {total:.1f}  baseline {base_total:.1f}  failed runs {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
