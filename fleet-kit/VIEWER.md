# The viewer

A page that shows what your plan does, so you can spend your hours on the planner. It is **read-only**: every verdict (valid or not, the score, the violations) comes from the kit's validator and scorer, and the page only draws it. One self-contained HTML file: no install, no network, works offline in any recent browser.

```sh
python3 -m fleetkit view scenario.json                      # just the scenario
python3 -m fleetkit view scenario.json plan.json -o view.html --open
```

## What you see

- **Map** (pan: drag, zoom: wheel, `F` fits it): no-fly zones with their ceilings, protected areas, contacts by class (hostile diamond, unknown ring, friendly square, civilian disc), aircraft as arrows pointing where they fly, trails, observation beams, a flash at every engagement, a green ring around each contact once it is served.
- **Time**: play or pause (`Space`), speed 1× to 32×, a scrubber with ticks for observations (dots), engagements (crosses) and violations (red triangles). `←` `→` step one second, with Shift ten.
- **Altitude strip**: altitude over time for every aircraft, with the allowed band; the selected aircraft is highlighted.
- **Aircraft** tab: status (on the ground, flying, observing, engaged, landed), altitude and energy left of each one; click to follow one.
- **Contacts** tab: class, points, what it needs, its window, and when it was served.
- **Issues** tab: every rule your plan breaks; click one to jump to the moment and the aircraft involved. An invalid plan is still drawn so you can see what went wrong.
- **Layers** tab: switch the built-in layers (zones, protected areas, observation and collateral ranges, trails) and your own.

## Draw your own layers

Candidate routes, a search tree, the cells you rejected: draw them on the same map.

```python
from fleetkit.model import Scenario, load_json
from fleetkit.viewer import Viewer

scenario = Scenario.from_dict(load_json("scenario.json"))
v = Viewer(scenario, load_json("plan.json"))
v.layer("candidates", lines=[[(0, 0), (900, 400), (1500, 380)]], color="#f778ba")
v.layer("goals", points=[(1500, 380, "C01 approach")], circles=[(1500, 380, 150)])
v.layer("timed", points=[{"x": 700, "y": 200, "label": "decision", "t0": 60, "t1": 90}])
v.save("view.html")
```

A layer takes `points` (x, y) or (x, y, label), `lines` (polylines of (x, y)), `circles` (x, y, radius in metres) and `labels` (x, y, text), each also as a dictionary (`color`, `t0`, `t1`, `width`, `r`). A layer, or one item, can be limited to a time window with `t0` and `t1` (seconds). From another language, write the same thing as JSON and pass it with `--layers layers.json`:

```json
[{"name": "candidates", "color": "#f778ba", "lines": [[[0, 0], [900, 400]]], "points": [[900, 400, "turn"]]}]
```

## Notes

- Positions are drawn to the metre, and large scenarios are sampled every 2 s, so the page stays small (about 0.4 MB at L3, 1.4 MB at L4).
- The page is for you and your demo: screenshots and screen recordings of it are welcome.
- It uses the Alta Ares look: Space Grotesk and Space Mono (SIL Open Font License, embedded so the page stays one offline file; the licences are in `fleetkit/viewer/fonts/`).
- With the link-loss part: `python3 -m fleetkit view scenario.json plan.json --events events.json --policy handin/policy.py` replays the whole run: the cut, the events, every aircraft's action (hold, return and speed are marked), the messages that were delivered or lost, and the retention.
