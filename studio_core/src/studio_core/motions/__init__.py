"""Motion library: shot actions → per-bone tracks for `build_character`.

    anim = animate(rig.view(), actions, fps=24, n_frames=240, root_px=Vec(960, 990), scale=1.0)
    built = build_character(rig, None, space, offsets=anim.angles, shifts=anim.shifts,
                            attachments=face_attachments(view, space, eyes=anim.eyes or "open"))

`actions` are the shot spec's `characters[].actions` (motion, start_s, duration_s, params).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from studio_core.motions.library import MOTIONS, MotionContext, MotionError
from studio_core.motions.timeline import Clip, Key, compose, sample
from studio_core.rig import clamp_offset
from studio_core.sif import Angle, Animated, Interp, Vec, Waypoint, frames

__all__ = [
    "MOTIONS",
    "Animation",
    "Clip",
    "Key",
    "MotionContext",
    "MotionError",
    "animate",
    "compose",
    "sample",
]


@dataclass
class Animation:
    angles: dict[str, Animated] = field(default_factory=dict)  # bone → offsets from rest (Angle)
    shifts: dict[str, Animated] = field(default_factory=dict)  # bone → joint shift (Vec, art px)
    eyes: Animated | None = None  # eye-state track for the face
    clips: list[Clip] = field(default_factory=list)


def animate(
    view: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    fps: int,
    n_frames: int,
    root_px: Vec | None = None,
    scale: float = 1.0,
    seed: str = "",
) -> Animation:
    """Turn a character's actions into tracks. Unknown motions raise MotionError with the list of
    known ones; angle offsets are clamped to each bone's limits."""
    clips = []
    for action in actions:
        name = action["motion"]
        if name not in MOTIONS:
            raise MotionError(f"unknown motion {name!r}; known: {sorted(MOTIONS)}")
        start = frames(action["start_s"], fps)
        if start > n_frames - 1:
            raise MotionError(f"{name} starts at {action['start_s']}s, after the end of the shot")
        ctx = MotionContext(
            view=view,
            fps=fps,
            start=start,
            last_frame=n_frames - 1,
            duration=frames(action["duration_s"], fps) if "duration_s" in action else None,
            params=dict(action.get("params", {})),
            root_px=root_px or Vec(0, 0),
            scale=scale,
            seed=seed,
        )
        clips.append(MOTIONS[name](ctx))

    out = Animation(clips=clips)
    for (kind, bone), keys in compose(clips).items():
        if kind == "angle":
            out.angles[bone] = Animated(
                "angle",
                tuple(
                    Waypoint(k.frame, Angle(clamp_offset(view, bone, float(k.value))), k.interp)
                    for k in keys
                ),
            )
        elif kind == "shift":
            out.shifts[bone] = Animated(
                "vector", tuple(Waypoint(k.frame, k.value, k.interp) for k in keys)
            )
        elif kind == "eyes":
            out.eyes = Animated(
                "string", tuple(Waypoint(k.frame, k.value, Interp.CONSTANT) for k in keys)
            )
    return out
