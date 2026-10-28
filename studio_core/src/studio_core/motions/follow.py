"""Follow-through for secondary bones (ears and tails): an additive layer after the main motions.

    channels = compose(clips)                       # what the actions did to the main bones
    layer = follow_through(view, channels, clips, fps=24, n_frames=240, energy=0.5)
    clips.append(layer)                             # additive: summed onto the bones' channels

A secondary bone does not act, it *reacts*: it trails its parent. Each one is a damped spring
that chases the angle its parent has at every frame; the bone's own offset is the spring's lag
(spring angle minus parent angle), so a head that tilts 15 degrees is followed a few frames
later by the ear and the ear overshoots a little before it settles. Per role:

- **ear:** also splays outward a little when the head or body drops (a nod, a bounce) and comes
  back with the same lag.
- **tail:** the segments chain (each chases the one before, so the tip trails most). The tail
  also sways with `idle_breathe` while it runs, lifts a little while the character travels, and
  trails the body's bob in a walk.

Pure functions of the keys and the frame rate (no randomness): the same shot gives the same
tracks. Energy 0..1 scales amplitude (gain, sway, splay) and the lag a little. Rigs without ear
or tail bones get no layer (None). The layer keeps every offset inside the bone's joint limits.
"""

from __future__ import annotations

import math
from typing import Any

from studio_core.motions.timeline import Channel, Clip, Key, sample
from studio_core.sif import Interp

SECONDARY_ROLES = ("ear", "tail")
SIGN_OUT = {"left": 1.0, "right": -1.0, "center": 0.0}  # +1: outward is clockwise
SUBSTEPS = 8  # the spring is stepped this many times per frame (stable at any lag)
EPS = 0.01  # degrees: below this a track counts as at rest


def secondary_bones(view: dict[str, Any]) -> list[str]:
    """Bones of role ear or tail, parents first."""
    out = [
        name
        for name, spec in view["bones"].items()
        if spec.get("role", name[:-2] if name.endswith(("_l", "_r")) else name) in SECONDARY_ROLES
    ]
    return sorted(out, key=lambda b: _depth(view, b))


def _depth(view: dict[str, Any], bone: str) -> int:
    n, current = 0, view["bones"][bone]["parent"]
    while current is not None:
        n, current = n + 1, view["bones"][current]["parent"]
    return n


def _role(view: dict[str, Any], name: str) -> str:
    return view["bones"][name].get("role", name[:-2] if name.endswith(("_l", "_r")) else name)


def _lerp(lo: float, hi: float, e: float) -> float:
    return lo + (hi - lo) * e


def spring_params(view: dict[str, Any], bone: str, energy: float) -> tuple[float, float, float]:
    """(lag in seconds, damping ratio, gain) for a bone: the role's defaults at this energy,
    overridden by the bone's own `follow` block."""
    role = _role(view, bone)
    if role == "ear":
        lag, damping, gain = _lerp(0.10, 0.06, energy), 0.5, _lerp(0.6, 1.0, energy)
    else:
        lag, damping, gain = _lerp(0.14, 0.09, energy), 0.35, 1.0
    own = view["bones"][bone].get("follow", {})
    return own.get("lag_s", lag), own.get("damping", damping), own.get("gain", gain)


def simulate(
    targets: list[float], lag_s: float, damping: float, fps: int, start: float | None = None
) -> list[float]:
    """The angle of a damped spring chasing `targets` (one per frame), at each frame. The natural
    frequency follows from the lag: a spring of damping z and frequency w trails a steadily
    moving target by 2z/w seconds. Starts at rest on the first target."""
    if not targets:
        return []
    w = 2 * damping / max(lag_s, 1e-3)
    dt = 1.0 / (fps * SUBSTEPS)
    a, v = (targets[0] if start is None else start), 0.0
    out = []
    for target in targets:
        for _ in range(SUBSTEPS):
            v += (w * w * (target - a) - 2 * damping * w * v) * dt
            a += v * dt
        out.append(a)
    return out


def _sampled(channels: dict[Channel, list[Key]], channel: Channel, frame: int) -> Any:
    keys = channels.get(channel)
    return sample(keys, frame) if keys else None


def _ancestors(view: dict[str, Any], bone: str) -> list[str]:
    out, current = [], view["bones"][bone]["parent"]
    while current is not None:
        out.append(current)
        current = view["bones"][current]["parent"]
    return out


