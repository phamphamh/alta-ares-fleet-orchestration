"""A dependency-free SVG view of a scenario and, optionally, a plan."""
from __future__ import annotations

import html
import math
from typing import Any, Dict, Optional

from .model import CIVILIAN, FRIENDLY, HOSTILE, SCOUT, UNKNOWN, Scenario, parse_plan

COLORS = {"scout": "#2b6cb0", "light": "#dd6b20", "heavy": "#6b46c1"}
SIZE = 900
MARGIN = 50


def _fmt(x: float) -> str:
    return f"{x:.1f}"


def render_svg(scenario: Scenario, plan: Optional[Any] = None, title: str = "") -> str:
    """Renders a top-down map with an altitude-time panel below it.

    Args:
        scenario: The scenario.
        plan: Optional decoded plan JSON to draw.
        title: Optional text for the heading.

    Returns:
        The SVG document as text.
    """
    area = max(
        [max(c.pos[0], c.pos[1]) for c in scenario.contacts]
        + [max(a.home[0], a.home[1]) for a in scenario.aircraft]
        + [z.center[0] + z.radius_m for z in scenario.zones] + [z.center[1] + z.radius_m for z in scenario.zones]
        + [1000.0]) * 1.05
    k = (SIZE - 2 * MARGIN) / area

    def px(x: float) -> float:
        return MARGIN + x * k

    def py(y: float) -> float:
        return SIZE - MARGIN - y * k

    out = []
    panel_h = 230
    height = SIZE + panel_h + 20
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {height}" width="{SIZE}" font-family="Helvetica, Arial, sans-serif" font-size="11">')
    out.append(f'<rect width="{SIZE}" height="{height}" fill="#ffffff"/>')
    out.append(f'<rect x="{MARGIN}" y="{MARGIN}" width="{SIZE - 2 * MARGIN}" height="{SIZE - 2 * MARGIN}" fill="#f7f7f5" stroke="#bbb"/>')
    heading = title or f"{scenario.level}  seed {scenario.seed}"
    out.append(f'<text x="{MARGIN}" y="26" font-size="15" font-weight="bold">{html.escape(str(heading))}</text>')
    for z in scenario.zones:
        out.append(f'<circle cx="{_fmt(px(z.center[0]))}" cy="{_fmt(py(z.center[1]))}" r="{_fmt(z.radius_m * k)}" fill="#e53e3e" fill-opacity="0.15" stroke="#e53e3e"/>')
        out.append(f'<text x="{_fmt(px(z.center[0]))}" y="{_fmt(py(z.center[1]))}" text-anchor="middle" fill="#9b2c2c">{html.escape(z.id)} (to {z.top_m:g} m)</text>')
    for c in scenario.contacts:
        x, y = px(c.pos[0]), py(c.pos[1])
        if c.cls in (FRIENDLY, CIVILIAN):
            for r, dash in ((scenario.rules.protect_radius_m, "2,2"), (scenario.rules.collateral_radius_m, "5,4")):
                out.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(r * k)}" fill="none" stroke="#38a169" stroke-dasharray="{dash}" stroke-opacity="0.7"/>')
    for a in scenario.aircraft:
        out.append(f'<rect x="{_fmt(px(a.home[0]) - 1.5)}" y="{_fmt(py(a.home[1]) - 1.5)}" width="3" height="3" fill="#444"/>')
    if plan is not None:
        routes, _ = parse_plan(plan)
        for aid, route in (routes or {}).items():
            ac = scenario.aircraft_by_id().get(aid)
            if ac is None:
                continue
            col = COLORS["scout"] if ac.type == SCOUT else COLORS[ac.subtype or "light"]
            pts = " ".join(f"{_fmt(px(w.x))},{_fmt(py(w.y))}" for w in route.waypoints)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.2" stroke-opacity="0.8"/>')
            for w in route.waypoints:
                if w.action == "observe":
                    out.append(f'<circle cx="{_fmt(px(w.x))}" cy="{_fmt(py(w.y))}" r="4" fill="none" stroke="{col}" stroke-width="1.6"/>')
                elif w.action == "engage":
                    x, y = px(w.x), py(w.y)
                    out.append(f'<path d="M{_fmt(x - 4)},{_fmt(y - 4)} L{_fmt(x + 4)},{_fmt(y + 4)} M{_fmt(x - 4)},{_fmt(y + 4)} L{_fmt(x + 4)},{_fmt(y - 4)}" stroke="{col}" stroke-width="2"/>')
    for c in scenario.contacts:
        x, y = px(c.pos[0]), py(c.pos[1])
        if c.cls == HOSTILE:
            needs = "+".join(f"{n}{s[0].upper()}" for s, n in sorted(c.needs.items()))
            out.append(f'<path d="M{_fmt(x)},{_fmt(y - 7)} L{_fmt(x + 6)},{_fmt(y + 5)} L{_fmt(x - 6)},{_fmt(y + 5)} Z" fill="#e53e3e"/>')
            label = f"{c.id} {c.points:g} pts {needs}"
        elif c.cls == UNKNOWN:
            out.append(f'<path d="M{_fmt(x)},{_fmt(y - 6)} L{_fmt(x + 6)},{_fmt(y)} L{_fmt(x)},{_fmt(y + 6)} L{_fmt(x - 6)},{_fmt(y)} Z" fill="#d69e2e"/>')
            label = f"{c.id} {c.points:g} pts"
        elif c.cls == FRIENDLY:
            out.append(f'<rect x="{_fmt(x - 5)}" y="{_fmt(y - 5)}" width="10" height="10" fill="#38a169"/>')
            label = f"{c.id} friendly"
        else:
            out.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="5" fill="#3182ce"/>')
            label = f"{c.id} civilian"
        out.append(f'<text x="{_fmt(x + 9)}" y="{_fmt(y + 4)}" fill="#222">{html.escape(label)}</text>')
    lx, ly = SIZE - MARGIN - 170, MARGIN + 14
    legend = [("scout", COLORS["scout"]), ("light effector", COLORS["light"]), ("heavy effector", COLORS["heavy"])]
    for i, (name, col) in enumerate(legend):
        out.append(f'<line x1="{lx}" y1="{ly + 15 * i}" x2="{lx + 22}" y2="{ly + 15 * i}" stroke="{col}" stroke-width="2"/><text x="{lx + 28}" y="{ly + 15 * i + 4}">{name}</text>')
    out.append(f'<text x="{lx}" y="{ly + 15 * len(legend) + 4}" fill="#555">ring = observe, cross = engage</text>')
    # altitude over time
    top = SIZE + 10
    left, width_p, h_p = MARGIN, SIZE - 2 * MARGIN, panel_h - 40
    out.append(f'<rect x="{left}" y="{top}" width="{width_p}" height="{h_p}" fill="#f7f7f5" stroke="#bbb"/>')
    out.append(f'<text x="{left}" y="{top - 2}" fill="#555">altitude (0 to {scenario.rules.z_max_m:g} m) against time (0 to {scenario.horizon_s:g} s)</text>')
    for level in (scenario.rules.z_min_m, scenario.rules.z_max_m):
        yy = top + h_p - level / scenario.rules.z_max_m * h_p
        out.append(f'<line x1="{left}" y1="{_fmt(yy)}" x2="{left + width_p}" y2="{_fmt(yy)}" stroke="#ccc" stroke-dasharray="3,3"/>')
    if plan is not None:
        routes, _ = parse_plan(plan)
        for aid, route in (routes or {}).items():
            ac = scenario.aircraft_by_id().get(aid)
            if ac is None:
                continue
            col = COLORS["scout"] if ac.type == SCOUT else COLORS[ac.subtype or "light"]
            pts = []
            for w in route.waypoints:
                for t in ((w.t, w.depart) if w.dwell_s > 0 else (w.t,)):
                    pts.append(f"{_fmt(left + t / scenario.horizon_s * width_p)},{_fmt(top + h_p - w.z / scenario.rules.z_max_m * h_p)}")
            out.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{col}" stroke-width="1" stroke-opacity="0.8"/>')
    out.append("</svg>")
    return "\n".join(out)
