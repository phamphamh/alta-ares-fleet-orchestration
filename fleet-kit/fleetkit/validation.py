"""The validation set: a fixed list of public scenarios for the live board.

Anyone can regenerate them with the public generator. They are not the scenarios of the final evaluation:
those are hidden and differ. The live board only ranks the plans teams upload for these.
"""
from __future__ import annotations

from typing import List, Tuple

VALIDATION_SET: List[Tuple[str, int]] = [
    ("L1", 101), ("L2", 201), ("L2", 202), ("L3", 301), ("L3", 302), ("L3", 303), ("L4", 401), ("L4", 402)]


def scenario_id(level: str, seed: int) -> str:
    """Returns the name of a scenario, like `L3-301`."""
    return f"{level}-{seed}"


def parse_scenario_id(text: str) -> Tuple[str, int]:
    """Returns (level, seed) from a name like `L3-301`; raises ValueError for anything else."""
    level, _, seed = text.partition("-")
    if level not in ("L1", "L2", "L3", "L4") or not seed.isdigit():
        raise ValueError(f"not a scenario name like L3-301: {text!r}")
    return level, int(seed)


def validation_ids() -> List[str]:
    """Returns the names of the validation scenarios, in order."""
    return [scenario_id(level, seed) for level, seed in VALIDATION_SET]
