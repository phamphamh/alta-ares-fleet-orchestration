# Fleet orchestration starter kit

A mixed fleet of ISR scouts and effector drones must be tasked against several contacts under written rules. This kit gives you the scenario generator, the rule validator, the scorer, a greedy baseline and an SVG viewer. Pure Python (3.9 or newer), standard library only: no install, no GPU, no hardware.

## Quick start

```sh
python3 -m fleetkit generate L2 7 -o scenario.json      # a scenario (levels L1 to L4)
python3 -m fleetkit baseline scenario.json -o plan.json # the greedy baseline plan
python3 -m fleetkit validate scenario.json plan.json    # the ten rules, with every violation listed
python3 -m fleetkit score scenario.json plan.json       # the score
python3 -m fleetkit viz scenario.json plan.json -o plan.svg   # open the SVG in a browser
```

Your job: write something that reads a scenario (JSON) and writes a plan (JSON) that scores better than the baseline. Any approach is fine: exact solver, heuristics, learning, a small local model. `python3 -m fleetkit stats L2 --seeds 0-19` shows how the baseline does across seeds.

## The world

- 3D, local metres (x east, y north, z up), flat ground. Time in seconds.
- **Scouts** observe contacts and must land back at their home. **Effectors** (light or heavy) are one-way: an engagement consumes them.
- **Contacts:** `hostile` (may be engaged, needs a given number of light and heavy effectors), `unknown` (observe only), `friendly` and `civilian` (never approached).
- **Zones** are no-fly cylinders with a ceiling: forbidden below `top_m`, overflyable above it.
- Everything is synthetic.

## Formats

A scenario and a plan are JSON; see `examples/L2-7.json` and `examples/L2-7.baseline.json`. A route is a list of waypoints `{t, x, y, z}` (arrival time and position); an aircraft holds `dwell_s` seconds at a waypoint, then leaves. A waypoint may carry `action` (`observe` or `engage`) and `target` (a contact id). The first waypoint is the aircraft's home; an effector's route ends with its engagement.

## The ten rules

A plan is valid only if all ten hold; an invalid plan scores 0. `validate` lists every violation.

| Id | Rule |
|---|---|
| R1 | Well-formed: right seed, known ids, one route per aircraft, times in order within the horizon, starts at home, effector routes end with an engagement |
| R2 | Kinematics: horizontal and vertical speed limits; altitude within the limits (except climb-out, landing and the final dive) |
| R3 | Energy: the route fits the usable battery energy; scouts end at home |
| R4 | Confirm before engage: a scout observation of the contact completed at least `confirm_margin_s` before the engagement |
| R5 | Authorisation: only effectors engage, only hostile contacts; scouts observe hostile or unknown contacts |
| R6 | Exclusion: no part of a route enters a zone below its ceiling or the protected area around a friendly or civilian contact |
| R7 | Collateral: a hostile contact close to a friendly or civilian contact is never engaged |
| R8 | Separation: airborne aircraft stay at least `d_sep_m` apart in 3D, except effectors engaging the same contact near it |
| R9 | Time windows: observations and engagements inside the contact's window |
| R10 | All-or-nothing: a contact is either not engaged or engaged by exactly the effectors it needs, within the synchronisation window |

All the numbers (`d_sep_m`, ranges, windows, ...) are in each scenario's `rules` block.

## Score

```
score = Σ points of served contacts  −  λ · energy used (Wh)  −  μ · effectors consumed
```

**Optional add-on:** a scout observation of a hostile contact completed 10 to 120 s after its last engagement verifies the outcome and adds 25% to its points (`score ... --verify`).

## Link loss (optional second part)

What if the link to the ground is cut mid-mission? Write a policy that keeps the mission safe with what the aircraft sense and hear from each other, using as little communication as you can. Everything you need, with a simulator, baselines, a scorer and a sizing grid, is in [`LINKLOSS.md`](LINKLOSS.md).

```sh
python3 -m fleetkit events scenario.json plan.json --seed 1 -o events.json
python3 -m fleetkit linkloss scenario.json plan.json events.json broadcast
```

## See what your plan does

```sh
python3 -m fleetkit view scenario.json plan.json -o view.html --open
```

One self-contained page (no install, no network): a map you can pan and zoom, an altitude strip, a time scrubber, every aircraft's status and energy, the violations with a jump to the moment, the score breakdown. It also draws your own layers (candidate routes, a search tree, anything) so you do not have to build a viewer. See [`VIEWER.md`](VIEWER.md). `viz` still writes a plain SVG.

## Live validation board

Upload plans (not code) for eight public scenarios and watch a live board rank the teams: `python3 -m fleetkit validation-set -o validation`, then `board-login` with the address and token the organisers give you (leave `--token` out to be asked for it), then `python3 -m fleetkit submit-all my-plans/` (plans named `L1-101.json`, `L2-201.json`, ...). It is a validation set; the final ranking uses scenarios you have not seen. See [`LEADERBOARD.md`](LEADERBOARD.md).

## Tests

```sh
python3 -m pytest tests          # needs pytest
```
