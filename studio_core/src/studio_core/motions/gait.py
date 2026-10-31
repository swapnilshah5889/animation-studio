"""Foot contact rules for a baked walk (engine-neutral, D-098).

A walk reads as stepping only when the planted foot stays where it was put. Two numbers decide it,
both measured on the bake (the joint positions every engine receives), not on the pictures:

- *float*: while the character walks, the lower sole must touch the ground (a hovering body is
  the "floating" look of the first Mia: soles 10 to 15 px above the shadow)
- *slide*: over a run of frames where a foot is planted, its x must not drift (take-off and
  landing frames excluded)
"""

from __future__ import annotations

import math
from typing import Any

PLANTED_PX = 3.0  # a sole this close to the ground counts as planted
EDGE_FRAMES = 2  # frames at each end of a planted run that belong to the step, not the stance


def foot_bones(char: dict[str, Any]) -> list[str]:
    """The bones that end in a foot: the shins, or the thighs of a rig whose legs are one piece."""
    shins = [b for b, sp in char["bones"].items() if sp["role"] == "shin"]
    return shins or [b for b, sp in char["bones"].items() if sp["role"] == "thigh"]


def sole_tracks(char: dict[str, Any]) -> dict[str, list[tuple[float, float]]]:
    """Per shin bone, per frame: the sole's (x, y) in the bake's stage px (y up). The sole is the
    knee plus the shin's length (knee to ground) along its world direction."""
    scale = char["scale"]
    out: dict[str, list[tuple[float, float]]] = {}
    for shin in foot_bones(char):
        length = char["bones"][shin]["length_px"] * scale
        track = []
        for fr in char["frames"]:
            x, y, deg = fr["bones"][shin]
            r = math.radians(deg)
            track.append((x + length * math.cos(r), y + length * math.sin(r)))
        out[shin] = track
    return out


def foot_report(char: dict[str, Any], ground_y: float) -> dict[str, float]:
    """{'float': worst gap between the lower sole and the ground (px) over the frames where the
    character moves, 'sink': worst depth below the ground, 'slide': worst x drift over a planted
    run (px)}. `ground_y` is in the bake's y-up stage px."""
    soles = sole_tracks(char)
    names = list(soles)
    n = len(char["frames"])
    low = [min(soles[b][f][1] for b in names) for f in range(n)]
    root = next(b for b, sp in char["bones"].items() if sp["parent"] is None)
    xs = [fr["bones"][root][0] for fr in char["frames"]]
    moving = [abs(xs[f + 1] - xs[f]) > 0.5 for f in range(n - 1)] + [False]
    gap = [low[f] - ground_y for f in range(n) if moving[f]]
    slide = 0.0
    for b in names:  # a planted run: the frames in a row the sole is on the ground
        run: list[float] = []
        for f in range(n + 1):
            on = f < n and soles[b][f][1] - ground_y < PLANTED_PX
            if on:
                run.append(soles[b][f][0])
                continue
            core = run[EDGE_FRAMES : len(run) - EDGE_FRAMES]  # take-off and landing are not slide
            if len(core) >= 3:
                slide = max(slide, max(core) - min(core))
            run = []
    return {
        "float": max(gap, default=0.0),
        "sink": max((-g for g in gap), default=0.0),
        "slide": slide,
    }
