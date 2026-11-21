"""The Viewer: builds the page for a scenario, a plan and, optionally, a link-loss run, with your own layers."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..model import Scenario
from .brand import font_face_css, logo_data_uri
from .model import build_model

HERE = Path(__file__).resolve().parent
PALETTE = ["#ff7b72", "#79c0ff", "#d2a8ff", "#7ee787", "#ffa657", "#f778ba"]


def render_html(model: Dict[str, Any]) -> str:
    """Returns the self-contained HTML page (no network, no external file) for a view model."""
    template = (HERE / "template.html").read_text(encoding="utf-8")
    css = (HERE / "style.css").read_text(encoding="utf-8")
    js = (HERE / "app.js").read_text(encoding="utf-8")
    data = json.dumps(model, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "\\u003c!--")
    title = html.escape(str(model["meta"]["title"]))
    return template.replace("__TITLE__", title).replace("/*__FONTS__*/", font_face_css()).replace("/*__CSS__*/", css).replace("/*__JS__*/", js).replace("__DATA__", data).replace("__LOGO__", logo_data_uri())


def _item(kind: str, spec: Any) -> dict:
    """Normalises one drawing item given as a tuple or a dictionary."""
    if isinstance(spec, dict):
        return {"kind": kind, **spec}
    if kind == "point":
        out = {"kind": kind, "x": spec[0], "y": spec[1]}
        if len(spec) > 2:
            out["label"] = spec[2]
    elif kind == "line":
        out = {"kind": kind, "pts": [[p[0], p[1]] for p in spec]}
    elif kind == "circle":
        out = {"kind": kind, "x": spec[0], "y": spec[1], "r": spec[2]}
    else:
        out = {"kind": "label", "x": spec[0], "y": spec[1], "label": spec[2]}
    return out


class Viewer:
    """Builds the viewer page.

    Example:
        v = Viewer(scenario, plan)
        v.layer("candidates", lines=[[(0, 0), (500, 300)]], points=[(500, 300, "goal")], color="#ff0")
        v.save("view.html")
    """

    def __init__(self, scenario, plan: Optional[dict] = None, *, events: Optional[dict] = None,
                 policy: Optional[Callable] = None, setting: Tuple[float, float] = (1000.0, 200.0),
                 run_seed: int = 0, title: Optional[str] = None):
        self.scenario = scenario if isinstance(scenario, Scenario) else Scenario.from_dict(scenario)
        self.plan, self.events, self.policy, self.setting, self.run_seed, self.title = plan, events, policy, setting, run_seed, title
        self._layers: List[dict] = []

    def layer(self, name: str, *, points: Optional[Sequence] = None, lines: Optional[Sequence] = None,
              circles: Optional[Sequence] = None, labels: Optional[Sequence] = None, color: Optional[str] = None,
              visible: bool = True, t0: Optional[float] = None, t1: Optional[float] = None) -> "Viewer":
        """Adds a layer drawn on the map; toggle it in the Layers tab.

        Args:
            name: The layer name.
            points: (x, y) or (x, y, label), or dictionaries with x, y, label, t0, t1, color.
            lines: Polylines, each a list of (x, y); or dictionaries with `pts`.
            circles: (x, y, radius) in metres.
            labels: (x, y, text).
            color: A CSS colour; a default is chosen from the layer count.
            visible: Whether it starts visible.
            t0, t1: Show the layer only between these times (s); items may carry their own.
        """
        items = [_item("point", p) for p in points or []] + [_item("line", l) for l in lines or []] \
            + [_item("circle", c) for c in circles or []] + [_item("label", l) for l in labels or []]
        self._layers.append({"name": name, "color": color or PALETTE[len(self._layers) % len(PALETTE)],
                             "visible": visible, "t0": t0, "t1": t1, "items": items})
        return self

    def add_layers(self, layers: List[dict]) -> "Viewer":
        """Adds layers given as dictionaries (the `--layers layers.json` format: name, color, items...)."""
        for l in layers:
            items = l.get("items")
            if items is None:
                items = [_item("point", p) for p in l.get("points", [])] + [_item("line", x) for x in l.get("lines", [])] \
                    + [_item("circle", c) for c in l.get("circles", [])] + [_item("label", x) for x in l.get("labels", [])]
            self._layers.append({"name": l["name"], "color": l.get("color") or PALETTE[len(self._layers) % len(PALETTE)],
                                 "visible": l.get("visible", True), "t0": l.get("t0"), "t1": l.get("t1"), "items": items})
        return self

    def model(self) -> Dict[str, Any]:
        """Returns the view model (a dictionary of plain JSON values)."""
        run = trace = oracle = None
        if self.plan is not None and self.events is not None and self.policy is not None:
            from ..linkloss.sim import simulate
            trace = {}
            run = simulate(self.scenario, self.plan, self.events, self.policy, setting=self.setting,
                           run_seed=self.run_seed, trace=trace)
            ref = simulate(self.scenario, self.plan, self.events, oracle=True)
            oracle = ref.points if not ref.failed and ref.points > 0 else None
        return build_model(self.scenario, self.plan, events=self.events, run=run, trace=trace, oracle_points=oracle,
                           setting=self.setting, layers=self._layers, title=self.title)

    def html(self) -> str:
        """Returns the page."""
        return render_html(self.model())

    def save(self, path: str) -> str:
        """Writes the page to `path` and returns the path."""
        Path(path).write_text(self.html(), encoding="utf-8")
        return str(path)