def _parent_tracks(
    view: dict[str, Any], channels: dict[Channel, list[Key]], bone: str, n_frames: int
) -> tuple[list[float], list[float]]:
    """Per frame: the summed angle offset and the summed vertical shift (art px, up) of the
    bone's main-bone ancestors (the secondary ones are skipped: they are what we compute)."""
    angle, rise = [0.0] * n_frames, [0.0] * n_frames
    for anc in _ancestors(view, bone):
        if _role(view, anc) in SECONDARY_ROLES:
            continue
        for f in range(n_frames):
            a = _sampled(channels, ("angle", anc), f)
            s = _sampled(channels, ("shift", anc), f)
            angle[f] += 0.0 if a is None else float(a)
            rise[f] += 0.0 if s is None else float(s.y)
    return angle, rise


def _windows(clips: list[Clip], motions: tuple[str, ...]) -> list[tuple[int, int]]:
    return [(c.start, c.end) for c in clips if c.motion in motions]


def _ramp(f: int, window: tuple[int, int], fade: int, last: int) -> float:
    """0..1: eases in over `fade` frames from the window's start, out when it ends before the
    shot does."""
    start, end = window
    if f < start or f > end:
        return 0.0
    up = min(1.0, (f - start) / fade)
    down = 1.0 if end >= last else min(1.0, (end - f) / fade)
    return up * down


def _lag_sign(view: dict[str, Any], bone: str) -> float:
    """+1 when a tail trailing the body's rise turns counter-clockwise, -1 clockwise, 0 for a
    bone that points straight up or down (nothing to trail): it lags below the side it points."""
    c = math.cos(math.radians(view["bones"][bone]["direction_deg"]))
    return 0.0 if abs(c) < 0.2 else (-1.0 if c > 0 else 1.0)


def follow_through(
    view: dict[str, Any],
    channels: dict[Channel, list[Key]],
    clips: list[Clip],
    *,
    fps: int,
    n_frames: int,
    energy: float = 0.5,
    travel: list[float] | None = None,
) -> Clip | None:
    """The additive follow-through clip for a view's ears and tail, or None when the rig has
    none or nothing moves them. `channels` is `compose(clips)`: the main bones' tracks."""
    bones = secondary_bones(view)
    if not bones or n_frames < 2:
        return None
    energy = min(1.0, max(0.0, energy))
    last = n_frames - 1
    idle = _windows(clips, ("idle_breathe",))
    fade = max(1, round(0.5 * fps))
    ref_speed = sum(
        view["bones"][b].get("length_px", 0.0)
        for b in view["bones"]
        if _role(view, b) in ("torso", "head")
    )
    world: dict[str, list[float]] = {}  # each secondary bone's spring angle, by frame
    offsets: dict[str, list[float]] = {}
    for bone in bones:
        parent = view["bones"][bone]["parent"]
        lag_s, damping, gain = spring_params(view, bone, energy)
        angle, rise = _parent_tracks(view, channels, bone, n_frames)
        base = world.get(parent, angle)  # a tail segment chases the one before it
        role = _role(view, bone)
        target = list(base)
        if role == "ear":
            # dropping (rise < 0) turns the ear outward: clockwise for the left ear
            outward = SIGN_OUT[view["bones"][bone].get("side", "left")]
            splay = _lerp(0.2, 0.4, energy)
            target = [t + outward * splay * r for t, r in zip(target, rise, strict=True)]
        elif parent not in world:  # the tail's first segment takes the drivers
            sign = _lag_sign(view, bone)
            amp, period = _lerp(2.0, 5.0, energy), _lerp(2.8, 1.8, energy) * fps
            lift = _lerp(2.0, 6.0, energy)
            for f in range(n_frames):
                sway = 0.0
                for window in idle:
                    sway += (
                        _ramp(f, window, fade, last)
                        * amp
                        * math.sin(2 * math.pi * (f - window[0]) / period)
                    )
                run = 0.0
                if travel is not None and f + 1 < len(travel) and ref_speed > 0:
                    run = min(1.0, (travel[f + 1] - travel[f]) * fps / ref_speed)
                target[f] += sway + sign * _lerp(0.3, 0.6, energy) * rise[f] - sign * lift * run
        sprung = simulate(target, lag_s, damping, fps, start=target[0])
        world[bone] = sprung
        limits = view["bones"][bone].get("limits_deg", {"min": -360, "max": 360})
        offsets[bone] = [
            min(limits["max"], max(limits["min"], gain * (s - b)))
            for s, b in zip(sprung, base, strict=True)
        ]
    channels_out: dict[Channel, list[Key]] = {}
    for bone, values in offsets.items():
        live = [i for i, v in enumerate(values) if abs(v) > EPS]
        if not live:
            continue
        keep = sorted({j for i in live for j in (i - 1, i, i + 1) if 0 <= j < n_frames})
        channels_out[("angle", bone)] = [Key(f, values[f], Interp.LINEAR) for f in keep]
    if not channels_out:
        return None
    start = min(k[0].frame for k in channels_out.values())
    end = max(k[-1].frame for k in channels_out.values())
    return Clip("follow_through", start, end, channels_out, additive=True)
