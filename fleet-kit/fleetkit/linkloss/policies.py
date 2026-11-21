"""The baseline policies shipped with the kit (what is easy, and the floor to beat)."""
from __future__ import annotations

from typing import Optional, Tuple

from ..geometry import segment_enters_cylinder
from ..model import parse_plan
from .sim import RouteClock


class ContinuePolicy:
    """Follows the plan blindly."""

    def __init__(self, scenario, plan, aircraft_id):
        pass

    def step(self, obs):
        return {"kind": "continue"}, None


class HoldPolicy:
    """Hovers where it is when the link is cut."""

    def __init__(self, scenario, plan, aircraft_id):
        pass

    def step(self, obs):
        return {"kind": "hold"}, None


class ReturnPolicy:
    """Retraces its route home when the link is cut."""

    def __init__(self, scenario, plan, aircraft_id):
        pass

    def step(self, obs):
        return {"kind": "return"}, None


class BroadcastSensePolicy:
    """Broadcasts its position and the dangers it senses once per second; aborts on a sensed or heard danger.

    It aborts (returns home) when the route ahead crosses a pop-up zone it knows of, or when its
    own target has been reclassified. It does not coordinate with its peers beyond that.
    """

    def __init__(self, scenario, plan, aircraft_id):
        routes, _ = parse_plan(plan)
        self.clock = RouteClock(routes[aircraft_id])
        last = routes[aircraft_id].waypoints[-1]
        self.target = last.target if last.action == "engage" else None
        self.reclassified = set()
        self.zones = []

    def _learn(self, event):
        if event["kind"] == "reclassify":
            self.reclassified.add(event["contact"])
        elif event["kind"] == "popup_zone":
            zone = (round(event["center"][0]), round(event["center"][1]), round(event["radius_m"]), round(event["top_m"]))
            if zone not in self.zones:
                self.zones.append(zone)

    def step(self, obs):
        news = []
        for e in obs["sensed"]:
            before = (len(self.reclassified), len(self.zones))
            self._learn(e)
            if before != (len(self.reclassified), len(self.zones)):
                news.append(e)
        for m in obs["inbox"]:
            p = m["payload"]
            for c in p.get("rc", []):
                self.reclassified.add(c)
            for z in p.get("zn", []):
                if tuple(z) not in self.zones:
                    self.zones.append(tuple(z))
        message = {"p": [round(v) for v in obs["pos"]]}
        if self.reclassified:
            message["rc"] = sorted(self.reclassified)[:3]
        if self.zones:
            message["zn"] = [list(z) for z in self.zones[-1:]]
        abort = obs["mode"] == "return" or (self.target in self.reclassified)
        if not abort:
            k = self.clock.next_waypoint(obs["tau"])
            pts = [self.clock.position(obs["tau"])] + self.clock.pos[k:]
            abort = any(segment_enters_cylinder(a, b, (z[0], z[1]), z[2], z[3])
                        for z in self.zones for a, b in zip(pts, pts[1:]))
        return ({"kind": "return"} if abort else {"kind": "continue"}), message


BASELINES = {"continue": ContinuePolicy, "hold": HoldPolicy, "return": ReturnPolicy,
             "broadcast": BroadcastSensePolicy}


def load_policy(spec: str):
    """Returns a policy factory from a baseline name (continue, hold, return, broadcast) or a path to a `policy.py`.

    The file must define a class `Policy(scenario, plan, aircraft_id)` with `step(obs) -> (action, message)`.
    """
    if spec in BASELINES:
        return BASELINES[spec]
    import importlib.util
    import os
    import sys
    path = os.path.abspath(spec)
    sys.path.insert(0, os.path.dirname(path))
    module_spec = importlib.util.spec_from_file_location("team_policy", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module.Policy
