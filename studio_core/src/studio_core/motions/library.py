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
from studio_core.rig import chain, world_pose
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
    # Distance the character has travelled forward by each frame (cumulative, art px), from its
    # placement path; None = it stands still. walk_cycle steps in time with it.
    travel: list[float] | None = None

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

    def hand(self, side: str, keys: list[tuple[int, str]]) -> dict[Channel, list[Key]]:
        """Hand-pose keys (frame, pose) for `side`'s hand: {} when the rig has no hands there. A
        pose the rig does not have becomes `rest`; keys all at rest add nothing."""
        if not self.has("forearm", side):
            return {}
        bone = self.bone("forearm", side)
        hand = self.view.get("hands", {}).get(bone)
        if hand is None:
            return {}
        poses = [(f, p if p in hand["poses"] else "rest") for f, p in keys]
        if all(p == "rest" for _, p in poses):
            return {}
        return {("hand", bone): [Key(f, p, Interp.CONSTANT) for f, p in poses]}

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


def _clear_raise(
    ctx: MotionContext, side: str, target: float, swing: float, lowest: float = 90.0
) -> float:
    """The largest arm raise ≤ `target` (degrees from rest, 5° steps) at which the raised hand
    stays clear of the head (its parts' rest box), even with the forearm swung `swing`
    degrees toward it. A big-headed character's wave would otherwise hide behind its own ears
    (Kit, task 4.4). Pip keeps the full raise up to energy 0.75; above that his hand also
    passed behind his head on the inward swing, so it stops at 150°."""
    if not ctx.has("head"):
        return target
    view, head = ctx.view, ctx.bone("head")
    upper, fore = ctx.bone("upper_arm", side), ctx.bone("forearm", side)
    rest = world_pose(view)
    hj = rest[head][0]
    lefts, rights = [], []
    for part in view["parts"].values():
        if head in chain(view, part["bone"]):  # the head and what hangs from it (ears)
            joint = rest[part["bone"]][0]
            lefts.append(joint.x - part["pivot_px"][0])
            rights.append(joint.x + part["size_px"][0] - part["pivot_px"][0])
    length = view["bones"][fore]["length_px"]
    outward = 1.0 if rest[upper][0].x > hj.x else -1.0  # which side of the head the arm is on
    edge = max(rights) if outward > 0 else min(lefts)
    raise_deg = target
    while raise_deg > lowest:
        pose = world_pose(view, {upper: SIGN[side] * raise_deg, fore: SIGN[side] * swing})
        joint, direction = pose[fore]
        hand_x = joint.x + length * math.cos(math.radians(direction))
        if outward * (hand_x - edge) >= 0:
            break
        raise_deg -= 5.0
    return max(raise_deg, lowest)


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
    amp = ctx.lerp(15, 35)
    raise_deg = _clear_raise(ctx, side, ctx.lerp(120, 160), swing=amp)
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
    hand = ctx.hand(side, [(t0, "rest"), (t0 + up // 2, "wave"), (t_end + down // 2, "rest")])
    return _clip(
        ctx,
        "wave",
        {
            ("angle", ctx.bone("upper_arm", side)): upper,
            ("angle", ctx.bone("forearm", side)): fore,
            **hand,
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


STRIDE = 0.8  # nominal hip travel per step, as a fraction of the leg length
MAX_STRIDE = 1.0  # a step never exceeds this (the thigh's joint limit allows about 1.1)
FOOT_LIFT = 0.12  # how high the swinging foot rises, as a fraction of the leg length


def _leg(ctx: MotionContext, side: str) -> tuple[float, float, str]:
    """(foot offset from the hip along x, leg length, thigh bone) at rest, in art px: the foot
    is the bottom-centre of the lowest part hanging from the thigh."""
    thigh = ctx.bone("thigh", side)
    rest = world_pose(ctx.view)
    hip = rest[thigh][0]
    low_y, low_x = hip.y, hip.x
    for part in ctx.view["parts"].values():
        if thigh not in chain(ctx.view, part["bone"]):
            continue
        joint = rest[part["bone"]][0]
        bottom = joint.y - (part["size_px"][1] - part["pivot_px"][1])
        if bottom < low_y:
            low_y = bottom
            low_x = joint.x + part["size_px"][0] / 2 - part["pivot_px"][0]
    return low_x - hip.x, hip.y - low_y, thigh


def foot_angle(offset: float, length: float, reach: float, lo: float, hi: float) -> float:
    """The thigh angle (degrees, CCW positive, within [lo, hi]) that puts a foot hanging
    (offset, -length) below the hip at x = reach: solves offset*cos + length*sin = reach."""

    def x_at(deg: float) -> float:
        r = math.radians(deg)
        return offset * math.cos(r) + length * math.sin(r)

    if reach <= x_at(lo):
        return lo
    if reach >= x_at(hi):
        return hi
    a, b = lo, hi
    for _ in range(40):
        mid = (a + b) / 2
        a, b = (mid, b) if x_at(mid) < reach else (a, mid)
    return (a + b) / 2


def stride_plan(distance: float, leg: float) -> tuple[int, float]:
    """(steps, stride): how many steps cover `distance` px with legs of `leg` px, and the hip
    travel per step. The walk starts and ends in the rest pose, so the gait covers the
    distance in `steps` strides (two half steps count as one)."""
    steps = max(1, round(distance / (STRIDE * leg)))
    if distance / steps > MAX_STRIDE * leg:
        steps = math.ceil(distance / (MAX_STRIDE * leg))
    return steps, distance / steps


def _stride_walk(ctx: MotionContext) -> Clip | None:
    """Walk across the frame: each foot is planted on the ground while the hip travels over it
    (it does not slide), the other leg swings forward. Steps are timed by the distance covered
    (ctx.travel), so a slow start or an eased stop takes small, slow steps. None when the
    character does not move during the walk or the rig has no pair of legs."""
    travel = ctx.travel
    if travel is None or not (ctx.has("thigh", "left") and ctx.has("thigh", "right")):
        return None
    end = min(ctx.last_frame, ctx.start + ctx.duration) if ctx.duration else ctx.last_frame
    moving = [f for f in range(ctx.start, end) if travel[f + 1] - travel[f] > 1e-6]
    if not moving:
        return None
    f0, f1 = moving[0], moving[-1] + 1
    legs = {side: _leg(ctx, side) for side in SIGN}
    length = min(leg[1] for leg in legs.values())
    steps, stride = stride_plan(travel[f1] - travel[f0], length)
    lift_px = FOOT_LIFT * length
    arm = ctx.lerp(8, 18)
    root = ctx.bone("torso")
    sides = list(SIGN)  # sides[k % 2] is planted during step k
    limits = {s: ctx.view["bones"][legs[s][2]]["limits_deg"] for s in sides}
    ch: dict[Channel, list[Key]] = {("shift", root): []}
    for side in sides:
        ch[("shift", legs[side][2])] = []
        ch[("angle", legs[side][2])] = []
        if ctx.has("upper_arm", side):
            ch[("angle", ctx.bone("upper_arm", side))] = []
    rest_frames = [ctx.start] if ctx.start < f0 else []
    for f in rest_frames:
        for channel, keys in ch.items():
            keys.append(Key(f, Vec(0, 0) if channel[0] == "shift" else 0.0, L))
    for f in range(f0, f1 + 1):
        s = (travel[f] - travel[f0]) / stride  # strides walked, 0..steps
        g = 0.5 + s  # gait phase: step k = floor(g), progress u = g - k
        k = min(int(g), steps)
        u = g - k
        hip = s * stride  # hip x from where the walk started
        fade = min(1.0, 40 * s, 40 * (steps - s))  # the foot settles at the first and last steps
        phi: dict[str, float] = {}
        drop = 0.0
        for side in sides:
            offset, leg_len, thigh = legs[side]
            if sides[k % 2] == side:  # planted at the hip position of step k's middle
                reach = k * stride - hip + offset
            else:  # swings from the foot's last spot (k-1) to its next (k+1)
                sm = u * u * (3 - 2 * u)
                reach = (k - 1) * stride + 2 * stride * sm - hip + offset
            lim = limits[side]
            phi[side] = foot_angle(offset, leg_len, reach, lim["min"], lim["max"])
            ch[("angle", thigh)].append(Key(f, phi[side], L))
            if sides[k % 2] == side:  # the planted foot rises as its leg tilts: lower the body
                r = math.radians(phi[side])
                drop = -(offset * math.sin(r) - leg_len * math.cos(r) + leg_len)
            lift = 0.0 if sides[k % 2] == side else lift_px * math.sin(math.pi * u) * fade
            ch[("shift", thigh)].append(Key(f, Vec(0, lift), L))
        ch[("shift", root)].append(Key(f, Vec(0, drop), L))
        span = max(abs(limits[s_]["max"]) for s_ in sides)
        for side in sides:
            if ctx.has("upper_arm", side):  # arms swing against the same-side leg
                swing = -arm * phi[side] / span
                ch[("angle", ctx.bone("upper_arm", side))].append(Key(f, swing, L))
    return _clip(ctx, "walk_cycle", ch)


def walk_cycle(ctx: MotionContext) -> Clip:
    """Walk. When the character moves across the frame during the walk (its placement path), the
    feet are planted and the steps follow the distance covered (_stride_walk). Standing still, it
    marches in place, seen from the front: legs lift in turn, the body bobs, the arms swing a
    little. A front view can't show legs swinging forward, so a sideways swing would look
    like stumbling; lifting the leg's joint reads as stepping."""
    if (stride := _stride_walk(ctx)) is not None:
        return stride
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


def walk_step(ctx: MotionContext) -> Clip:
    """A front-view walk across the frame with a visible gait (D-096): `walk_cycle`'s planted
    feet, plus a higher eased foot lift, a knee bend on the lifted leg (the foot tucks toward the
    direction of travel, `params.dir` = 1 right, -1 left), a body bob at every step (up at
    mid-swing, two per cycle) and a small torso sway toward the planted leg. The motion data
    stays in code: everything derives from the lift the stride already computes."""
    base = walk_cycle(ctx)
    sides = [s for s in SIGN if ctx.has("thigh", s) and ctx.has("shin", s)]
    if not sides or ("shift", ctx.bone("thigh", sides[0])) not in base.channels:
        return base
    direction = 1.0 if float(ctx.params.get("dir", 1.0)) >= 0 else -1.0
    gain = ctx.lerp(1.2, 1.7)  # the foot rises this many times walk_cycle's lift
    knee, bob, sway = ctx.lerp(22, 42), ctx.lerp(5, 12), ctx.lerp(1.5, 3.0)
    lifts: dict[str, dict[int, float]] = {}
    for side in sides:
        thigh = ctx.bone("thigh", side)
        keys = [
            Key(k.frame, Vec(k.value.x, k.value.y * gain), k.interp)
            for k in base.channels[("shift", thigh)]
        ]
        base.channels[("shift", thigh)] = keys
        lifts[side] = {k.frame: k.value.y for k in keys}
    peak = max((v for d in lifts.values() for v in d.values()), default=0.0) or 1.0
    frames = sorted({f for d in lifts.values() for f in d})
    limits: dict[str, tuple[float, float]] = {}
    for side in sides:
        shin = ctx.bone("shin", side)
        base.channels[("angle", shin)] = [
            Key(f, direction * knee * min(1.0, lifts[side].get(f, 0.0) / peak), L) for f in frames
        ]
        lim = ctx.view["bones"][shin]["limits_deg"]
        limits[shin] = (min(lim["min"], -knee), max(lim["max"], knee))
    root = ctx.bone("torso")
    drop = {k.frame: k.value for k in base.channels.get(("shift", root), [])}
    base.channels[("shift", root)] = [
        Key(
            f,
            Vec(
                drop[f].x if f in drop else 0.0,
                (drop[f].y if f in drop else 0.0)
                + bob * sum(lifts[s].get(f, 0.0) for s in sides) / peak,
            ),
            L,
        )
        for f in frames
    ]
    if len(sides) == 2:
        a, b = sides
        base.channels[("angle", root)] = [
            Key(f, sway * (lifts[b].get(f, 0.0) - lifts[a].get(f, 0.0)) / peak * direction, L)
            for f in frames
        ]
    base.limits.update(limits)
    base.motion = "walk_step"
    return base


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
    # Anticipation: the arm dips back a few degrees first. Overshoot: it swings 5° past the target
    # and settles, so the point has a flick rather than a glide.
    wind, past = ctx.frames(0.1), math.copysign(5.0, offset)
    back = -math.copysign(min(6.0, abs(offset) * 0.1), offset)
    keys = [
        Key(ctx.start, 0.0),
        Key(ctx.start + wind, back),
        Key(t1 + wind, offset + past),
        Key(t1 + wind + ctx.frames(0.12), offset),
        Key(t2 + wind, offset),
        Key(t2 + wind + out, 0.0),
    ]
    ch: dict[Channel, list[Key]] = {("angle", bone): keys}
    if ctx.has("forearm", side):
        ch[("angle", ctx.bone("forearm", side))] = [
            Key(ctx.start, 0.0),
            Key(t1 + wind, 0.0),
            Key(t2 + wind + out, 0.0),
        ]
    ch.update(
        ctx.hand(
            side, [(ctx.start, "rest"), (ctx.start + wind, "point"), (t2 + wind + out // 2, "rest")]
        )
    )
    return _clip(ctx, "point", ch)


def talk_gesture(ctx: MotionContext) -> Clip:
    """Small explaining gestures with one hand, with little head tilts on the beats."""
    side = ctx.params.get("side", "right")
    s = SIGN[side]
    beat = ctx.frames(0.6)
    beats = _cycles(ctx, 2, beat, ctx.frames(0.3))
    up_deg, fore_deg = ctx.lerp(10, 25), ctx.lerp(18, 40)
    upper, fore, head = [Key(ctx.start, 0.0)], [Key(ctx.start, 0.0)], [Key(ctx.start, 0.0)]
    hand = [(ctx.start, "rest")]
    t = ctx.start
    for i in range(beats):
        t_hit, t_rel = t + beat // 3, t + beat
        hand += [(t_hit, "open"), (t_rel - 1, "rest")]  # the palm opens on each beat
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
            **ctx.hand(side, hand),
        },
    )


# --------------------------------------------------------------------------- acting motions
# Small reusable beats for children's shorts. All are front-view safe: parts rotate in the
# picture plane and joints shift, nothing turns toward or away from the viewer. Each ends at rest.

Pairs = list[tuple[int, float]]


def _envelope(
    start: int, anticipate: int, into: int, hold: int, out: int, relax: float = 0.92
) -> Pairs:
    """(frame, fraction of the peak) keys for a pose that is reached, held and released:
    a small opposite move first (anticipation, -12%), the peak, a 'moving hold' that relaxes a
    little instead of freezing, then back to rest."""
    pairs: Pairs = [(start, 0.0)]
    t = start
    if anticipate:
        t += anticipate
        pairs.append((t, -0.12))
    t += into
    pairs.append((t, 1.0))
    if hold >= 2:
        pairs.append((t + hold // 2, relax))
        t += hold
        pairs.append((t, (1.0 + relax) / 2))
    else:
        t += 1
        pairs.append((t, 1.0))
    pairs.append((t + out, 0.0))
    return pairs


def _angles(pairs: Pairs, amp: float) -> list[Key]:
    return [Key(f, frac * amp) for f, frac in pairs]


def _shifts(pairs: Pairs, dx: float, dy: float) -> list[Key]:
    return [Key(f, Vec(dx * frac, dy * frac)) for f, frac in pairs]


def _hold(ctx: MotionContext, into: int, out: int, anticipate: int, default_s: float) -> int:
    """Frames to hold the pose: what is left of a requested duration, else `default_s`."""
    if ctx.duration:
        return max(1, ctx.duration - into - out - anticipate)
    return ctx.frames(default_s)


def shrug(ctx: MotionContext) -> Clip:
    """Shrug ("I don't know"): the head rises toward the shoulders and tilts, both arms open out
    a little with the forearms turned up, hold, and relax. Front view: the shoulders are not
    parts, so the head lift and the open arms carry it. `side` is the way the head tilts."""
    side = ctx.params.get("side", "left")
    ant, into, out = ctx.frames(0.08), ctx.frames(0.16), ctx.frames(0.32)
    pairs = _envelope(ctx.start, ant, into, _hold(ctx, into, out, ant, 0.7), out)
    ch: dict[Channel, list[Key]] = {
        ("shift", ctx.bone("head")): _shifts(pairs, 0, ctx.lerp(4, 10)),
        ("angle", ctx.bone("head")): _angles(pairs, SIGN[side] * ctx.lerp(4, 10)),
    }
    for sd in SIGN:
        if ctx.has("upper_arm", sd):
            ch[("angle", ctx.bone("upper_arm", sd))] = _angles(pairs, SIGN[sd] * ctx.lerp(12, 28))
        if ctx.has("forearm", sd):
            ch[("angle", ctx.bone("forearm", sd))] = _angles(pairs, SIGN[sd] * ctx.lerp(25, 55))
    return _clip(ctx, "shrug", ch)


def bow(ctx: MotionContext) -> Clip:
    """Bow politely: a small rise first, then the head dips and the body sinks, hold, and rise
    again. Front view: a real bow pitches the head and torso forward, which a flat cut-out
    cannot do, so the head drops (more than the body) the way nod does, but slower and deeper."""
    ant, into, out = ctx.frames(0.1), ctx.frames(0.45 - 0.1 * ctx.energy), ctx.frames(0.5)
    pairs = _envelope(ctx.start, ant, into, _hold(ctx, into, out, ant, 0.6), out)
    return _clip(
        ctx,
        "bow",
        {
            ("shift", ctx.bone("torso")): _shifts(pairs, 0, -ctx.lerp(3, 8)),
            ("shift", ctx.bone("head")): _shifts(pairs, 0, -ctx.lerp(14, 32)),
        },
    )


def look_around(ctx: MotionContext) -> Clip:
    """Glance one way, then the other, and come back to centre. Front view: the head cannot
    turn, so it slides sideways a little and leans into each glance; the face stays front-on.
    `side` is the first glance (the character's own side); `cycles` repeats the left-right pair."""
    side = ctx.params.get("side", "left")
    cycles = int(ctx.params.get("cycles", 1))
    move, dwell = ctx.frames(0.25 - 0.08 * ctx.energy), ctx.frames(0.5)
    reach, lean = ctx.lerp(3, 7), ctx.lerp(4, 9)
    first = 1.0 if side == "left" else -1.0  # the character's left is the viewer's right (+x)
    shift: list[Key] = [Key(ctx.start, Vec(0, 0))]
    tilt: list[Key] = [Key(ctx.start, 0.0)]
    t = ctx.start + ctx.frames(0.08)  # anticipation: a small move the other way first
    shift.append(Key(t, Vec(-first * reach * 0.15, 0)))
    tilt.append(Key(t, first * lean * 0.15))
    for i in range(2 * cycles):
        amount = first * (1.0 if i % 2 == 0 else -0.8)  # the return glance is a little shorter
        t += move
        shift.append(Key(t, Vec(amount * reach, 0)))
        tilt.append(Key(t, -amount * lean))
        t += dwell
        shift.append(Key(t, Vec(amount * reach * 0.94, 0)))  # moving hold
        tilt.append(Key(t, -amount * lean * 0.94))
    t += move
    shift.append(Key(t, Vec(0, 0)))
    tilt.append(Key(t, 0.0))
    head = ctx.bone("head")
    return _clip(ctx, "look_around", {("shift", head): shift, ("angle", head): tilt})


def sneak(ctx: MotionContext) -> Clip:
    """Tiptoe: a walk made slow, small and low. The body crouches a little and the steps and arm
    swings are short. Across the frame (the placement moves) the feet stay planted like
    walk_cycle; standing still it marches softly in place. Front view: no toes to point, so
    'low and small' carries it."""
    quiet = MotionContext(
        view=ctx.view,
        fps=ctx.fps,
        start=ctx.start,
        last_frame=ctx.last_frame,
        duration=ctx.duration,
        params={**ctx.params, "energy": ctx.energy * 0.3},
        root_px=ctx.root_px,
        scale=ctx.scale,
        seed=ctx.seed,
        travel=ctx.travel,
    )
    walk = walk_cycle(quiet)
    crouch, ramp = ctx.lerp(5, 10), ctx.frames(0.25)
    root = ("shift", ctx.bone("torso"))
    last = walk.end
    channels = {c: list(keys) for c, keys in walk.channels.items()}
    channels[root] = [
        Key(
            k.frame,
            Vec(
                k.value.x,
                k.value.y
                - crouch * min(1.0, (k.frame - walk.start) / ramp, (last - k.frame) / ramp),
            ),
            k.interp,
        )
        for k in channels[root]
    ]
    return Clip("sneak", walk.start, walk.end, channels)


def clap(ctx: MotionContext) -> Clip:
    """Clap overhead, as in cheering: both arms rise and the forearms swing together and apart
    in quick beats, then lower. Front view: arms only move in the picture plane, so a chest-level
    clap is out of reach (an elbow bends one way); the clap happens above the head and the
    raise stops early on a big head, as wave does. `cycles` is the number of claps."""
    claps = _cycles(ctx, 4, 2 * ctx.frames(0.14), ctx.frames(0.8))
    up, down, half = ctx.frames(0.4 - 0.1 * ctx.energy), ctx.frames(0.45), ctx.frames(0.14)
    apart, together = ctx.lerp(8, 18), ctx.lerp(40, 65)
    raise_deg = min(_clear_raise(ctx, sd, ctx.lerp(130, 150), swing=together) for sd in SIGN)
    t0 = ctx.start
    t_up = t0 + up
    times = [t_up]
    for _ in range(claps):  # open, then together
        times += [times[-1] + half, times[-1] + 2 * half]
    t_end = times[-1] + half
    ch: dict[Channel, list[Key]] = {}
    for sd in SIGN:
        s = SIGN[sd]
        fore = [Key(t0, 0.0), Key(t_up, s * apart * 0.5)]
        for i, t in enumerate(times[1:]):
            fore.append(Key(t, s * (apart if i % 2 == 0 else together), C if i % 2 else E))
        fore += [Key(t_end, s * apart * 0.5), Key(t_end + down, 0.0)]
        ch[("angle", ctx.bone("forearm", sd))] = fore
        ch[("angle", ctx.bone("upper_arm", sd))] = [
            Key(t0, 0.0),
            Key(t_up, s * raise_deg),
            Key(t_end, s * raise_deg),
            Key(t_end + down, 0.0),
        ]
        # Open palms meet; a fist would read as punching, not clapping.
        ch.update(ctx.hand(sd, [(t0, "rest"), (t_up, "open"), (t_end + down // 2, "rest")]))
    return _clip(ctx, "clap", ch)


def laugh(ctx: MotionContext) -> Clip:
    """Laugh: the body bounces in quick beats, the head follows a frame behind and leans back,
    the arms jiggle, and the eyes squint (half-closed) for the length of the laugh. The mouth is
    the character's expression, not part of the motion: pair it with set_expression happy or
    excited (or lip-sync a laughing line). Front view: all bounce and tilt in the picture plane."""
    beat = ctx.frames(0.22 - 0.07 * ctx.energy)
    n = _cycles(ctx, 4, 2 * beat, 0)
    bounce, jiggle, lean = ctx.lerp(2, 6), ctx.lerp(2, 6), ctx.lerp(3, 8)
    side = ctx.params.get("side", "left")
    t0, t_end = ctx.start, ctx.start + 2 * n * beat
    body, head, tilt = [Key(t0, Vec(0, 0))], [Key(t0, Vec(0, 0))], [Key(t0, 0.0)]
    arms: dict[str, list[Key]] = {sd: [Key(t0, 0.0)] for sd in SIGN if ctx.has("upper_arm", sd)}
    for i in range(1, 2 * n + 1):
        t = t0 + i * beat
        edge = 0.5 if i in (1, 2 * n - 1) else 1.0  # the first and last bounce are smaller
        up = i % 2 == 1
        body.append(Key(t, Vec(0, -bounce * edge if up else 0)))  # dips: no gap at the hips
        head.append(Key(t + 1 if i < 2 * n else t, Vec(0, -bounce * 0.6 * edge if up else 0)))
        tilt.append(Key(t, SIGN[side] * lean * edge * (1 if up else 0.4) if i < 2 * n else 0.0))
        for sd, keys in arms.items():
            keys.append(Key(t, -SIGN[sd] * jiggle * edge if up else 0.0))  # inward: no pocket
    eyes = [Key(t0, "open", Interp.CONSTANT), Key(t0 + 2, "half", Interp.CONSTANT)]
    eyes += [Key(t_end - 2, "half", Interp.CONSTANT), Key(t_end, "open", Interp.CONSTANT)]
    ch: dict[Channel, list[Key]] = {
        ("shift", ctx.bone("torso")): body,
        ("shift", ctx.bone("head")): head,
        ("angle", ctx.bone("head")): tilt,
        ("eyes", ""): eyes,
    }
    for sd, keys in arms.items():
        ch[("angle", ctx.bone("upper_arm", sd))] = keys
    return _clip(ctx, "laugh", ch)


def think(ctx: MotionContext) -> Clip:
    """Think: one hand comes up beside the head with the elbow out, the head tilts the other
    way, hold (the pose relaxes slightly instead of freezing), then lower. Front view: the hand
    reaches the side of the head, not the chin, which is in front of the arm's plane; a real
    chin-rub needs the arm in front of the body."""
    side = ctx.params.get("side", "right")
    s = SIGN[side]
    ant, into, out = ctx.frames(0.1), ctx.frames(0.45), ctx.frames(0.5)
    pairs = _envelope(ctx.start, ant, into, _hold(ctx, into, out, ant, 1.6), out)
    ch: dict[Channel, list[Key]] = {
        ("angle", ctx.bone("upper_arm", side)): _angles(pairs, s * ctx.lerp(70, 80)),
        ("angle", ctx.bone("forearm", side)): _angles(pairs, s * ctx.lerp(130, 140)),
        ("angle", ctx.bone("head")): _angles(pairs, s * ctx.lerp(5, 11)),
    }
    t_in, t_out = pairs[2][0], pairs[-1][0] - out // 2  # a fist at the head while it is held
    ch.update(ctx.hand(side, [(ctx.start, "rest"), (t_in, "fist"), (t_out, "rest")]))
    return _clip(ctx, "think", ch)


MOTIONS: dict[str, Callable[[MotionContext], Clip]] = {
    "idle_breathe": idle_breathe,
    "blink": blink,
    "wave": wave,
    "nod": nod,
    "head_tilt": head_tilt,
    "walk_cycle": walk_cycle,
    "walk_step": walk_step,
    "jump": jump,
    "point": point,
    "talk_gesture": talk_gesture,
    "shrug": shrug,
    "bow": bow,
    "look_around": look_around,
    "sneak": sneak,
    "clap": clap,
    "laugh": laugh,
    "think": think,
}
