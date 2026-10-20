"""Rhubarb mouth cues → waypoints for a Switch layer's `layer_name`.

Rhubarb (`rhubarb -f json`) returns `mouthCues: [{start, end, value}]` with values A-H and X.
A mouth Switch layer holds one child per shape, named after it; animating `layer_name` with
constant (step) waypoints shows the right shape at the right frame.

Timing rules (unit-tested): a cue starting at t seconds shows from frame ceil(t * fps); when two
cues land on the same frame the later one wins; consecutive identical shapes collapse into one
waypoint.
"""

from __future__ import annotations

import json
from pathlib import Path

from studio_core.sif.units import frames
from studio_core.sif.values import Animated, Interp, Waypoint

RHUBARB_SHAPES = ("A", "B", "C", "D", "E", "F", "G", "H", "X")


def load_cues(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text())["mouthCues"]


def mouth_track(
    cues: list[dict[str, object]],
    fps: int,
    *,
    start_frame: int = 0,
    shape_map: dict[str, str] | None = None,
    rest: str = "X",
) -> Animated:
    """Build the animated `layer_name` value. `shape_map` maps Rhubarb shapes to the shapes a
    puppet actually has (e.g. a 3-mouth placeholder); unmapped shapes pass through unchanged."""
    shape_map = shape_map or {}
    by_frame: dict[int, str] = {start_frame: rest}
    for cue in cues:
        value = str(cue["value"])
        if value not in RHUBARB_SHAPES:
            raise ValueError(f"unknown Rhubarb shape {value!r}")
        by_frame[start_frame + frames(float(cue["start"]), fps)] = shape_map.get(value, value)

    waypoints: list[Waypoint] = []
    for frame in sorted(by_frame):
        shape = by_frame[frame]
        if waypoints and waypoints[-1].value == shape:
            continue
        waypoints.append(Waypoint(frame, shape, Interp.CONSTANT))
    return Animated("string", tuple(waypoints))
