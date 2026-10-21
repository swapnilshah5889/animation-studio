"""Motion library v1: named, parameterized motions → clips (task 2.5).

Every motion is a pure function of a `MotionContext`. Shared conventions:
- `energy` 0..1 scales amplitude (and a little speed): 0 = subtle, 1 = big.
- `side` picks a limb from the **character's** point of view; mirrored limbs rotate the other way
  (`SIGN`), so callers never think about signs.
- Motions start and end at the rest pose (offset 0), so they chain cleanly.
- Reversal points use `halt` (ease: speed 0 where the direction flips, like a pendulum);
  pass-through points use `clamped`. See synfig-format.md, "Animation".
- Bones are found by `role` + `side` (rig.schema.json), so motions work on any rig.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from studio_core.motions.timeline import Channel, Clip, Key, sample
from studio_core.rig import world_pose
from studio_core.sif import Interp, Vec

SIGN = {"left": 1.0, "right": -1.0}  # raising an arm: CCW for the character's left (front view)
E, C, L = Interp.EASE, Interp.CLAMPED, Interp.LINEAR


class MotionError(ValueError):
    pass


@dataclass
class MotionContext:
    view: dict[str, Any]  # one rig view (rig.json views.<name>)
    fps: int
    start: int  # first frame
    last_frame: int  # last frame of the shot (inclusive); clips are cut there
    duration: int | None = None  # requested length in frames, if any
    params: dict[str, Any] = field(default_factory=dict)
    root_px: Vec = field(default_factory=lambda: Vec(0, 0))  # character root on screen (px, y down)
    scale: float = 1.0  # art px → screen px
    seed: str = ""  # makes "random" choices (blink timing) repeatable

    @property
    def energy(self) -> float:
        return float(self.params.get("energy", 0.5))

    def frames(self, seconds: float) -> int:
        return max(1, round(seconds * self.fps))

    def lerp(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.energy

    def bone(self, role: str, side: str | None = None) -> str:
        for name, spec in self.view["bones"].items():
            if spec.get("role", _role_from_name(name)) != role:
                continue
            if side is None or spec.get("side", "center") in (side, "center"):
                return name
        where = f" on the {side} side" if side else ""
        raise MotionError(f"this rig has no {role!r} bone{where}")

    def has(self, role: str, side: str | None = None) -> bool:
        try:
            self.bone(role, side)
        except MotionError:
            return False
        return True


def _role_from_name(name: str) -> str:
    return name[:-2] if name.endswith(("_l", "_r")) else name


def _clip(
    ctx: MotionContext, motion: str, channels: dict[Channel, list[Key]], additive: bool = False
) -> Clip:
    """Cut keys at the end of the shot (keeping a key exactly at the cut) and wrap them up."""
    cut: dict[Channel, list[Key]] = {}
    for channel, keys in channels.items():
        keys = sorted({k.frame: k for k in keys}.values())
        inside = [k for k in keys if k.frame <= ctx.last_frame]
        if len(inside) < len(keys) and (not inside or inside[-1].frame < ctx.last_frame):
            inside.append(Key(ctx.last_frame, sample(keys, ctx.last_frame), keys[-1].interp))
        if inside:
            cut[channel] = inside
    if not cut:
        raise MotionError(f"{motion} starts after the end of the shot")
    end = max(k.frame for keys in cut.values() for k in keys)
    return Clip(motion, ctx.start, end, cut, additive)


def _cycles(ctx: MotionContext, default: int, per_cycle: int, overhead: int) -> int:
    """Explicit `cycles`, else as many as fit a requested duration, else the default."""
    if "cycles" in ctx.params:
        return int(ctx.params["cycles"])
    if ctx.duration:
        return max(1, round((ctx.duration - overhead) / per_cycle))
    return default


# --------------------------------------------------------------------------- motions


def wave(ctx: MotionContext) -> Clip:
    """Raise one arm and wave the forearm back and forth, then lower it."""
    side = ctx.params.get("side", "right")
    s = SIGN[side]
    up, swing, down = (
        ctx.frames(0.45 - 0.15 * ctx.energy),
        ctx.frames(0.32 - 0.1 * ctx.energy),
        ctx.frames(0.5),
    )
    cycles = _cycles(ctx, 3, 2 * swing, up + down)
    raise_deg, amp = ctx.lerp(120, 160), ctx.lerp(15, 35)
    t0 = ctx.start
    t_up = t0 + up
    fore = [Key(t0, 0.0), Key(t_up, s * amp * 0.3)]
    t = t_up
    for i in range(2 * cycles):
        t += swing
        fore.append(Key(t, s * (amp if i % 2 == 0 else -amp * 0.6)))
    t_end = t + max(1, swing // 2)
    fore.append(Key(t_end, s * amp * 0.3))
    fore.append(Key(t_end + down, 0.0))
    upper = [
        Key(t0, 0.0),
        Key(t_up, s * raise_deg),
        Key(t_end, s * raise_deg),
        Key(t_end + down, 0.0),
    ]
    return _clip(
        ctx,
        "wave",
        {
            ("angle", ctx.bone("upper_arm", side)): upper,
            ("angle", ctx.bone("forearm", side)): fore,
        },
    )


def nod(ctx: MotionContext) -> Clip:
    """Bob the head down and up (a nod, seen from the front)."""
    down, up = ctx.frames(0.18), ctx.frames(0.22)
    cycles = _cycles(ctx, 2, down + up, 0)
    depth = ctx.lerp(5, 14)
    keys = [Key(ctx.start, Vec(0, 0))]
    t = ctx.start
    for _ in range(cycles):
        t += down
        keys.append(Key(t, Vec(0, -depth)))
        t += up
        keys.append(Key(t, Vec(0, 0)))
    return _clip(ctx, "nod", {("shift", ctx.bone("head")): keys})


def head_tilt(ctx: MotionContext) -> Clip:
    """Tilt the head to one side, hold, and come back."""
    side = ctx.params.get("side", "left")
    into, out = ctx.frames(0.3), ctx.frames(0.3)
    hold = (ctx.duration - into - out) if ctx.duration else ctx.frames(1.0)
    angle = SIGN[side] * ctx.lerp(8, 20)
    t1 = ctx.start + into
    t2 = t1 + max(1, hold)
    keys = [Key(ctx.start, 0.0), Key(t1, angle), Key(t2, angle), Key(t2 + out, 0.0)]
    return _clip(ctx, "head_tilt", {("angle", ctx.bone("head")): keys})


def idle_breathe(ctx: MotionContext) -> Clip:
    """Additive: a slow rise and fall of the head and a slight arm sway, until the shot ends."""
    period = ctx.frames(ctx.lerp(4.0, 3.0))
    end = ctx.start + ctx.duration if ctx.duration else ctx.last_frame
    rise, sway = ctx.lerp(1.5, 4.0), ctx.lerp(0.8, 2.0)
    head: list[Key] = []
    arms: dict[str, list[Key]] = {s: [] for s in SIGN if ctx.has("upper_arm", s)}
    t = ctx.start
    while t <= end:
        head += [Key(t, Vec(0, 0)), Key(min(t + period // 2, end), Vec(0, rise))]
        for side in arms:
            arms[side] += [Key(t, 0.0), Key(min(t + period // 2, end), SIGN[side] * sway)]
        t += period
    if head[-1].frame < end:  # keep breathing right up to the end (mid-breath is fine)
        head.append(Key(end, sample([*head, Key(t, Vec(0, 0))], end)))
        for side in arms:
            arms[side].append(Key(end, sample([*arms[side], Key(t, 0.0)], end)))
    channels: dict[Channel, list[Key]] = {("shift", ctx.bone("head")): head}
    for side, keys in arms.items():
        channels[("angle", ctx.bone("upper_arm", side))] = keys
    return _clip(ctx, "idle_breathe", channels, additive=True)


def blink(ctx: MotionContext) -> Clip:
    """Eye blinks at natural, slightly irregular intervals (repeatable via the seed)."""
    end = ctx.start + ctx.duration if ctx.duration else ctx.last_frame
    interval = ctx.lerp(4.0, 2.5)
    digest = hashlib.sha256(f"{ctx.seed}:{ctx.start}".encode()).digest()
    keys = [Key(ctx.start, "open", Interp.CONSTANT)]
    t = ctx.start + ctx.frames(0.4)  # first blink soon after the start
    i = 0
    while t + 3 <= end:
        for k, state in enumerate(("half", "closed", "half", "open")):
            keys.append(Key(t + k, state, Interp.CONSTANT))
        jitter = (digest[i % len(digest)] / 255 - 0.5) * 1.2  # ±0.6 s
        t += max(5, ctx.frames(interval + jitter))
        i += 1
    return _clip(ctx, "blink", {("eyes", ""): keys})


def walk_cycle(ctx: MotionContext) -> Clip:
    """Walk in place, seen from the front: legs lift in turn (a march), the body bobs, the arms
    swing a little. A front view can't show legs swinging forward, so a sideways swing would look
    like stumbling; lifting the leg's joint reads as stepping."""
    step = ctx.frames(ctx.lerp(0.6, 0.4))
    steps = _cycles(ctx, 4, step, step)
    lift, knee, arm, bob = ctx.lerp(10, 24), ctx.lerp(2, 6), ctx.lerp(6, 16), ctx.lerp(2, 6)
    sides = [s for s in SIGN if ctx.has("thigh", s)]
    root = ctx.bone("torso")
    ch: dict[Channel, list[Key]] = {("shift", root): [Key(ctx.start, Vec(0, 0))]}
    for side in sides:
        ch[("shift", ctx.bone("thigh", side))] = [Key(ctx.start, Vec(0, 0))]
        ch[("angle", ctx.bone("thigh", side))] = [Key(ctx.start, 0.0)]
        if ctx.has("upper_arm", side):
            ch[("angle", ctx.bone("upper_arm", side))] = [Key(ctx.start, 0.0)]
    t = ctx.start
    for i in range(steps):
        t_mid, t_end = t + step // 2, t + step
        lead = sides[i % len(sides)] if sides else None
        for side in sides:
            up = side == lead
            ch[("shift", ctx.bone("thigh", side))] += [
                Key(t_mid, Vec(0, lift if up else 0)),
                Key(t_end, Vec(0, 0)),
            ]
            ch[("angle", ctx.bone("thigh", side))] += [
                Key(t_mid, SIGN[side] * knee if up else 0.0),
                Key(t_end, 0.0),
            ]
            if ctx.has("upper_arm", side):
                # The arm opposite the lifted leg swings out a little.
                ch[("angle", ctx.bone("upper_arm", side))].append(
                    Key(t_mid, 0.0 if up else SIGN[side] * arm)
                )
        ch[("shift", root)] += [Key(t_mid, Vec(0, bob)), Key(t_end, Vec(0, 0))]
        t = t_end
    for side in sides:
        if ctx.has("upper_arm", side):
            ch[("angle", ctx.bone("upper_arm", side))].append(Key(t, 0.0))
    return _clip(ctx, "walk_cycle", ch)


