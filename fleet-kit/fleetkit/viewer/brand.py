"""The Alta Ares look: Space Grotesk and Space Mono (SIL Open Font License, see fonts/) and the palette.

The fonts are embedded as data URIs so that every page stays one offline file. The colours are the design
system's: near-black ink, bone text, signal orange, and the map semantics (hostile red, friendly blue,
neutral green, unknown yellow).
"""
from __future__ import annotations

import base64
from pathlib import Path

FONTS = Path(__file__).resolve().parent / "fonts"
ASSETS = Path(__file__).resolve().parent / "assets"

INK, VOID, BONE = "#111111", "#0b0b0a", "#f4f3ef"
PANEL, PANEL2 = "#181817", "#20201e"
BONE2, BONE3, BONE4 = "#bbbbba", "#a3a29d", "#595959"
LINE = "rgba(244,243,239,0.10)"
SIGNAL, CAUTION, ALERT = "#ff480d", "#f2b84b", "#ff5c77"
HOSTILE, FRIEND, NEUTRAL, UNKNOWN, MINT = "#ff3031", "#00a8dc", "#00e200", "#ffff00", "#61d095"
SANS = '"Space Grotesk", ui-sans-serif, system-ui, sans-serif'
MONO = '"Space Mono", ui-monospace, Menlo, monospace'


def _b64(name: str) -> str:
    return base64.b64encode((FONTS / name).read_bytes()).decode("ascii")


def font_face_css() -> str:
    """Returns the @font-face rules with the two latin font files embedded."""
    return (f'@font-face{{font-family:"Space Grotesk";src:url(data:font/woff2;base64,{_b64("space-grotesk-latin.woff2")}) format("woff2");'
            f'font-weight:300 700;font-style:normal;font-display:swap}}'
            f'@font-face{{font-family:"Space Mono";src:url(data:font/woff2;base64,{_b64("space-mono-latin-400.woff2")}) format("woff2");'
            f'font-weight:400;font-style:normal;font-display:swap}}')


def logo_data_uri() -> str:
    """The Alta Ares mark (white dots on transparent, 160 px) as a data URI; invert it on a light background."""
    return "data:image/png;base64," + base64.b64encode((ASSETS / "alta_ares_logo.png").read_bytes()).decode("ascii")
