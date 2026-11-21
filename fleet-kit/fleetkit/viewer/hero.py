"""An animated SVG of a plan (SMIL, no script): a README hero that GitHub renders as an image."""
from __future__ import annotations

import html
from typing import Dict, List, Optional

from ..model import Scenario
from . import brand
from .model import build_model

W, H = 1280, 640
MAP = (640, 40, 580, 560)            # x, y, width, height of the map box
BG, PANEL, GRID, TEXT, MUTED = brand.INK, brand.PANEL, "rgba(244,243,239,0.07)", brand.BONE, brand.BONE3
COLOR = {"scout": brand.BONE, "light": brand.CAUTION, "heavy": brand.MINT}
CLS = {"hostile": brand.HOSTILE, "unknown": brand.UNKNOWN, "friendly": brand.FRIEND, "civilian": brand.NEUTRAL}
ZONE = brand.ALERT
SANS, MONO = "'Space Grotesk',system-ui,sans-serif", "'Space Mono',ui-monospace,Menlo,monospace"


def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def render_hero(scenario: Scenario, plan: dict, *, title: str = "Fleet Orchestration",
                tagline: str = "Task a mixed fleet of scouts and effector drones under ten written rules.",
                loop_s: float = 26.0, step_s: float = 4.0) -> str:
    """Returns the animated SVG of a plan flown at high speed, looping.

    Args:
        scenario: The scenario.
        plan: A plan dictionary (the shipped baseline's, never a private solver's).
        title: Big heading on the left.
        tagline: One line under the heading.
        loop_s: Length of the loop in seconds.
        step_s: Sampling step of the positions in simulated seconds.
    """
    model = build_model(scenario, plan)
    world, tr, tm = model["world"], model["tracks"], model["time"]
    x0, x1, y0, y1 = world["bounds"]
    mx, my, mw, mh = MAP
    span = max(x1 - x0, y1 - y0, 200.0) * 1.1
    k = min(mw, mh) / span
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def px(x: float) -> float:
        return mx + mw / 2 + (x - cx) * k

    def py(y: float) -> float:
        return my + mh / 2 - (y - cy) * k

    n = len(next(iter(tr.values()))["p"])
    stride = max(1, int(round(step_s / tm["dt"])))
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    hold = max(2, int(len(idx) * 0.08))                       # rest on the last frame at the end of the loop
    total = len(idx) + hold
    t_end = tm["t1"]

    def frac(t: float) -> float:
        return min(0.999, max(0.0, t / t_end * (len(idx) / total)))

    out: List[str] = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{html.escape(title)}: animated plan replay">')
    a(f'<defs><style>{brand.font_face_css()}</style><pattern id="hz" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M-2 10L10 -2M-2 6L6 -2M2 10L10 2" stroke="{ZONE}" stroke-opacity=".55" stroke-width="1.2"/></pattern>'
      f'<clipPath id="mc"><rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="6"/></clipPath></defs>')
    a(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
    # left column
    a(f'<image x="64" y="58" width="34" height="34" href="{brand.logo_data_uri()}"/>'
      f'<text x="110" y="82" fill="{TEXT}" font-family="{SANS}" font-size="14" font-weight="600" letter-spacing="3.2">ALTA ARES</text>'
      f'<text x="222" y="82" fill="{brand.SIGNAL}" font-family="{SANS}" font-size="14">/</text>'
      f'<text x="240" y="82" fill="{MUTED}" font-family="{SANS}" font-size="14" letter-spacing="1.4">EDTH PARIS 2026</text>')
    a(f'<text x="64" y="190" fill="{TEXT}" font-family="{SANS}" font-size="56" font-weight="300" letter-spacing="-0.6">{html.escape(title)}</text>')
    words, lines, cur = tagline.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > 38:
            lines.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    lines.append(cur)
    for i, line in enumerate(lines):
        a(f'<text x="64" y="{238 + 30 * i}" fill="{MUTED}" font-family="{SANS}" font-size="22">{html.escape(line)}</text>')
    ly = 238 + 30 * len(lines) + 56
    legend = [("scout", COLOR["scout"], "circle"), ("light effector", COLOR["light"], "circle"), ("heavy effector", COLOR["heavy"], "circle"),
              ("hostile", CLS["hostile"], "diamond"), ("unknown", CLS["unknown"], "ring"), ("friendly", CLS["friendly"], "square"), ("civilian", CLS["civilian"], "circle")]
    for i, (name, col, shape) in enumerate(legend):
        lx, lyy = 64 + (i % 2) * 220, ly + (i // 2) * 34
        if shape == "circle":
            a(f'<circle cx="{lx + 7}" cy="{lyy - 6}" r="6" fill="{col}"/>')
        elif shape == "diamond":
            a(f'<path d="M{lx + 7} {lyy - 14}L{lx + 15} {lyy - 6}L{lx + 7} {lyy + 2}L{lx - 1} {lyy - 6}Z" fill="{col}"/>')
        elif shape == "ring":
            a(f'<circle cx="{lx + 7}" cy="{lyy - 6}" r="6" fill="none" stroke="{col}" stroke-width="2.2"/>')
        else:
            a(f'<rect x="{lx + 1}" y="{lyy - 12}" width="12" height="12" fill="{col}"/>')
        a(f'<text x="{lx + 26}" y="{lyy}" fill="{TEXT}" font-family="{SANS}" font-size="17">{html.escape(name)}</text>')
    plan_info = model["plan"]
    caption = f"the shipped baseline on {model['meta']['level']} seed {model['meta']['seed']}: score {plan_info['score']}" if plan_info["valid"] else ""
    a(f'<text x="64" y="{H - 52}" fill="{MUTED}" font-family="{SANS}" font-size="15">{html.escape(caption)}</text>')
    a(f'<text x="64" y="{H - 28}" fill="{MUTED}" font-family="{MONO}" font-size="14">python3 -m fleetkit generate L3 4 -o s.json</text>')
    # map box
    a(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="6" fill="{PANEL}" stroke="{brand.LINE}"/>')
    a('<g clip-path="url(#mc)">')
    step = 1000.0 if span > 4000 else 500.0
    gx = (int(x0 // step) - 1) * step
    while gx < x1 + step:
        a(f'<line x1="{_f(px(gx))}" y1="{my}" x2="{_f(px(gx))}" y2="{my + mh}" stroke="{GRID}" stroke-width="1"/>')
        gx += step
    gy = (int(y0 // step) - 1) * step
    while gy < y1 + step:
        a(f'<line x1="{mx}" y1="{_f(py(gy))}" x2="{mx + mw}" y2="{_f(py(gy))}" stroke="{GRID}" stroke-width="1"/>')
        gy += step
    for z in world["zones"]:
        a(f'<circle cx="{_f(px(z["x"]))}" cy="{_f(py(z["y"]))}" r="{_f(z["r"] * k)}" fill="url(#hz)" stroke="{ZONE}" stroke-dasharray="5 3" stroke-width="1.4"/>')
    for c in world["contacts"]:
        X, Y, col = _f(px(c["x"])), _f(py(c["y"])), CLS[c["cls"]]
        if c["cls"] in ("friendly", "civilian"):
            a(f'<circle cx="{X}" cy="{Y}" r="{_f(world["rules"]["protect"] * k)}" fill="none" stroke="{col}" stroke-opacity=".5" stroke-dasharray="3 3"/>')
    # faint routes
    for ac in model["aircraft"]:
        pts = [tr[ac["id"]]["p"][i] for i in idx if tr[ac["id"]]["p"][i] and tr[ac["id"]]["s"][i] in "fohr"]
        if len(pts) > 1:
            col = COLOR["scout"] if ac["type"] == "scout" else COLOR[ac["sub"]]
            a(f'<polyline points="{" ".join(_f(px(p[0])) + "," + _f(py(p[1])) for p in pts)}" fill="none" stroke="{col}" stroke-opacity=".22" stroke-width="1.2"/>')
    # contacts on top, with a green ring once served and a pulse at each engagement
    for c in world["contacts"]:
        X, Y, col = _f(px(c["x"])), _f(py(c["y"])), CLS[c["cls"]]
        if c["cls"] == "hostile":
            r = 7
            a(f'<path d="M{X} {_f(py(c["y"]) - r)}L{_f(px(c["x"]) + r)} {Y}L{X} {_f(py(c["y"]) + r)}L{_f(px(c["x"]) - r)} {Y}Z" fill="{col}"/>')
        elif c["cls"] == "unknown":
            a(f'<circle cx="{X}" cy="{Y}" r="6" fill="none" stroke="{col}" stroke-width="2.2"/>')
        elif c["cls"] == "friendly":
            a(f'<rect x="{_f(px(c["x"]) - 5.5)}" y="{_f(py(c["y"]) - 5.5)}" width="11" height="11" fill="{col}"/>')
        else:
            a(f'<circle cx="{X}" cy="{Y}" r="5.5" fill="{col}"/>')
        sv = model["served"].get(c["id"])
        if sv is not None:
            f0 = frac(sv)
            a(f'<circle cx="{X}" cy="{Y}" r="12" fill="none" stroke="#00e200" stroke-width="2.4" opacity="0"><animate attributeName="opacity" dur="{loop_s}s" repeatCount="indefinite" values="0;0;1;1;0" keyTimes="0;{f0:.4f};{min(0.9995, f0 + 0.0005):.4f};0.985;1"/></circle>')
    for m in model["marks"]:
        if m["kind"] != "engage":
            continue
        c = next(x for x in world["contacts"] if x["id"] == m["contact"])
        f0, f1 = frac(m["t"]), frac(m["t"] + 6)
        a(f'<circle cx="{_f(px(c["x"]))}" cy="{_f(py(c["y"]))}" r="8" fill="none" stroke="#ff3031" stroke-width="3" opacity="0">'
          f'<animate attributeName="r" dur="{loop_s}s" repeatCount="indefinite" values="8;8;34;34" keyTimes="0;{f0:.4f};{max(f0 + 0.001, f1):.4f};1"/>'
          f'<animate attributeName="opacity" dur="{loop_s}s" repeatCount="indefinite" values="0;0.95;0;0" keyTimes="0;{f0:.4f};{max(f0 + 0.001, f1):.4f};1"/></circle>')
    # aircraft
    for ac in model["aircraft"]:
        t = tr[ac["id"]]
        if all(s == "g" for s in t["s"]):
            continue
        col = COLOR["scout"] if ac["type"] == "scout" else COLOR[ac["sub"]]
        r = 5 if ac["type"] == "scout" else 4.2 if ac["sub"] == "light" else 5.6
        xs, ys, op = [], [], []
        last = None
        for i in idx:
            p, s = t["p"][i], t["s"][i]
            if p:
                last = p
            elif last is None:
                last = ac["home"]
            xs.append(_f(px(last[0])))
            ys.append(_f(py(last[1])))
            op.append("0" if s == "x" else ".35" if s in "gl" else "1")
        xs += [xs[-1]] * hold
        ys += [ys[-1]] * hold
        op += [op[-1]] * hold
        d = f'dur="{loop_s}s" repeatCount="indefinite"'
        a(f'<circle r="{r}" fill="{col}" stroke="{BG}" stroke-width="1.2"><animate attributeName="cx" {d} values="{";".join(xs)}"/>'
          f'<animate attributeName="cy" {d} values="{";".join(ys)}"/><animate attributeName="opacity" {d} values="{";".join(op)}"/></circle>')
    a('</g>')
    a(f'<rect x="{mx + 14}" y="{my + mh - 18}" width="{mw - 28}" height="4" rx="2" fill="{GRID}"/>'
      f'<rect x="{mx + 14}" y="{my + mh - 18}" width="0" height="4" rx="2" fill="{brand.SIGNAL}"><animate attributeName="width" dur="{loop_s}s" repeatCount="indefinite" values="0;{mw - 28}" /></rect>')
    a('</svg>')
    return "\n".join(out)
