"""Alta Ares link-loss policy: "silent unless it matters".

Design (one instance per aircraft, called at 1 Hz after the cut):

* Everyone carries the whole plan, so every aircraft can dead-reckon every peer that is still
  on its plan. Silence means "I am on my plan". Only facts that a peer cannot infer are sent:
    - a scout that completes an observation an effector still depends on sends a confirmation
      (contact, completion time), repeated a few times; effectors of that target relay it once;
    - an aircraft whose route clock drifts from its plan (hold / return / slow-down) announces
      its state so peers can predict where it really is.
* Hard safety rules, checked locally every step:
    - never fly into a known no-fly disc (sensed or heard): turn back, or hold if that is blocked;
    - an effector never engages a reclassified contact (it senses it 300 m out, before the dive);
    - an effector whose confirming observation was due after the cut waits short of its dive
      until it hears a confirmation, and engages only >= confirm_margin after the completion time;
    - separation guard: the chosen motion is checked a few seconds ahead against the predicted
      positions of neighbours; if it would come too close, the safest alternative is taken.
Messages are compact JSON well under 64 bytes.
"""
import math

from fleetkit.geometry import segment_enters_cylinder
from fleetkit.linkloss.sim import RouteClock
from fleetkit.model import parse_plan

D_SEP_MARGIN = 12.0      # extra metres kept on top of d_sep in the guard
LOOKAHEAD = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
FREEZE_LEAD = 6.0        # an unconfirmed group freezes this many seconds before its first planned engagement
CONF_REPEAT = (0, 2, 4, 7, 11, 16, 24)
DEV_REPEAT = (0, 1, 3, 6)
NEIGH_R = 900.0
GRID = 300.0

_SHARED = {}


