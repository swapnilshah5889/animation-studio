"""Mocap → engine-neutral clips for a 2D puppet (the part that is plain math, no rig, no engine).

`build_clip` turns CMU joint positions into a `RealClip`: per-bone angle offsets (degrees, CCW
positive on screen, from the rest pose) for the torso, head and arms; for each leg the ankle's
position relative to the hip (so the puppet's own bone lengths can reach it by IK and keep the
foot where the actor's foot was); the body's rise and fall; and, for gaits, the hip travel per
cycle (so the puppet's steps follow the ground it covers and the planted foot does not slide).
Lengths are in units of the actor's standing hip height `U`; a puppet multiplies by its own leg
length. Nothing here names a Synfig field (D-030).

Pipeline: project the 3D joints onto a vertical plane (yaw 0 = seen from the front, 90 = from
the side), low-pass and resample to the film's fps, read the segment directions, make the
relative angles, and for gaits cut one loop from the walk (two heel strikes of the same foot that
match best) and close it.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from studio_core.mocap.acclaim import Mocap

SIDES = ("left", "right")
PREFIX = {"left": "l", "right": "r"}
ARM_KEEP = 0.3  # share of the arms' mean forward offset a gait keeps (they hang near the body)
REACH = 0.985  # a planted leg is never quite straight: the body is lowered to keep this


@dataclass
class RealClip:
    name: str
    source: str  # the CMU trial it came from, e.g. "35_01"
    fps: int
    frames: int
    loop: bool
    yaw_deg: float
    tracks: dict[str, list[float]]  # "torso", "head", "upper_arm:left", ... → degrees
    hip_drop: list[float]  # body height change per frame, in U (≤ 0 is lower than standing)
    feet: dict[str, dict[str, list[float]]]  # side → {"dx": [...], "dy": [...]} in U, vs standing
    knee: dict[str, float]  # side → +1/-1: which way the knee turns (sign of thigh cross shin)
    stride_cycle: float | None = None  # hip travel per loop in U (gaits); None = in place
    side: str | None = None  # the side doing the gesture (a wave), so it can be mirrored
    contacts: dict[str, list[bool]] = field(default_factory=dict)  # side → foot on ground
    stats: dict[str, float] = field(default_factory=dict)

    def mirrored(self) -> RealClip:
        """The same motion as a mirror image: left and right swap and every angle and sideways
        offset flips sign (a right-hand wave becomes a left-hand wave)."""
        swap = {"left": "right", "right": "left"}
        tracks = {}
        for name, values in self.tracks.items():
            role, _, side = name.partition(":")
            tracks[f"{role}:{swap[side]}" if side else role] = [-v for v in values]
        return RealClip(
            self.name,
            self.source,
            self.fps,
            self.frames,
            self.loop,
            self.yaw_deg,
            tracks,
            list(self.hip_drop),
            {
                swap[s]: {"dx": [-v for v in f["dx"]], "dy": list(f["dy"])}
                for s, f in self.feet.items()
            },
            {swap[s]: -k for s, k in self.knee.items()},
            self.stride_cycle,
            swap[self.side] if self.side else None,
            {swap[s]: list(c) for s, c in self.contacts.items()},
            dict(self.stats),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> RealClip:
        return cls(**d)


# --------------------------------------------------------------------------- signal helpers


def gaussian_smooth(a: np.ndarray, sigma: float, wrap: bool = False) -> np.ndarray:
    """Low-pass along axis 0 (a Gaussian of `sigma` samples); `wrap` treats it as periodic."""
    if sigma <= 0:
        return a
    r = max(1, math.ceil(sigma * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    mode = "wrap" if wrap else "edge"
    pad = np.pad(a, [(r, r)] + [(0, 0)] * (a.ndim - 1), mode=mode)
    out = np.empty_like(a, dtype=float)
    flat = pad.reshape(len(pad), -1)
    res = np.stack([np.convolve(flat[:, j], k, mode="valid") for j in range(flat.shape[1])], 1)
    out[:] = res.reshape(a.shape)
    return out


def resample(a: np.ndarray, src_fps: float, dst_fps: float, n: int, t0: float = 0.0) -> np.ndarray:
    """Linear resample: `n` samples at dst_fps starting `t0` seconds into the signal."""
    t = (t0 + np.arange(n) / dst_fps) * src_fps
    t = np.clip(t, 0, len(a) - 1)
    i = np.minimum(t.astype(int), len(a) - 2)
    w = (t - i).reshape(-1, *([1] * (a.ndim - 1)))
    return a[i] * (1 - w) + a[i + 1] * w


def close_loop(a: np.ndarray) -> np.ndarray:
    """Remove the drift between the first and last sample (a linear ramp): a seamless loop."""
    n = len(a)
    ramp = np.linspace(0, 1, n).reshape(-1, *([1] * (a.ndim - 1)))
    return a - ramp * (a[-1] - a[0])


# --------------------------------------------------------------------------- projection


def lateral_forward(m: Mocap) -> tuple[np.ndarray, np.ndarray]:
    """The actor's left and forward directions on the ground (unit vectors; y is up)."""
    left = (m.joints["lfemur"] - m.joints["rfemur"]).mean(0)
    left[1] = 0.0
    left /= np.linalg.norm(left)
    fwd = np.cross(left, np.array([0.0, 1.0, 0.0]))
    return left, fwd


