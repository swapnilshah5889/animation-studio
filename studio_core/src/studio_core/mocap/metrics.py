"""Numbers for judging a motion without looking at it (foot slide, jerk, range of motion).

Everything works on the keyed tracks `animate()` returns, so old and new motions are measured
the same way: sample every bone's angle and shift at each frame, run forward kinematics, and read
the feet off the result. Distances are in art pixels; a puppet's leg length makes them comparable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from studio_core.motions.timeline import Clip, compose, sample
from studio_core.rig import world_pose
from studio_core.sif import Vec


@dataclass
class FootTrack:
    x: list[float]  # ankle on the ground plane (art px, travel included)
    y: list[float]  # ankle height (art px, up)


def frame_offsets(view: dict[str, Any], clips: list[Clip], n_frames: int) -> list[dict[str, float]]:
    """Every bone's angle offset at each frame, clamped the way `animate()` clamps them (the
    rig's limits, widened by what the playing clips declare), so the numbers are what renders."""
    from studio_core.motions import _clamp, _widened  # local: motions imports this package's data

    channels = compose(clips)
    widened = _widened(clips)
    out = []
    for f in range(n_frames):
        offsets = {b: 0.0 for b in view["bones"]}
        for (kind, bone), keys in channels.items():
            if kind == "angle":
                offsets[bone] = _clamp(view, bone, float(sample(keys, f)), widened)  # type: ignore[arg-type]
        out.append(offsets)
    return out


def foot_tracks(
    view: dict[str, Any], clips: list[Clip], n_frames: int, travel: list[float] | None
) -> dict[str, FootTrack]:
    """Where each foot's ankle is at every frame, in the world (the hip's own travel included)."""
    channels = compose(clips)
    offsets = frame_offsets(view, clips, n_frames)
    root = next(b for b, s in view["bones"].items() if s["parent"] is None)
    legs = {
        side: (b, next(c for c, s in view["bones"].items() if s["parent"] == b))
        for b, s in view["bones"].items()
        if s.get("role") == "thigh" and (side := s.get("side")) in ("left", "right")
    }

    def shift_y(bone: str, f: int) -> float:
        keys = channels.get(("shift", bone))
        if not keys:
            return 0.0
        v = sample(keys, f)
        return v.y if isinstance(v, Vec) else 0.0

    out = {side: FootTrack([], []) for side in legs}
    for f in range(n_frames):
        pose = world_pose(view, offsets[f])
        for side, (thigh, shin) in legs.items():
            joint, direction = pose[shin]
            length = view["bones"][shin]["length_px"]
            x = joint.x + length * math.cos(math.radians(direction))
            y = joint.y + length * math.sin(math.radians(direction))
            out[side].x.append(x + (travel[f] if travel else 0.0))
            out[side].y.append(y + shift_y(root, f) + shift_y(thigh, f))
    return out


def contact_segments(
    feet: dict[str, FootTrack], leg: float, tol: float = 0.03, trim: float = 0.025
) -> dict[str, list[tuple[int, int]]]:
    """Runs of frames in which a foot is planted: within `tol` leg lengths of the lowest ankle
    height it reaches. The fast frames at both ends of a run (a foot still swinging in, or just
    leaving) are trimmed: a speed above `trim` leg lengths per frame is not standing."""
    floor = min(min(t.y) for t in feet.values())
    out: dict[str, list[tuple[int, int]]] = {}
    for side, t in feet.items():
        on = [y <= floor + tol * leg for y in t.y]
        runs, start = [], None
        for f, flag in enumerate([*on, False]):
            if flag and start is None:
                start = f
            elif not flag and start is not None:
                a, b = start, f - 1
                while a < b and abs(t.x[a + 1] - t.x[a]) > trim * leg:
                    a += 1
                while b > a and abs(t.x[b] - t.x[b - 1]) > trim * leg:
                    b -= 1
                if b - a >= 2:
                    runs.append((a, b))
                start = None
        out[side] = runs
    return out


def foot_slide(feet: dict[str, FootTrack], leg: float, tol: float = 0.03) -> dict[str, float]:
    """How far a planted foot slides along the ground, per contact (in leg lengths): the ankle's
    travel from the first to the last frame of each contact run. 0 = no skating."""
    slides = []
    for side, runs in contact_segments(feet, leg, tol).items():
        for a, b in runs:
            xs = feet[side].x[a : b + 1]
            slides.append((max(xs) - min(xs)) / leg)
    if not slides:
        return {"contacts": 0, "mean": 0.0, "max": 0.0}
    return {
        "contacts": len(slides),
        "mean": sum(slides) / len(slides),
        "max": max(slides),
    }


def jerk_rms(offsets: list[dict[str, float]], bones: list[str]) -> float:
    """RMS of the third difference of the angle tracks (degrees per frame³): low = smooth."""
    total, count = 0.0, 0
    for b in bones:
        v = [o[b] for o in offsets]
        for i in range(3, len(v)):
            j = v[i] - 3 * v[i - 1] + 3 * v[i - 2] - v[i - 3]
            total += j * j
            count += 1
    return math.sqrt(total / count) if count else 0.0


def range_of_motion(offsets: list[dict[str, float]], bones: list[str]) -> dict[str, float]:
    return {b: max(o[b] for o in offsets) - min(o[b] for o in offsets) for b in bones}


def accel_peak(offsets: list[dict[str, float]], bones: list[str]) -> float:
    """The largest frame-to-frame change of speed on any of the tracks (degrees per frame²): a
    hand-keyed zig-zag reverses in a single frame (big), a real swing eases through (small)."""
    peak = 0.0
    for b in bones:
        v = [o[b] for o in offsets]
        for i in range(2, len(v)):
            peak = max(peak, abs(v[i] - 2 * v[i - 1] + v[i - 2]))
    return peak