def _shared(scenario, plan):
    key = id(plan)
    got = _SHARED.get(key)
    if got is not None and got["plan"] is plan:
        return got
    routes, _ = parse_plan(plan)
    ac = scenario.aircraft_by_id()
    clocks = {a: RouteClock(r) for a, r in routes.items()}
    target, te, groups = {}, {}, {}
    for a, r in routes.items():
        last = r.waypoints[-1]
        if ac[a].type == "effector" and last.action == "engage":
            target[a] = last.target
            te[a] = last.t
            groups.setdefault(last.target, []).append(a)
    obs = {}
    for a, r in routes.items():
        if ac[a].type != "scout":
            continue
        for k, w in enumerate(r.waypoints):
            if w.action == "observe":
                obs.setdefault(w.target, []).append((a, w.t + w.dwell_s, k))
    ids = sorted(c.id for c in scenario.contacts)
    num = {cid: i for i, cid in enumerate(ids)}
    # coarse neighbour sets: peers whose planned paths come within NEIGH_R at the same time
    t_end = max(c.end for c in clocks.values()) if clocks else 0.0
    neigh = {a: set() for a in routes}
    cell = NEIGH_R
    t = 0.0
    names = sorted(routes)
    while t <= t_end + 1e-9:
        buckets = {}
        for a in names:
            c = clocks[a]
            if t < c.start or t > c.end:
                continue
            p = c.position(t)
            buckets.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(a)
        for (i, j), lst in buckets.items():
            near = []
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    near.extend(buckets.get((i + di, j + dj), ()))
            for a in lst:
                neigh[a].update(near)
        t += 4.0
    for a in neigh:
        neigh[a].discard(a)
    # spatial index of every planned trajectory: cell -> [(t, aircraft)], sampled every 2 s
    grid = {}
    for a in names:
        c = clocks[a]
        t = c.start
        while t <= c.end + 1e-9:
            p = c.position(t)
            grid.setdefault((int(p[0] // GRID), int(p[1] // GRID)), []).append((t, a))
            t += 2.0
    te_first = {c: min(te[a] for a in m) for c, m in groups.items()}
    te_last = {c: max(te[a] for a in m) for c, m in groups.items()}
    got = {"te_first": te_first, "te_last": te_last, "plan": plan, "routes": routes, "ac": ac, "clocks": clocks, "target": target, "te": te,
           "groups": groups, "obs": obs, "num": num, "ids": ids, "neigh": neigh,
           "contacts": scenario.contact_by_id(), "rules": scenario.rules, "grid": grid}
    _SHARED.clear()
    _SHARED[key] = got
    return got


def _c(x):
    """Compact number for messages: 3.0 -> 3."""
    return int(x) if float(x).is_integer() else x


def _cyl_hit(a, b, z):
    return segment_enters_cylinder(a, b, (z[0], z[1]), z[2] + 6.0, z[3])


class Policy:
    def __init__(self, scenario, plan, aircraft_id):
        self.S = _shared(scenario, plan)
        self.id = aircraft_id
        S = self.S
        self.clock = S["clocks"][aircraft_id]
        self.kind = S["ac"][aircraft_id].type
        self.target = S["target"].get(aircraft_id)
        self.window = None
        if self.target is not None:
            self.window = S["contacts"][self.target].window
        self.rules = S["rules"]
        self.zones = []          # (x, y, r, top)
        self.reclass = set()
        self.conf = {}           # contact -> completion time
        self.dev = {}            # peer -> (tau, t_sent, rate, mode)
        self.need_conf = None
        self.sent_conf = {}      # contact -> first send time
        self.relayed = set()
        self.my_dev = None       # (rate, since)
        self.last_dev_sent = -1e9
        self.dev_sent_at = None
        self.aborted = False
        self.pending_msgs = []

    # ------------------------------------------------------------------ knowledge
    def _learn(self, obs):
        t = obs["t"]
        for e in obs["sensed"]:
            if e["kind"] == "reclassify":
                self.reclass.add(e["contact"])
            elif e["kind"] == "popup_zone":
                z = (float(e["center"][0]), float(e["center"][1]), float(e["radius_m"]), float(e.get("top_m", 200.0)))
                if z not in self.zones:
                    self.zones.append(z)
        ids = self.S["ids"]
        for m in obs["inbox"]:
            p = m.get("payload")
            if not isinstance(p, list):
                continue
            try:
                if len(p) == 3:           # confirmation: [contact number, completion time, 0]
                    cid = ids[int(p[0])]
                    self.conf[cid] = min(self.conf.get(cid, 1e18), float(p[1]))
                elif len(p) == 2:         # deviation: [route-clock rate, route clock at sending]
                    self.dev[m["from"]] = (float(p[1]), float(m["sent_t"]), float(p[0]), t)
            except (ValueError, IndexError, TypeError, KeyError):
                pass

    # ------------------------------------------------------------------ prediction
    def _peer_pos(self, peer, t):
        S = self.S
        c = S["clocks"][peer]
        d = self.dev.get(peer)
        if d is not None:
            tau0, ts, rate, _ = d
            tau = tau0 + rate * (t - ts)
        else:
            tau = t
        if tau < c.start or tau > c.end + 1e-9:
            if d is not None and d[2] < 0 and tau < c.start:
                return None      # landed back home
            if tau > c.end:
                return None      # engaged or landed
            return None          # not yet airborne
        return c.position(tau)

    def _own_pos(self, tau, rate, dt):
        c = self.clock
        x = tau + rate * dt
        if x > c.end:
            return None
        if x < c.start:
            return c.position(c.start)
        return c.position(x)

    def _min_sep(self, obs, rate):
        """Smallest predicted distance to a non-exempt neighbour over the look-ahead.

        Right of way: a hovering aircraft is a fixed obstacle that everybody else avoids, so an
        aircraft that is already hovering never moves for separation. Starting to hover is checked
        over the time the others need to hear about it.
        """
        S = self.S
        t, tau = obs["t"], obs["tau"]
        hovering = self.my_dev is not None and self.my_dev[0] == 0.0
        if rate == 0.0 and hovering:
            return 1e9
        horizon = 2.0 if rate == 0.0 else 99.0
        me_dev = not (abs(rate - 1.0) < 1e-9 and abs(tau - t) < 1e-6) or rate == 0.0
        peers = set()
        for p, d in self.dev.items():
            if abs(d[2] - 1.0) < 1e-9 and abs(d[0] - d[1]) <= 0.6:
                continue                      # back on its plan
            if abs(d[2]) < 1e-9:
                peers.add(p)                  # a hovering aircraft is an obstacle for everybody
            elif not me_dev or p < self.id:
                peers.add(p)                  # moving deviators: on-plan traffic and higher ids yield
        if me_dev:
            peers |= self._near_plans(obs["pos"], t - 4.0, t + 8.0) - set(self.dev)
        best = 1e9
        tgt = self.target
        tpos = S["contacts"][tgt].pos if tgt is not None else None
        exr = self.rules.exempt_radius_m
        for k in LOOKAHEAD:
            if k > horizon:
                break
            me = self._own_pos(tau, rate, k)
            if me is None:
                break
            if me[2] <= 0.0 and rate <= 0:
                continue
            for p in peers:
                q = self._peer_pos(p, t + k)
                if q is None:
                    continue
                d = math.sqrt((me[0] - q[0]) ** 2 + (me[1] - q[1]) ** 2 + (me[2] - q[2]) ** 2)
                if d >= best:
                    continue
                if tgt is not None and S["target"].get(p) == tgt:
                    if math.dist(me, tpos) <= exr - 2 and math.dist(q, tpos) <= exr - 2:
                        continue
                best = d
        return best

    def _motion_hits_zone(self, obs, rate, steps=2.0):
        if not self.zones:
            return False
        tau = obs["tau"]
        a = self.clock.position(tau)
        pts = [a]
        c = self.clock
        if rate > 0:
            hi = min(c.end, tau + rate * steps)
            pts += [c.pos[k] for k in range(c.next_waypoint(tau), len(c.pos)) if c.arr[k] < hi]
            pts.append(c.position(hi))
        elif rate < 0:
            lo = max(c.start, tau + rate * steps)
            k = c.next_waypoint(tau) - 1
            while k >= 0 and c.arr[k] > lo:
                pts.append(c.pos[k])
                k -= 1
            pts.append(c.position(lo))
        else:
            return False
        for z in self.zones:
            for p, q in zip(pts, pts[1:]):
                if _cyl_hit(p, q, z):
                    return True
        return False

    def _path_blocked(self, tau, forward):
        if not self.zones:
            return False
        c = self.clock
        a = c.position(tau)
        k = c.next_waypoint(tau)
        pts = [a] + (c.pos[k:] if forward else c.pos[:k][::-1])
        for z in self.zones:
            for p, q in zip(pts, pts[1:]):
                if _cyl_hit(p, q, z):
                    return True
        return False

    # ------------------------------------------------------------------ step
    def _mission(self, obs):
        """What the mission wants this step (route-clock rate) and whether moving forward is forbidden."""
        S = self.S
        t, tau = obs["t"], obs["tau"]
        rem = self.clock.end - tau
        if self.aborted:
            return 0.0
        if self._path_blocked(tau, True) or (self.target is not None and self.target in self.reclass):
            self.aborted = True
            return 0.0
        if self.kind != "effector" or not self.need_conf:
            return 1.0
        tf = S["te_first"][self.target] - FREEZE_LEAD
        e = self.conf.get(self.target)
        lo, hi = self.window
        if e is None:
            if t + rem > hi + 0.5 or t > hi:
                self.aborted = True
                return 0.0
            return 0.0 if (t >= tf or rem <= FREEZE_LEAD) else 1.0
        need = e + self.rules.confirm_margin_s + 0.06
        shift = max(0.0, need - S["te_first"][self.target])
        t_go = tf + shift
        if S["te_last"][self.target] + shift > hi - 0.5:
            self.aborted = True        # too late for the window: the strike cannot be completed
            return 0.0
        if t + rem < need:
            return 0.0 if (t >= tf or rem <= FREEZE_LEAD) else 1.0
        if shift > 0 and t < t_go and t >= tf:
            return 0.0
        return 1.0

    def step(self, obs):
        try:
            return self._step(obs)
        except Exception:        # never crash the run: hover, and say so
            return {"kind": "hold"}, None

    def _step(self, obs):
        t = obs["t"]
        S = self.S
        self._learn(obs)
        msg = None
        if self.need_conf is None:
            self.need_conf = False
            if self.target is not None:
                ends = [e for (_, e, _) in S["obs"].get(self.target, [])]
                self.need_conf = not any(e <= obs["t_loss"] - 1.0 for e in ends)
        if self.kind == "scout":
            for cid in obs["own_observed"]:
                if cid not in self.sent_conf and cid in S["groups"]:
                    if any(S["te"][e] > obs["t_loss"] for e in S["groups"][cid]):
                        self.sent_conf[cid] = t
                        ends = [e for (a, e, _) in S["obs"][cid] if a == self.id]
                        planned = max(ends) if ends else t
                        # completion time: the plan's, shifted by our own clock lag
                        self.conf.setdefault(cid, min(t, planned + (t - obs["tau"])))
        tau = obs["tau"]
        want = self._mission(obs)

        on_plan = abs(tau - t) < 1e-6
        options = [want] + [r for r in ((0.0, -1.0, 0.5, 1.0) if self.aborted else (0.0, 0.5, 1.0, -1.0)) if r != want]
        chosen, best_any = None, None
        need = self.rules.d_sep_m + D_SEP_MARGIN
        for r in options:
            if r > 0 and self._forward_forbidden(obs, r):
                continue
            if self._motion_hits_zone(obs, r):
                continue
            sep = self._min_sep(obs, r)
            if sep >= (self.rules.d_sep_m + 3.0 if r == 0.0 else need):
                chosen = r
                break
            if best_any is None or sep > best_any[0]:
                best_any = (sep, r)
        if chosen is None:
            chosen = best_any[1] if best_any is not None else 0.0

        # ---- deviation announcements (anyone whose clock is not the plan's)
        if not (on_plan and chosen == 1.0):
            state = (round(chosen, 2), round(tau - t * chosen, 1))
            if self.my_dev != state:
                self.my_dev = state
                self.dev_sent_at = t
            k = t - self.dev_sent_at
            period = 10
            if chosen == 0.0:
                th = self._threat(obs)
                period = 1 if th <= 8.0 else (3 if th <= 20.0 else 15)
            if any(abs(k - x) < 0.5 for x in DEV_REPEAT) or (k > 0 and int(round(k)) % period == 0):
                msg = [_c(chosen), _c(round(tau, 1))]
        # ---- confirmations (scouts send, effectors relay their own target once)
        if msg is None:
            for cid, t0 in self.sent_conf.items():
                if any(abs((t - t0) - x) < 0.5 for x in CONF_REPEAT):
                    msg = [S["num"][cid], _c(math.ceil(self.conf[cid] * 10 - 1e-6) / 10), 0]
                    break
        if msg is None and self.kind == "effector" and self.need_conf and self.target in self.conf \
                and self.target not in self.relayed:
            self.relayed.add(self.target)
            msg = [S["num"][self.target], _c(math.ceil(self.conf[self.target] * 10 - 1e-6) / 10), 0]
        if chosen == 1.0:
            return {"kind": "continue"}, msg
        if chosen == 0.0:
            return {"kind": "hold"}, msg
        if chosen < 0:
            return {"kind": "return"}, msg
        return {"kind": "speed", "scale": chosen}, msg

    def _near_plans(self, pos, t0, t1):
        """Aircraft whose planned trajectory passes within ~one grid cell of `pos` during [t0, t1]."""
        g = self.S["grid"]
        i, j = int(pos[0] // GRID), int(pos[1] // GRID)
        out = set()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for t, a in g.get((i + di, j + dj), ()):
                    if t0 <= t <= t1:
                        out.add(a)
        out.discard(self.id)
        return out

    def _threat(self, obs, radius=160.0):
        """Seconds until a peer that may not know we hover gets within `radius` of us (inf if none in 20 s)."""
        t = obs["t"]
        me = obs["pos"]
        S = self.S
        cand = []
        for p in self._near_plans(me, t - 2.0, t + 22.0):
            d = self.dev.get(p)
            if d is not None and (abs(d[2]) < 1e-9 or abs(d[0] - d[1]) > 0.6):
                continue      # it hovers or deviates: it has been hearing us
            cand.append(p)
        best = 1e9
        for p in cand:
            for k in range(0, 21, 2):
                if k >= best:
                    break
                q = self._peer_pos(p, t + k)
                if q is not None and (me[0] - q[0]) ** 2 + (me[1] - q[1]) ** 2 + (me[2] - q[2]) ** 2 < radius * radius:
                    best = k
                    break
        return best

    def _traffic_near(self, obs, radius=700.0, ks=(0.0, 8.0, 16.0)):
        t = obs["t"]
        me = obs["pos"]
        for p in self.S["neigh"].get(self.id, ()):
            for k in ks:
                q = self._peer_pos(p, t + k)
                if q is not None and (me[0] - q[0]) ** 2 + (me[1] - q[1]) ** 2 < radius ** 2:
                    return True
        return False

    def _forward_forbidden(self, obs, rate):
        """An effector may not reach its engagement unless it is confirmed early enough and safe."""
        if self.kind != "effector" or self.target is None:
            return False
        rem = self.clock.end - obs["tau"]
        t = obs["t"]
        if rem > rate * 2.0 + 0.5:
            return False
        if self.target in self.reclass or self.aborted:
            return True
        if self.need_conf:
            ct = self.conf.get(self.target)
            if ct is None or t + rem / max(rate, 1e-6) < ct + self.rules.confirm_margin_s + 0.06:
                return True
        return False
