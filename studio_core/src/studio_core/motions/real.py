"""Motions retargeted from real human motion capture (the `*_real` motions).

The clips live in `motions/real_clips/*.json` (built by `scripts/build_real_clips.py` from CMU
mocap, see studio_core/mocap/retarget.py). Here a clip is played on one puppet:

- the torso, head and arm tracks are angle offsets, used as they are (fitted into the bone's range);
- each leg is solved by two-bone IK so its ankle goes where the actor's ankle went relative to
  the hip, with the puppet's own thigh and shin lengths; the knee bends the way the actor's did;
- gaits (walk, run) are timed by the ground the character covers (`ctx.travel`), so the planted
  foot stays put: phase = distance / stride. Standing still, they play at the actor's own pace.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from functools import cache
from pathlib import Path

from studio_core.mocap.retarget import RealClip
from studio_core.motions.library import MotionContext, MotionError, _clip
from studio_core.motions.timeline import Channel, Clip, Key
from studio_core.rig import world_pose
from studio_core.sif import Interp, Vec

CLIPS_DIR = Path(__file__).parent / "real_clips"
L = Interp.LINEAR
# What a real gait needs beyond the front-view rig's default limits (thigh +-35, shin one way only):
# the knee bends the way a person's does, and a long stride swings the thigh a little further.
SHIN_RANGE = (-65.0, 65.0)
THIGH_RANGE = (-50.0, 50.0)
FOREARM_RANGE = (-100.0, 100.0)  # a wave flexes the elbow toward the head: the rig's other way
# Rigid cut-out parts open seams and holes where the head meets the shoulders when the head and
# torso rotate against each other (pose sweep, 4B.1), so their rotation is played smaller.
CUT_GAIN = {"head": 0.4, "torso": 0.5}
RANGES = {"thigh": THIGH_RANGE, "shin": SHIN_RANGE, "forearm": FOREARM_RANGE}
KNEE_SOFT = 35.0  # a knee bend beyond this eases toward SHIN_RANGE (rigid parts open when bent far)
SETTLE = 8  # frames for a one-shot to come back to rest at its end
BLEND = 5  # frames to fade a gait in from the rest pose and out again


@cache
def load_clip(name: str) -> RealClip:
    path = CLIPS_DIR / f"{name}.json"
    if not path.is_file():
        raise MotionError(f"no real-motion clip {name!r}; known: {sorted(available())}")
    return RealClip.from_json(json.loads(path.read_text()))


def available() -> list[str]:
    return sorted(p.stem for p in CLIPS_DIR.glob("*.json"))


# --------------------------------------------------------------------------- math


def fit_to_limits(values: list[float], lo: float, hi: float, floor: float = 0.5) -> list[float]:
    """Scale the positive and negative parts of a track down (never below `floor` of their size)
    so the track fits [lo, hi] without a flat clamp, then clamp what is left."""
    top, bottom = max(values), min(values)
    up = min(1.0, hi / top) if top > hi > 0 else 1.0
    down = min(1.0, lo / bottom) if bottom < lo < 0 else 1.0
    up, down = max(up, floor), max(down, floor)
    return [max(lo, min(hi, v * (up if v > 0 else down))) for v in values]


def two_bone_ik(
    l1: float, l2: float, tx: float, ty: float, bend: float
) -> tuple[float, float, float]:
    """Directions (degrees, world) of a two-bone chain from the origin whose end reaches (tx, ty),
    and the distance actually reached (the target is pulled in or out to what the bones can span).
    `bend` (+1 or -1) is the sign of upper cross lower: which way the middle joint points."""
    d = math.hypot(tx, ty)
    d_ok = min(max(d, abs(l1 - l2) + 1e-6), l1 + l2 - 1e-6)
    base = math.atan2(ty, tx) if d > 1e-9 else -math.pi / 2
    cos_a = (l1 * l1 + d_ok * d_ok - l2 * l2) / (2 * l1 * d_ok)
    a = math.acos(max(-1.0, min(1.0, cos_a)))
    for sign in (1.0, -1.0):
        t1 = base + sign * a
        kx, ky = l1 * math.cos(t1), l1 * math.sin(t1)
        ex, ey = tx / d * d_ok - kx if d > 1e-9 else 0.0, ty / d * d_ok - ky if d > 1e-9 else 0.0
        t2 = math.atan2(ey, ex)
        cross = kx * ey - ky * ex
        if cross * bend >= 0:
            return math.degrees(t1), math.degrees(t2), d_ok
    return math.degrees(t1), math.degrees(t2), d_ok  # unreachable


def soft_limit(value: float, start: float, cap: float) -> float:
    """Leave |value| <= start alone; beyond it ease toward `cap` (never reached): smooth and
    monotonic, so a deep bend keeps its shape instead of flattening against a wall."""
    a = abs(value)
    if a <= start:
        return value
    span = cap - start
    return math.copysign(start + span * math.tanh((a - start) / span), value)


def periodic(values: list[float], pos: float) -> float:
    """Linear interpolation of a loop at fractional index `pos` (wraps around)."""
    n = len(values)
    i = math.floor(pos)
    w = pos - i
    return values[i % n] * (1 - w) + values[(i + 1) % n] * w


def at(values: list[float], pos: float) -> float:
    """Linear interpolation of a one-shot at fractional index `pos` (holds the ends)."""
    pos = max(0.0, min(len(values) - 1.0, pos))
    i = min(int(pos), len(values) - 2)
    w = pos - i
    return values[i] * (1 - w) + values[i + 1] * w


# --------------------------------------------------------------------------- playing a clip


def _leg_rig(ctx: MotionContext, side: str) -> dict[str, float | str | tuple[float, float]]:
    thigh, shin = ctx.bone("thigh", side), ctx.bone("shin", side)
    bones = ctx.view["bones"]
    rest = world_pose(ctx.view)
    hip, d_thigh = rest[thigh]
    knee, d_shin = rest[shin]
    l1, l2 = bones[thigh]["length_px"], bones[shin]["length_px"]
    ankle = (
        knee.x + l2 * math.cos(math.radians(d_shin)),
        knee.y + l2 * math.sin(math.radians(d_shin)),
    )
    return {
        "thigh": thigh,
        "shin": shin,
        "l1": l1,
        "l2": l2,
        "rest": (ankle[0] - hip.x, ankle[1] - hip.y),
        "d_thigh": d_thigh,
        "d_shin": d_shin,
    }


def _legs(
    ctx: MotionContext,
    clip: RealClip,
    weights: list[float],
    index: Callable[[int], float],
    frames_: list[int],
    torso: list[float],
    loop: bool,
    lift: float,
    stretch: float,
) -> dict[Channel, list[Key]]:
    ch: dict[Channel, list[Key]] = {}
    get = periodic if loop else at
    for side in ("left", "right"):
        if not (ctx.has("thigh", side) and ctx.has("shin", side)):
            continue
        rig = _leg_rig(ctx, side)
        l1, l2 = float(rig["l1"]), float(rig["l2"])  # type: ignore[arg-type]
        lp = l1 + l2
        rx, ry = rig["rest"]  # type: ignore[misc]
        up, lo = [], []
        for k, f in enumerate(frames_):
            pos, w = index(f), weights[k]
            dx = get(clip.feet[side]["dx"], pos) * lp * w * stretch
            dy = get(clip.feet[side]["dy"], pos) * lp * w * lift
            # a gait puts the foot under the hip (the actor's stance); the rig's splay fades out
            x = (rx * (1 - w) if loop else rx) + dx
            if x == rx and dy == 0.0:  # exactly the rest pose: say so (the solver is a hair off)
                up.append(0.0)
                lo.append(0.0)
                continue
            t1, t2, _ = two_bone_ik(l1, l2, x, ry + dy, clip.knee[side])
            up.append(t1 - float(rig["d_thigh"]) - torso[k])  # type: ignore[arg-type]
            knee = t2 - t1 - (float(rig["d_shin"]) - float(rig["d_thigh"]))  # type: ignore[arg-type]
            lo.append(soft_limit(knee, KNEE_SOFT, SHIN_RANGE[1]))
        ch[("angle", str(rig["thigh"]))] = [Key(f, v, L) for f, v in zip(frames_, up, strict=True)]
        ch[("angle", str(rig["shin"]))] = [Key(f, v, L) for f, v in zip(frames_, lo, strict=True)]
    return ch


def _body(
    ctx: MotionContext,
    clip: RealClip,
    weights: list[float],
    index: Callable[[int], float],
    frames_: list[int],
    loop: bool,
    gain: float,
) -> tuple[dict[Channel, list[Key]], list[float]]:
    """Torso, head and arms; returns the channels and the torso offsets (the legs need them)."""
    get = periodic if loop else at
    ch: dict[Channel, list[Key]] = {}
    torso: list[float] = []
    for name, values in clip.tracks.items():
        role, _, side = name.partition(":")
        if not ctx.has(role, side or None):
            if role == "torso":
                torso = [0.0] * len(frames_)
            continue
        bone = ctx.bone(role, side or None)
        limits = ctx.view["bones"][bone].get("limits_deg")
        g = gain * CUT_GAIN.get(role, 1.0)
        series = [get(values, index(f)) * w * g for f, w in zip(frames_, weights, strict=True)]
        if limits and role not in ("thigh", "shin"):  # (the legs are solved by IK, not fitted)
            lo, hi = limits["min"], limits["max"]
            if role in RANGES:
                lo, hi = min(lo, RANGES[role][0]), max(hi, RANGES[role][1])
            series = fit_to_limits(series, lo, hi)
        if role == "torso":
            torso = series
        ch[("angle", bone)] = [Key(f, v, L) for f, v in zip(frames_, series, strict=True)]
    return ch, torso or [0.0] * len(frames_)


def _play(ctx: MotionContext, clip: RealClip, name: str) -> Clip:
    """Gait or one-shot, by the clip's kind."""
    p = ctx.params
    if clip.side and p.get("side", clip.side) != clip.side:
        clip = clip.mirrored()
    gain = ctx.lerp(0.85, 1.2) * float(p.get("amount", 1.0))
    leg_len = (
        sum(float(ctx.view["bones"][ctx.bone(r, "left")]["length_px"]) for r in ("thigh", "shin"))
        if ctx.has("thigh", "left") and ctx.has("shin", "left")
        else 0.0
    )
    root = ctx.bone("torso")
    speed = float(p.get("speed", 1.0))
    lift = float(p.get("lift", 1.0))
    stretch = 1.0
    if clip.loop:
        end = min(ctx.last_frame, ctx.start + ctx.duration) if ctx.duration else None
        travel = ctx.travel
        moving = (
            [
                f
                for f in range(ctx.start, (end if end is not None else ctx.last_frame))
                if travel[f + 1] - travel[f] > 1e-6
            ]
            if travel is not None
            else []
        )
        if moving and clip.stride_cycle and leg_len:
            f0, f1 = moving[0], moving[-1] + 1
            # whole half-cycles cover the distance, so the walk starts and ends on a passing pose;
            # steps stretch to fit (and the foot offsets with them, which keeps the foot planted)
            distance = travel[f1] - travel[f0]  # type: ignore[index]
            halves = max(1, round(2 * distance / (clip.stride_cycle * leg_len)))
            stride_px = distance / (halves / 2)
            stretch = stride_px / (clip.stride_cycle * leg_len)

            def index(f: int) -> float:
                return (travel[f] - travel[f0]) / stride_px * clip.frames  # type: ignore[index]

            frames_ = list(range(f0, f1 + 1))
        else:
            n = ctx.duration or ctx.frames(2.0 * clip.frames / clip.fps)
            f0 = ctx.start
            f1 = min(ctx.last_frame, f0 + n)
            frames_ = list(range(f0, f1 + 1))

            def index(f: int) -> float:
                return (f - f0) * speed

        n_f = len(frames_)
        weights = [
            min(1.0, k / BLEND, (n_f - 1 - k) / BLEND) if n_f > 2 * BLEND else 1.0
            for k in range(n_f)
        ]
        weights = [smooth(w) for w in weights]
        loop = True
    else:
        f0 = ctx.start
        n = max(2, round((clip.frames - 1) / speed))
        frames_ = [f for f in range(f0, f0 + n + 1) if f <= ctx.last_frame]

        def index(f: int) -> float:
            return (f - f0) * speed

        # the action ends standing: whatever the actor was doing in the last frames fades to rest
        tail = min(SETTLE, len(frames_) // 3)
        weights = [
            smooth(min(1.0, (len(frames_) - 1 - k) / tail)) if tail else 1.0
            for k in range(len(frames_))
        ]
        loop = False
    get = periodic if loop else at
    ch, torso = _body(ctx, clip, weights, index, frames_, loop, gain)
    if leg_len:
        ch.update(_legs(ctx, clip, weights, index, frames_, torso, loop, lift, stretch))
        drop = float(p.get("hop", 1.0))
        ch[("shift", root)] = [
            Key(f, Vec(0, get(clip.hip_drop, index(f)) * leg_len * w * drop), L)
            for f, w in zip(frames_, weights, strict=True)
        ]
    if frames_[0] > ctx.start:  # a walk that starts after the clip does: stand until then
        for channel, keys in ch.items():
            zero = Vec(0, 0) if channel[0] == "shift" else 0.0
            ch[channel] = [Key(ctx.start, zero, L), *keys]
    out = _clip(ctx, name, ch)
    out.limits = {
        bone: RANGES[role]
        for bone, role in (
            (ctx.bone(r, sd), r) for r in RANGES for sd in ("left", "right") if ctx.has(r, sd)
        )
    }
    return out


def smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def make_motion(motion: str, clip_name: str) -> Callable[[MotionContext], Clip]:
    def run(ctx: MotionContext) -> Clip:
        return _play(ctx, load_clip(clip_name), motion)

    run.__doc__ = f"Real human motion ({clip_name}), retargeted to this rig's bones."
    return run


REAL_MOTIONS: dict[str, str] = {  # motion name → clip file
    "walk_real": "walk",
    "run_real": "run",
    "wave_real": "wave",
    "jump_real": "jump",
    "shrug_real": "shrug",
}
MOTIONS: dict[str, Callable[[MotionContext], Clip]] = {
    m: make_motion(m, c) for m, c in REAL_MOTIONS.items() if (CLIPS_DIR / f"{c}.json").is_file()
}
