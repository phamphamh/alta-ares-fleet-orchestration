"""Runs your policy.py the way we will: on generated scenarios with a cut and events, next to the
shipped `broadcast` baseline. A policy that crashes, hangs or fails every run is reported here first.

    python3 check_policy.py                          # L2 and L3, two scenarios each
    python3 check_policy.py --levels L1,L2,L3 --seeds 0-3 --timeout 120

The real evaluation uses scenarios and events you have not seen, so do not tune to these.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT))

from fleetkit.baseline import greedy_plan  # noqa: E402
from fleetkit.generator import generate  # noqa: E402
from fleetkit.linkloss.events import make_events  # noqa: E402
from fleetkit.model import Scenario, save_json  # noqa: E402


def seeds(text):
    if "-" in text:
        lo, hi = text.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in text.split(",")]


def run(policy, files, extra, timeout):
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(KIT), "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-m", "fleetkit", "linkloss", *files, policy, "--seeds", "2", *extra]
    try:
        proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, cwd=HERE)
    except subprocess.TimeoutExpired:
        return f"timeout after {timeout:g} s"
    lines = proc.stdout.decode(errors="replace").strip().splitlines()
    if proc.returncode != 0:
        return "crash: " + " | ".join(lines[-3:])
    return lines[0].split(": ", 1)[1] if lines and ": " in lines[0] else " ".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="L2,L3")
    ap.add_argument("--seeds", default="0-1")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--policy", default=str(HERE / "policy.py"))
    a = ap.parse_args()
    bad = 0
    with tempfile.TemporaryDirectory(prefix="policy-") as tmp:
        for level in a.levels.split(","):
            for seed in seeds(a.seeds):
                data = generate(level, seed)
                sc = Scenario.from_dict(data)
                plan = greedy_plan(sc)
                events = make_events(sc, plan, seed + 1)
                files = [str(Path(tmp) / f"{level}-{seed}-{n}.json") for n in ("s", "p", "e")]
                save_json(data, files[0])
                save_json(plan, files[1])
                save_json(events, files[2])
                mine = run(a.policy, files, [], a.timeout)
                base = run("broadcast", files, [], a.timeout)
                bad += mine.startswith(("crash", "timeout"))
                print(f"{level}-{seed}  events {[e['kind'] for e in events['events']]}\n   yours:     {mine}\n   broadcast: {base}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
