# Link loss: when the ground goes silent (optional second part)

Your plan is flying. At time `t_loss` the link to the ground station is cut for the whole fleet. From then on each aircraft decides for itself, once per second, with what it can sense and what it hears from its peers. Your job: a **policy** that keeps the mission safe and as complete as possible, using as little communication as you can.

You can do this part with any plan (the baseline's is fine). The final evaluation uses our own reference plans, so a team that only does this part is not at a disadvantage.

```sh
python3 -m fleetkit generate L2 7 -o scenario.json
python3 -m fleetkit baseline scenario.json -o plan.json
python3 -m fleetkit events scenario.json plan.json --seed 1 -o events.json   # a cut and 2 to 3 events, verified feasible
python3 -m fleetkit linkloss scenario.json plan.json events.json broadcast   # a shipped baseline
python3 -m fleetkit linkloss scenario.json plan.json events.json handin/policy.py
python3 -m fleetkit linkloss scenario.json plan.json events.json handin/policy.py --sizing   # the whole grid
python3 -m fleetkit view scenario.json plan.json --events events.json --policy handin/policy.py -o run.html --open   # replay the run
```

## What happens

The simulator steps at 1 Hz. Until `t_loss` (a quarter to a half of the way through the plan) every aircraft follows its plan. After it, each aircraft calls your policy every second:

```python
class Policy:
    def __init__(self, scenario, plan, aircraft_id): ...      # scenario: a fleetkit Scenario; plan: the plan dictionary
    def step(self, obs):
        return {"kind": "continue"}, None                      # (action, message or None)
```

| Action | Effect |
|---|---|
| `{"kind": "continue"}` | follow the route |
| `{"kind": "speed", "scale": s}` | follow the route at `s` times the planned speed, `s` from 0.5 to 1 |
| `{"kind": "hold"}` | hover where you are (hover power, no progress) |
| `{"kind": "return"}` | retrace your route backwards to the start and land |

There is no other action: a policy cannot invent a route, so it cannot steer around a danger except by holding, slowing or turning back. An effector that reaches the last waypoint of its route engages at that moment; a scout completes an observation when it has been through the whole dwell. **Everything is judged on the real times**, so holding makes you late for good and a late engagement can miss its window or its synchronisation.

`fleetkit.linkloss.RouteClock(route).position(tau)` gives the planned position at planned time `tau`, to dead-reckon peers or look ahead along your own route.

### What you see (`obs`)

| Key | Meaning |
|---|---|
| `t`, `t_loss` | the clock, and when the link was cut |
| `pos`, `vel` | your position and velocity (always known) |
| `tau`, `next_wp`, `mode` | your place on the route clock, the next waypoint, `route` or `return` |
| `energy_left_wh` | usable energy left; at zero the aircraft is lost |
| `own_observed` | contacts whose observation you completed |
| `sensed` | events within 300 m of you (a contact that turned friendly, a new no-fly disc) |
| `inbox` | messages delivered this step: `{"from", "sent_t", "payload"}` |
| `last_heard` | the last message from each peer: `{peer: {"t", "payload"}}` |

Peers' positions are known only from messages, or by dead reckoning on the plan up to the cut.

### Events (after the cut, not announced)

| Event | Effect | Who senses it |
|---|---|---|
| `reclassify` | a hostile contact planned for engagement turns friendly; engaging it is a failure | aircraft within 300 m of it |
| `popup_zone` | a new no-fly disc (ceiling 200 m) on or near a route; entering it is a failure | aircraft within 300 m of it |
| `failure` | an aircraft stops and is removed | nobody directly |

### Failure and value

A run **fails** (retention 0) on: a separation violation (R8, with its usual exemption), entering a zone or a protected area (including a new disc), engaging a reclassified contact, an engagement with no completed observation by a scout at least `confirm_margin_s` earlier (R4 at execution time), or a policy that raises an exception. An aircraft that runs out of energy is lost: its tasks go unserved, which is not a failure.

A contact is served as in the plan scoring (hostile: exactly the needed effectors inside the window and the synchronisation window; unknown: observed inside its window), judged on the real times. `V_oracle` is the value of a full-information reference that knows every event the instant it happens and keeps separation.

```
retention = min(1, V_you / V_oracle)  if your run did not fail, else 0
S_loss    = mean retention  -  0.002 * messages per aircraft per minute
```

### Messages

One message per aircraft per second, any JSON, **at most 64 bytes** once written compactly (a longer one is not sent). A setting is a range `R_max` and a capacity `C` (bytes per second each receiver can take). A message from `i` to `j` at distance `d` is delivered, one step later, with probability `0.95 * p_range * p_cap`, where `p_range` is 1 up to `R_max/2`, then falls linearly to 0 at `R_max`, and `p_cap = min(1, C / bytes offered to j this step)`. The leaderboard setting is 1000 m and 200 B/s.

### Sizing

The scorer evaluates your policy on a grid of 20 settings (`R_max` 250, 500, 1000, 2000 m by `C` 50, 100, 200, 400, 800 B/s, 5 communication seeds each). A cell **meets the bar** if the mean retention is at least 0.9 and no run failed. Your **sizing score** is the share of cells that meet it; your **frontier** is the smallest capacity that meets the bar at each range. A design that holds up on a tight budget scores well; the frontier is part of what you hand in.

### Baselines

`continue` (blind, fails whenever an event hits), `hold`, `return` (safe, keeps only what was served before the cut) and `broadcast` (broadcasts its position and the dangers it senses, aborts on a sensed or heard danger: the floor to beat).

## Hand-in

A file `policy.py` defining `Policy`, in your hand-in folder next to `planner.py`. `python3 handin/check_policy.py` runs it on generated scenarios the way we will. The policy time per call is printed: keep it well under 50 ms (finalists can check it on a Raspberry Pi 5). Standard library only.