def jump(ctx: MotionContext) -> Clip:
    """Crouch, spring up with the arms raised, land with a little squash."""
    height, squash = ctx.lerp(60, 160), ctx.lerp(8, 20)
    crouch, rise, hang, fall, land, settle = (
        ctx.frames(x) for x in (0.25, 0.18, 0.12, 0.2, 0.08, 0.25)
    )
    t = [ctx.start]
    for d in (crouch, rise, hang, fall, land, settle):
        t.append(t[-1] + d)
    root = ctx.bone("torso")
    ch: dict[Channel, list[Key]] = {
        ("shift", root): [
            Key(t[0], Vec(0, 0)),
            Key(t[1], Vec(0, -squash)),
            Key(t[2], Vec(0, height), C),
            Key(t[3], Vec(0, height)),
            Key(t[4], Vec(0, 0), L),
            Key(t[5], Vec(0, -squash * 0.6)),
            Key(t[6], Vec(0, 0)),
        ],
    }
    for side in SIGN:
        s = SIGN[side]
        if ctx.has("upper_arm", side):
            ch[("angle", ctx.bone("upper_arm", side))] = [
                Key(t[0], 0.0),
                Key(t[1], -s * 20),
                Key(t[2], s * ctx.lerp(110, 150)),
                Key(t[4], s * 40),
                Key(t[6], 0.0),
            ]
        if ctx.has("thigh", side):
            ch[("angle", ctx.bone("thigh", side))] = [
                Key(t[0], 0.0),
                Key(t[1], s * 10),
                Key(t[2], -s * 4),
                Key(t[4], s * 8),
                Key(t[6], 0.0),
            ]
    return _clip(ctx, "jump", ch)


