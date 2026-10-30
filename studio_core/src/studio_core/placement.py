"""Where a character stands over time: the placement track (task 4B.6).

A shot character has a start `position` (the point between its feet, frame fractions, D-033) and
an optional `path`: waypoints `{time_s, position, ease}`. The character holds `position` until
the first waypoint's segment starts, and each waypoint is reached from the previous one (the
start position for the first) with that waypoint's easing. To hold still for a while, put two
waypoints at the same position. Engine-neutral (D-030): pure maths on specs, no scene format.
"""

from __future__ import annotations

import math
from typing import Any

from studio_core.sif.units import frames

EASES = ("linear", "ease_in", "ease_out", "ease_in_out")
DEFAULT_EASE = "ease_in_out"
EPS = 1e-9


def ease(name: str, u: float) -> float:
    """Progress 0..1 → eased progress 0..1."""
    u = min(1.0, max(0.0, u))
    if name == "linear":
        return u
    if name == "ease_in":
        return u * u
    if name == "ease_out":
        return 1 - (1 - u) * (1 - u)
    if name == "ease_in_out":
        return u * u * (3 - 2 * u)
    raise ValueError(f"unknown ease {name!r}; known: {list(EASES)}")


def position_at(
    start: list[float] | tuple[float, ...], path: list[dict[str, Any]], t: float
) -> tuple[float, float]:
    """The character's position (frame fractions) at time t seconds."""
    x0, y0, t0 = float(start[0]), float(start[1]), 0.0
    for key in path:
        t1 = float(key["time_s"])
        x1, y1 = float(key["position"][0]), float(key["position"][1])
        if t < t1:
            u = ease(key.get("ease", DEFAULT_EASE), (t - t0) / (t1 - t0))
            return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
        x0, y0, t0 = x1, y1, t1
    return x0, y0


def frame_positions(
    start: list[float], path: list[dict[str, Any]], fps: int, n_frames: int
) -> list[tuple[float, float]]:
    """The position at every frame (frame f is at f / fps seconds)."""
    return [position_at(start, path, f / fps) for f in range(n_frames)]


def facing_frames(
    base: str,
    positions: list[tuple[float, float]],
    walking: list[bool],
) -> list[str]:
    """The facing at every frame. It is `base` until the character walks (a walk_cycle running)
    while moving sideways; then it faces the direction of travel and keeps it."""
    out, current = [], base
    for f in range(len(positions)):
        if walking[f] and f + 1 < len(positions):
            dx = positions[f + 1][0] - positions[f][0]
            if abs(dx) > EPS:
                current = "right" if dx > 0 else "left"
        out.append(current)
    return out


GAITS = ("walk_cycle", "walk_real", "run_real")


def walking_frames(actions: list[dict[str, Any]], fps: int, n_frames: int) -> list[bool]:
    """Frames covered by a gait action (to its duration, else to the end of the shot)."""
    flags = [False] * n_frames
    for a in actions:
        if a["motion"] not in GAITS:
            continue
        start = frames(a["start_s"], fps)
        end = start + frames(a["duration_s"], fps) if "duration_s" in a else n_frames
        for f in range(start, min(end, n_frames)):
            flags[f] = True
    return flags


def forward_travel(
    positions: list[tuple[float, float]],
    facings: list[str],
    *,
    width_px: float,
    height_px: float,
    scale: float,
) -> list[float]:
    """Cumulative distance travelled in the facing direction, per frame, in the character's own
    art pixels (screen px / scale). Movement against the facing, or none, adds nothing."""
    out, total = [0.0], 0.0
    for f in range(1, len(positions)):
        dx = (positions[f][0] - positions[f - 1][0]) * width_px
        dy = (positions[f][1] - positions[f - 1][1]) * height_px
        forward = dx if facings[f - 1] == "right" else -dx
        if forward > EPS:
            total += math.hypot(forward, dy) / scale
        out.append(total)
    return out
