# Alta Ares fleet orchestration challenge (EDTH hackathon, Nov 2026)

A planner that tasks ISR scouts and FPV effectors against contacts under the 10 mission rules,
plus a link-loss policy that keeps the plan safe when the ground link is cut.

* **Solution and write-up:** [`fleet-kit/handin/`](fleet-kit/handin/) (start with its [README](fleet-kit/handin/README.md)).
* **Results:** x1.88 the greedy baseline on unseen scenarios (x3 on 100-aircraft scenarios), 0 invalid plans;
  with the link cut, 97.8 % of the mission kept and 0 failures over 3 840 simulated runs, at about 4 messages
  per aircraft per minute.
* **Demos:** open the pages in [`demo/`](demo/) in a browser.
* Python standard library only. The challenge kit (`fleet-kit/fleetkit/`) comes from
  [Alta-Ares/AA-Hackathon-EDTH-202611](https://github.com/Alta-Ares/AA-Hackathon-EDTH-202611).

Run a scenario:

```sh
cd fleet-kit
PYTHONPATH=. python3 handin/planner.py examples/L2-7.json plan.json
python3 -m fleetkit validate examples/L2-7.json plan.json   # -> valid
python3 -m fleetkit score examples/L2-7.json plan.json
```