def project(m: Mocap, yaw_deg: float) -> dict[str, np.ndarray]:
    """Every joint as (frames, 2): screen x then up. yaw 0 looks at the actor's front (their left
    is screen right); yaw 90 looks from the side with the actor walking toward screen right."""
    left, fwd = lateral_forward(m)
    yaw = math.radians(yaw_deg)
    axis = math.cos(yaw) * left + math.sin(yaw) * fwd
    return {name: np.stack([p @ axis, p[:, 1]], 1) for name, p in m.joints.items()}


def best_yaw(m: Mocap, joints: list[tuple[str, str]], step: float = 5.0) -> float:
    """The yaw (0..90) at which the listed joints (point, relative-to) move most on screen: a way
    to pick the view that shows a gesture instead of foreshortening it."""
    best, best_v = 0.0, -1.0
    for yaw in np.arange(0.0, 90.0 + step, step):
        p = project(m, float(yaw))
        v = sum(float(np.var(p[a] - p[b], axis=0).sum()) for a, b in joints)
        if v > best_v + 1e-9:
            best, best_v = float(yaw), v
    return best


def direction(v: np.ndarray) -> np.ndarray:
    """Angle in degrees of vectors (frames, 2), unwrapped over time."""
    ang = np.unwrap(np.arctan2(v[:, 1], v[:, 0]))
    return np.degrees(ang)


def _near(a: np.ndarray, ref: float) -> np.ndarray:
    """Shift a whole track by a multiple of 360° so its first sample is within 180° of `ref`."""
    k = round((ref - a[0]) / 360.0)
    return a + 360.0 * k


# --------------------------------------------------------------------------- the build


