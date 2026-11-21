# Fleet Orchestration

![A fleet of scouts and effectors flying a plan: zones, contacts, engagements](hero.svg)

A mixed fleet of scouts and effector drones sits at its bases. Contacts appear on the ground: some hostile, some unknown, some friendly or civilian, with no-fly zones scattered between them. There are more contacts than the fleet can serve. You write the planner that decides **who goes where, when, and in what order**, under ten written rules, and a validator tells you exactly which rule your plan breaks.

Scouts must confirm a contact before an effector may engage it. Effectors are one-way: an engagement consumes them. Aircraft differ in speed, endurance and battery, contacts differ in value and time window, zones forbid flying below their ceiling, and everything must stay 40 m apart. An invalid plan scores zero.

## The problem

- **The world.** 3D, local metres (x east, y north, z up), flat ground, time in seconds. Scenarios come from a seeded generator with four levels, from 5 to 100 aircraft.
- **The input.** A scenario (JSON): aircraft (type, base, speeds, battery), contacts (class, position, points, what they need, time window), zones, and the rules with all their numbers.
- **The output.** A plan (JSON): for every aircraft you use, a route of timed waypoints, with `observe` and `engage` actions on contacts.
- **The score.** Points of the contacts served, minus the energy used, minus a cost per effector consumed. Details and the ten rules are in [`fleet-kit/README.md`](fleet-kit/README.md).
- **Failure.** A plan that breaks any rule scores 0 for that scenario.

## What you build

Write a planner in [`fleet-kit/handin/planner.py`](fleet-kit/handin/planner.py): it reads `scenario.json` and writes `plan.json`. The template just calls the greedy baseline. Any approach is welcome: exact solver, heuristics, search, learning, a small local model, or a mix. Everything you need is in [`fleet-kit/`](fleet-kit/): generator, validator, scorer, baseline, viewer.

```sh
cd fleet-kit
python3 -m fleetkit generate L2 7 -o scenario.json       # a scenario (levels L1 to L4)
python3 -m fleetkit baseline scenario.json -o plan.json  # the greedy baseline
python3 -m fleetkit validate scenario.json plan.json     # every rule your plan breaks
python3 -m fleetkit score scenario.json plan.json
python3 -m fleetkit view scenario.json plan.json --open  # watch it fly
python3 handin/check_handin.py                           # runs your hand-in the way we will
```

**Optional second part:** the link to the ground is cut mid-mission. Write a policy that keeps the mission safe with what the aircraft sense and hear from each other, using as little communication as you can. See [`fleet-kit/LINKLOSS.md`](fleet-kit/LINKLOSS.md).

## Hypotheses

What you can rely on, in the public scenarios and in the ones you have not seen:

- The scenario is the only input of your planner. It is complete: nothing moves, nothing is hidden, every position and number is exact.
- Contacts and zones are static. Aircraft fly straight legs between waypoints at the speed the timing implies, within their limits.
- The rules and all their parameters are in each scenario's `rules` block and are the same for every scenario.
- The generator is public: you can make as many scenarios as you like, and tune on them.

## Limits

This is an exercise built for a weekend, not a mission planner:

- **Synthetic.** Local metres, no geography. Straight legs, no wind, no turning dynamics, no sensor noise, no communication.
- **A simple energy model.** Cruise power grows with the square of the speed (so there is a best-range speed) and climbing costs energy per metre. It is not a battery model.
- **A game of rules.** The ten rules are written to be checked exactly, not to be realistic. A plan the rules accept can still be silly; tell us if you find a loophole.

## Evaluation protocol

We run your planner on scenarios you have not seen, with the same rules, the same score and the same validator, in a fresh copy of your folder with the official `fleetkit` importable. Scoring on the public generator only tells you how you do on scenes you could tune for.

1. We call `python3 planner.py scenario.json plan.json`. Each run has **60 seconds**.
2. A run that crashes, times out, writes no plan or writes an invalid plan scores 0 for that scenario.
3. **Ranking:** the sum of your raw scores over all scenarios; ties are broken by total run time.

The optional verify add-on (`score --verify`) has its own board and does not change the ranking. A jury also looks at the soundness and presentation of your approach.

## Setup

Python 3.9 or newer, standard library only: no install, no GPU, no hardware.

```sh
git clone https://github.com/Alta-Ares/AA-Hackathon-EDTH-202611.git
cd AA-Hackathon-EDTH-202611/fleet-orchestration/fleet-kit
python3 -m fleetkit generate L1 0 -o scenario.json
python3 -m pytest tests          # optional; needs pytest
```

## See what your plan does

`python3 -m fleetkit view scenario.json plan.json --open` writes one offline page: a map with trails, an altitude strip, a time scrubber, every aircraft's status and energy, the violations with a jump to the moment, and the score breakdown. You can draw your own layers on it (candidate routes, a search tree): see [`fleet-kit/VIEWER.md`](fleet-kit/VIEWER.md). Use it in your demo too.

## Live validation board

While you work, see how your planner compares. Upload **plans** (not code) for eight public scenarios; the organisers' server validates and scores each one with the same validator as `fleetkit score`, and a live board shows the sum per level, the total, and the total against the baseline. It is a validation set: the final ranking is on scenarios you have not seen.

```sh
cd fleet-kit
python3 -m fleetkit board-login --server http://<address>:8080 --team "Your team" --token <token>   # address and token: from the organisers (leave --token out to be asked for it)
python3 -m fleetkit validation-set -o validation          # writes the 8 public scenarios
python3 -m fleetkit baseline validation/L1-101.json -o my-plans/L1-101.json   # or your own planner; name each plan after its scenario
python3 -m fleetkit submit-all my-plans/                  # or one at a time: submit L3-301 my-plans/L3-301.json
```

Open the address in a browser to watch the board. You appear as soon as one plan is accepted; the server keeps your best score per scenario, so a worse plan never hurts. The scenarios are `L1-101, L2-201, L2-202, L3-301, L3-302, L3-303, L4-401, L4-402`. More in [`fleet-kit/LEADERBOARD.md`](fleet-kit/LEADERBOARD.md).

## Hand-in

Put your planner in a folder with a file `planner.py` (the template is in `fleet-kit/handin/`). Python standard library only ; anything else you need goes inside your folder. `check_handin.py` runs your folder exactly the way we will, on generated scenarios.

For the link-loss part, add a file `policy.py` defining `Policy` in the same folder; `check_policy.py` checks it. It is scored separately and does not change the Plan it ranking.

Hand-in deadline November 22nd, midday.
