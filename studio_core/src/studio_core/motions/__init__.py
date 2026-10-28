"""Motion library: shot actions → per-bone tracks for `build_character`.

    anim = animate(rig.view(), actions, fps=24, n_frames=240, root_px=Vec(960, 990), scale=1.0)
    built = build_character(rig, None, space, offsets=anim.angles, shifts=anim.shifts,
                            attachments=face_attachments(view, space, eyes=anim.eyes or "open"))

`actions` are the shot spec's `characters[].actions` (motion, start_s, duration_s, params).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from studio_core.motions.follow import follow_through
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
    "follow_through",
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
    poses: list[dict[str, Any]] | None = None,
    travel: list[float] | None = None,
    secondary: bool = True,
) -> Animation:
    """Turn a character's actions into tracks. Unknown motions raise MotionError with the list of
    known ones; `travel` (distance covered per frame, from the placement path) makes walk_cycle
    step across the frame; angle offsets are clamped to each bone's limits. A rig with ear or tail
    bones also gets the follow-through layer (motions/follow.py) after the actions, at the mean
    energy of the actions; `secondary=False` leaves those bones at rest."""
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
            travel=travel,
        )
        clips.append(MOTIONS[name](ctx))

    for pose in poses or []:  # manual key poses (pose_at): one-frame override keys per bone
        f = frames(pose["time_s"], fps)
        if f > n_frames - 1:
            raise MotionError(f"pose at {pose['time_s']}s is after the end of the shot")
        unknown = sorted(set(pose["bones"]) - set(view["bones"]))
        if unknown:
            raise MotionError(f"pose names unknown bones {unknown}; known: {sorted(view['bones'])}")
        clips.append(
            Clip("pose", f, f, {("angle", b): [Key(f, float(a))] for b, a in pose["bones"].items()})
        )

    if secondary:
        energies = [float(a.get("params", {}).get("energy", 0.5)) for a in actions]
        layer = follow_through(
            view,
            compose(clips),
            clips,
            fps=fps,
            n_frames=n_frames,
            energy=sum(energies) / len(energies) if energies else 0.5,
            travel=travel,
        )
        if layer is not None:
            clips.append(layer)

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