def segment_angles(p: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Absolute segment directions (degrees, 2D) per frame."""
    out = {
        "torso": direction(p["lowerneck"] - p["root"]),
        "head": direction(p["head_end"] - p["lowerneck"]),
    }
    for side, c in PREFIX.items():
        out[f"upper_arm:{side}"] = direction(p[f"{c}humerus_end"] - p[f"{c}humerus"])
        out[f"forearm:{side}"] = direction(p[f"{c}radius_end"] - p[f"{c}radius"])
        out[f"thigh:{side}"] = direction(p[f"{c}femur_end"] - p[f"{c}femur"])
        out[f"shin:{side}"] = direction(p[f"{c}tibia_end"] - p[f"{c}tibia"])
    return out


PARENT = {
    "head": "torso",
    "upper_arm:left": "torso",
    "upper_arm:right": "torso",
    "forearm:left": "upper_arm:left",
    "forearm:right": "upper_arm:right",
}
REST_DIR = {"torso": 90.0, "head": 90.0, "upper_arm": -90.0, "forearm": -90.0}


def relative_angles(absolute: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Offsets from a puppet standing straight with arms down: each bone's world direction minus
    its rest direction, minus its parent's offset (so they compose the way bone angles do)."""
    world: dict[str, np.ndarray] = {}
    for name in (
        "torso",
        "head",
        "upper_arm:left",
        "upper_arm:right",
        "forearm:left",
        "forearm:right",
    ):
        rest = REST_DIR[name.split(":")[0]]
        world[name] = _near(absolute[name], rest) - rest
    out = {"torso": world["torso"]}
    for name in world:
        if name != "torso":
            out[name] = world[name] - world[PARENT[name]]
    return out


def find_loop(ankle_x: np.ndarray, fps: float, lo: float = 0.4, hi: float = 1.8) -> tuple[int, int]:
    """Indices (i0, i1) of one gait cycle: two successive maxima of the ankle's lead (the same
    foot reaching forward again), between `lo` and `hi` seconds apart, whose pose match best."""
    s = gaussian_smooth(ankle_x, fps * 0.04)
    peaks = [
        i for i in range(2, len(s) - 2) if s[i] >= s[i - 1] and s[i] > s[i + 1] and s[i] > s[i - 2]
    ]
    best: tuple[float, int, int] | None = None
    for a, i in enumerate(peaks):
        for j in peaks[a + 1 :]:
            if not lo * fps <= j - i <= hi * fps:
                continue
            err = abs(s[i] - s[j])
            if best is None or err < best[0]:
                best = (err, i, j)
    if best is None:
        raise ValueError("no gait cycle found in this clip")
    return best[1], best[2]


def contacts_from(
    ankle_x: np.ndarray, ankle_h: np.ndarray, hip_speed: float, fps: float, height_tol: float
) -> np.ndarray:
    """Foot on the ground: low enough, and (for a walk) its ground speed small beside the hip's."""
    v = np.gradient(ankle_x) * fps  # the foot's speed over the ground
    low = ankle_h < height_tol
    still = np.abs(v) < 0.3 * abs(hip_speed) if abs(hip_speed) > 1e-6 else low
    return low & still


def build_gait(
    m: Mocap,
    name: str,
    source: str,
    fps: int,
    yaw_deg: float = 90.0,
    smooth_s: float = 0.03,
    arm_gain: float = 1.8,
) -> RealClip:
    """One seamless loop of a walk or run (travel along screen x). `arm_gain` enlarges the arms'
    swing about their mean (cartoon exaggeration; 1 = as captured)."""
    p = project(m, yaw_deg)
    src = m.fps
    p = {k: gaussian_smooth(v, src * smooth_s) for k, v in p.items()}
    hip_mid = (p["lfemur"] + p["rfemur"]) / 2
    ground = min(p["ltibia_end"][:, 1].min(), p["rtibia_end"][:, 1].min())
    hip_h = hip_mid[:, 1] - ground
    big_u = float(np.percentile(hip_h, 98))
    i0, i1 = find_loop(p["ltibia_end"][:, 0] - hip_mid[:, 0], src)
    n = round((i1 - i0) / src * fps)
    seg = slice(i0, i1 + 1)
    cyc = (i1 - i0) / src
    hip_speed = float((hip_mid[i1, 0] - hip_mid[i0, 0]) / cyc)  # actor units / s along x

    def take(a: np.ndarray) -> np.ndarray:
        # resample [i0, i1) as a loop: n samples, then remove the seam drift
        part = a[seg]
        out = resample(part, src, fps, n + 1)[:n] if len(part) > 1 else part
        return out

    ref_x = hip_mid[i0, 0] + hip_speed * (np.arange(len(hip_mid)) - i0) / src
    absolute = segment_angles(p)
    tracks_abs = {k: take(v) for k, v in absolute.items()}
    tracks_abs = {k: close_loop_periodic(v) for k, v in tracks_abs.items()}
    rel = relative_angles(tracks_abs)
    feet: dict[str, dict[str, list[float]]] = {}
    knee: dict[str, float] = {}
    contacts: dict[str, list[bool]] = {}
    step = (hip_mid[i1, 0] - hip_mid[i0, 0]) / n  # the uniform hip's travel per frame
    hh = take(hip_h)
    rel_x, height, flags = {}, {}, {}
    for side, c in PREFIX.items():
        ankle = p[f"{c}tibia_end"]
        rel_x[side] = take(ankle[:, 0] - ref_x)
        height[side] = take(ankle[:, 1] - ground)
        ct = contacts_from(ankle[:, 0], ankle[:, 1] - ground, hip_speed, src, 0.18 * big_u)
        flags[side] = take(ct.astype(float)) > 0.5
    mean_x = float(np.mean([rel_x["left"].mean(), rel_x["right"].mean()]))
    dx, ah = {}, {}
    for side in PREFIX:
        dx[side] = (lock_stance(rel_x[side], flags[side], step) - mean_x) / big_u
        ah[side] = lock_stance(height[side], flags[side], 0.0, mode="floor") / big_u
        # the lock leaves corners where it takes hold; ease them (the planted middle stays put)
        dx[side] = gaussian_smooth(dx[side], 0.8, wrap=True)
        ah[side] = gaussian_smooth(ah[side], 0.8, wrap=True)
    # the body can only be as high as the planted leg reaches (a straight leg is 1 U): lower it
    # where the mocap hip was higher than the locked feet allow, so the IK can always reach
    reach = REACH
    cap = np.min([ah[s_] + np.sqrt(np.maximum(reach**2 - dx[s_] ** 2, 0.0)) for s_ in PREFIX], 0)
    hip = np.minimum(hh / big_u, cap)
    hip = gaussian_smooth(hip, 1.2, wrap=True)
    hip = np.minimum(hip, cap)
    feet: dict[str, dict[str, list[float]]] = {}
    knee: dict[str, float] = {}
    for side, c in PREFIX.items():
        th = p[f"{c}femur_end"] - p[f"{c}femur"]
        sh = p[f"{c}tibia_end"] - p[f"{c}tibia"]
        cross = th[:, 0] * sh[:, 1] - th[:, 1] * sh[:, 0]
        knee[side] = 1.0 if np.median(cross) >= 0 else -1.0
    # start the loop at a passing pose (left foot planted, the right passing it): the feet are
    # together, so a walk fades in from standing, and ends on a passing pose, without a lunge
    diff = dx["left"] - dx["right"]
    cand = [k for k in range(n) if diff[k - 1] > 0 >= diff[k] and flags["left"][k]]
    shift = cand[0] if cand else 0
    roll = lambda a: np.roll(a, -shift)  # noqa: E731
    for side in PREFIX:
        feet[side] = {"dx": _loop(roll(dx[side])), "dy": _loop(roll(ah[side] - hip + 1.0))}
    contacts = {s_: [bool(x) for x in roll(flags[s_])] for s_ in PREFIX}
    hip_drop = roll(hip) - 1.0
    stats = {
        "U": big_u,
        "cycle_s": cyc,
        "speed_U_per_s": hip_speed / big_u,
        "loop_seam_deg": float(max(abs(tracks_abs[k][-1] - tracks_abs[k][0]) for k in tracks_abs)),
    }
    return RealClip(
        name,
        source,
        fps,
        n,
        True,
        yaw_deg,
        {k: _loop(roll(v)) for k, v in rel.items()},
        _loop(hip_drop),
        feet,
        knee,
        stride_cycle=hip_speed * cyc / big_u,
        contacts=contacts,
        stats=stats,
    )


def lock_stance(
    series: np.ndarray, flags: np.ndarray, step: float, blend: int = 2, mode: str = "mean"
) -> np.ndarray:
    """Foot lock for a looped series: while the foot is down, hold it still on the ground.

    `series` is the foot's position relative to a hip that advances `step` per frame, so a planted
    foot has slope -step; inside each run of `flags` the world position (series + step*k) is
    replaced by its mean ("mean"), or by its lowest value ("floor", for heights; step 0), with a
    short smooth blend of `blend` frames at both ends. Runs that wrap around the loop work."""
    n = len(series)
    if not flags.any() or flags.all():
        return series
    r = int(np.argmin(flags))
    k = r + np.arange(n)
    idx = k % n
    world = series[idx] + step * k
    f = flags[idx]
    out = world.copy()
    a = 0
    while a < n:
        if not f[a]:
            a += 1
            continue
        b = a
        while b + 1 < n and f[b + 1]:
            b += 1
        target = world[a : b + 1].min() if mode == "floor" else world[a : b + 1].mean()
        for j in range(a, b + 1):
            w = smoothstep01((j - a + 1) / (blend + 1)) * smoothstep01((b - j + 1) / (blend + 1))
            out[j] = world[j] * (1 - w) + target * w
        a = b + 1
    result = np.empty(n)
    result[idx] = out - step * k
    return result


def smoothstep01(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def close_loop_periodic(a: np.ndarray) -> np.ndarray:
    """A cycle sampled [i0, i1): spread the end-to-start jump over the whole loop."""
    n = len(a)
    ramp = np.arange(n) / n
    return a - ramp * (a[-1] - a[0] + (a[-1] - a[-2] if n > 1 else 0))


def _loop(a: np.ndarray) -> list[float]:
    return [round(float(x), 4) for x in a]


def build_oneshot(
    m: Mocap,
    name: str,
    source: str,
    fps: int,
    yaw_deg: float,
    window: tuple[float, float] | None = None,
    smooth_s: float = 0.04,
    arms: tuple[str, ...] = SIDES,
    gesture_side: str | None = None,
    legs: bool = True,
) -> RealClip:
    """A single action (wave, shrug, jump...) that starts and ends standing: everything is relative
    to the first frame's pose. `window` (seconds) cuts the part of the trial that is the action."""
    p = project(m, yaw_deg)
    src = m.fps
    p = {k: gaussian_smooth(v, src * smooth_s) for k, v in p.items()}
    t0, t1 = window if window else (0.0, (m.frames - 1) / src)
    a, b = int(t0 * src), min(int(t1 * src), m.frames - 1)
    p = {k: v[a : b + 1] for k, v in p.items()}
    n = max(2, round((b - a) / src * fps) + 1)
    p = {k: resample(v, src, fps, n) for k, v in p.items()}
    hip_mid = (p["lfemur"] + p["rfemur"]) / 2
    ground = min(p["ltibia_end"][:, 1].min(), p["rtibia_end"][:, 1].min())
    big_u = float(hip_mid[0, 1] - ground)
    rel = relative_angles(segment_angles(p))
    tracks = {k: _loop(v - v[0]) for k, v in rel.items()}
    for side in SIDES:
        if side not in arms:  # keep the unused arm calm: no motion rather than mocap noise
            for bone in ("upper_arm", "forearm"):
                tracks[f"{bone}:{side}"] = [0.0] * n
    feet, knee, contacts = {}, {}, {}
    for side, c in PREFIX.items():
        ankle = p[f"{c}tibia_end"]
        rx = ankle[:, 0] - hip_mid[:, 0]
        h = ankle[:, 1] - ground
        feet[side] = {
            "dx": _loop((rx - rx[0]) / big_u),
            "dy": _loop(
                (h - hip_mid[:, 1] + ground + big_u - (h[0] - hip_mid[0, 1] + ground + big_u))
                / big_u
            ),
        }
        th = p[f"{c}femur_end"] - p[f"{c}femur"]
        sh = p[f"{c}tibia_end"] - p[f"{c}tibia"]
        cross = th[:, 0] * sh[:, 1] - th[:, 1] * sh[:, 0]
        knee[side] = 1.0 if np.median(cross) >= 0 else -1.0
        contacts[side] = [bool(x) for x in h < 0.12 * big_u]
    hip_drop = (hip_mid[:, 1] - hip_mid[0, 1]) / big_u
    if not legs:  # an upper-body gesture: the legs stand (bent legs open seams in a rigid cut)
        zero = [0.0] * n
        feet = {s_: {"dx": list(zero), "dy": list(zero)} for s_ in feet}
        hip_drop = np.zeros(n)
    stats = {"U": big_u, "seconds": (n - 1) / fps}
    return RealClip(
        name,
        source,
        fps,
        n,
        False,
        yaw_deg,
        tracks,
        _loop(hip_drop),
        feet,
        knee,
        side=gesture_side,
        contacts=contacts,
        stats=stats,
    )
