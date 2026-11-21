# Fleet orchestration: plan, with and without comms

Hand-in folder: `planner.py` (Plan it), `policy.py` (link loss), `aaplan/` (the planner's modules).
Python standard library only. `python3 check_handin.py` and `python3 check_policy.py` run it the way
the organisers do.

## 1. The planner (`planner.py`)

The problem splits cleanly once you look at what is scarce:

* **Effectors are cheap to schedule.** They are one-way, waiting on the pad costs nothing, so an
  effector can take off whenever needed and arrive at any chosen time. What matters is *how many*
  of each subtype are left, and their energy.
* **Scouts are the bottleneck.** A scout flies one sortie, must come home, and every hostile needs
  a completed observation at least 10 s before the strike, inside the contact's window.

So the planner works in three stages.

### Stage 1: scout tours as a team orienteering problem with time windows (LNS)

* Each candidate contact gets a **net value**: points minus the expected cost of the strike
  (`c_eff` per effector + λ x the effector energy to fly there). Hostiles inside the collateral
  radius, contacts that no effector can reach inside their window, and contacts worth less than
  their strike cost are dropped up front.
* Obstacle-aware distances (visibility graph around zones and protected discs) are precomputed at
  three cruise levels (35 m, 76 m, 121 m: below, between and above most zone ceilings).
* A tour is evaluated in O(length): travel minus the observation reach, waits absorbed by stretched
  legs, departure pushed as late as the windows allow (waiting on the ground is free), energy and
  horizon checked. The model is deliberately conservative so the exact rebuild almost always fits.
* **Large neighbourhood search**: greedy insertion with cached best positions, then thousands of
  ruin-and-recreate moves (random, spatially related, whole tour, change of cruise level), 2-opt,
  simulated-annealing acceptance, and random *shadow prices* on light/heavy effectors so the search
  learns which contacts are worth the scarce subtype.

### Stage 2: exact routes

* Scouts: observation points are chosen on the reach disc of each contact (looking one contact
  ahead), legs follow the obstacle-free polyline, climb-out and landing are steep and short so a
  low zone is never clipped, and the departure time is searched so the tour is conflict-free.
* Effectors: for each served hostile (best net value first), the cheapest effectors of each needed
  subtype are timed to strike after the confirmation, within the 20 s synchronisation window.
  Altitude level, approach bearing and strike time are searched, and the cheapest candidate that
  passes the exact separation check against every accepted route is kept.

### Stage 3: validation and repair

The whole plan goes through the official validator. Any violation removes the offending strike (or
tour) and the plan is re-validated; tours that serve nothing are dropped. The search is restarted
with different seeds and model settings while time remains (about 35 s), the best valid plan wins,
and the shipped greedy baseline is kept as a last-resort fallback. A run can never write an invalid
plan.

### Results (score, sum over scenarios)

| Set | Ours | Greedy baseline | Ratio |
|---|---:|---:|---:|
| Public validation set (8 scenarios) | RESULT_VAL | 2664 | RATIO_VAL |
| 40 generated scenarios (L1 to L4, seeds 1000 to 1009) | 22 253 | 12 308 | x1.81 |
| UNSEEN_LINE |

0 invalid plans, longest run under 40 s. On L4 we serve nearly every hostile that is reachable at
all: what is left is either inside a collateral radius, out of every scout's range, or worth less than
its strike.

## 2. Link loss (`policy.py`): how much comms does the plan need?

**Answer: almost none, if every aircraft carries the plan.** Silence means "I am on my plan", and
every aircraft can predict every silent peer exactly. Only two facts cannot be inferred, so only
those are sent:

1. **"I observed C at t"**: a scout that completes an observation an effector still depends on
   (one planned after the cut) sends it a few times; effectors of that target relay it once.
   An effector waiting for one freezes a few seconds before its group's first planned strike, so
   the whole group freezes in its planned formation, and resumes together, shifted so the strike
   is still at least 10 s after the observation. No confirmation means no strike: a silent failed
   scout can never cause an R4 violation.
2. **"My clock is now X, moving at rate r"**: an aircraft that leaves its schedule (hover, slow
   down, turn back) says so, so peers can predict where it really is. A hovering aircraft calls
   more often only while someone that may not have heard is about to pass by.

Everything else is local:

* pop-up zones and reclassified contacts are sensed 300 m out, before any route can enter or any
  dive can start; the aircraft aborts and hovers (losing a battery is not a failure, flying back
  through traffic might be);
* **right of way**: a hovering aircraft is a fixed obstacle that everybody avoids; moving
  deviators yield to on-plan traffic and to lower ids; on-plan traffic only reacts to deviators it
  has heard of. Each candidate action is checked a few seconds ahead against the predicted positions
  of the aircraft whose plans pass nearby (spatial index of all planned trajectories).

Messages are 7 to 14 bytes (`[rate, clock]`, `[contact, time, 0]`), so a 50 B/s receiver is never
saturated.

### Results

LINKLOSS_TABLE
