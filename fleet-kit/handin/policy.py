"""Your link-loss policy (optional second part). See LINKLOSS.md in the kit folder.

Each aircraft gets one `Policy` object and `step(obs)` is called once per second after the cut.
Return an action and an optional message (any JSON, at most 64 bytes written compactly).
"""


class Policy:
    def __init__(self, scenario, plan, aircraft_id):
        self.aircraft_id = aircraft_id

    def step(self, obs):
        # TODO: your policy here. The simplest one: carry on with the plan and say nothing.
        return {"kind": "continue"}, None