def point(ctx: MotionContext) -> Clip:
    """Point one arm at a spot in the frame (params.target), hold, lower it."""
    target = ctx.params.get("target")
    side = ctx.params.get("side")
    rest = world_pose(ctx.view)

    def shoulder_screen(sd: str) -> Vec:
        joint = rest[ctx.bone("upper_arm", sd)][0]
        return Vec(ctx.root_px.x + joint.x * ctx.scale, ctx.root_px.y - joint.y * ctx.scale)

    if side is None:
        # Front view: the character's left arm is on the viewer's right.
        side = "left" if target is None or target[0] * 1.0 >= ctx.root_px.x else "right"
    bone = ctx.bone("upper_arm", side)
    if target is None:
        offset = SIGN[side] * 90.0  # straight out to the side
    else:
        sh = shoulder_screen(side)
        direction = math.degrees(math.atan2(-(target[1] - sh.y), target[0] - sh.x))  # y up
        offset = (direction - ctx.view["bones"][bone]["direction_deg"] + 180) % 360 - 180
    into, out = ctx.frames(0.35), ctx.frames(0.4)
    hold = (ctx.duration - into - out) if ctx.duration else ctx.frames(1.2)
    t1 = ctx.start + into
    t2 = t1 + max(1, hold)
    keys = [Key(ctx.start, 0.0), Key(t1, offset), Key(t2, offset), Key(t2 + out, 0.0)]
    ch: dict[Channel, list[Key]] = {("angle", bone): keys}
    if ctx.has("forearm", side):
        ch[("angle", ctx.bone("forearm", side))] = [
            Key(ctx.start, 0.0),
            Key(t1, 0.0),
            Key(t2 + out, 0.0),
        ]
    return _clip(ctx, "point", ch)


def talk_gesture(ctx: MotionContext) -> Clip:
    """Small explaining gestures with one hand, with little head tilts on the beats."""
    side = ctx.params.get("side", "right")
    s = SIGN[side]
    beat = ctx.frames(0.6)
    beats = _cycles(ctx, 2, beat, ctx.frames(0.3))
    up_deg, fore_deg = ctx.lerp(10, 25), ctx.lerp(18, 40)
    upper, fore, head = [Key(ctx.start, 0.0)], [Key(ctx.start, 0.0)], [Key(ctx.start, 0.0)]
    t = ctx.start
    for i in range(beats):
        t_hit, t_rel = t + beat // 3, t + beat
        upper += [Key(t_hit, s * up_deg), Key(t_rel, s * up_deg * 0.6)]
        fore += [Key(t_hit, s * fore_deg), Key(t_rel, s * fore_deg * 0.5)]
        head += [Key(t_hit, (3.0 if i % 2 == 0 else -3.0)), Key(t_rel, 0.0)]
        t = t_rel
    settle = ctx.frames(0.3)
    upper.append(Key(t + settle, 0.0))
    fore.append(Key(t + settle, 0.0))
    return _clip(
        ctx,
        "talk_gesture",
        {
            ("angle", ctx.bone("upper_arm", side)): upper,
            ("angle", ctx.bone("forearm", side)): fore,
            ("angle", ctx.bone("head")): head,
        },
    )


MOTIONS: dict[str, Callable[[MotionContext], Clip]] = {
    "idle_breathe": idle_breathe,
    "blink": blink,
    "wave": wave,
    "nod": nod,
    "head_tilt": head_tilt,
    "walk_cycle": walk_cycle,
    "jump": jump,
    "point": point,
    "talk_gesture": talk_gesture,
}
