"""Smooth motion as deterministic code (D-093): no pops, eased changes, blended faces.

Three problems made the first films look jerky, and each has a small pure function here:

1. **Pops.** Where one action ends and the next begins (walk -> wave), the clips' keys jump.
   `blend_pops` finds the frames where a bone's angle jumps by more than `pop_deg` in one frame
   and smooths *only around them* (a zero-phase Gaussian, weighted by distance), so ordinary fast
   motion keeps its shape. `limit_step` then enforces a per-bone speed cap (degrees per frame),
   the contract `Clip.max_speed_dps` declares, the way `Clip.limits` declares an angle range.
2. **Switches.** A blink, a mouth letter or a new expression changed in one frame. `eye_series`,
   `mouth_series` and `expression_series` turn those switch tracks into continuous numbers
   (`face` dicts that `engines/face_flat.draw_face` draws), so every in-between frame is a real
   drawing: lids close fast and open slower, the mouth leads the sound by a frame and eases
   between shapes, an expression crosses over several frames.
3. **Hard cuts.** `crossfade_alpha` gives the opacity of the incoming shot over a short overlap
   (a smootherstep), for a cut between shots that are not a matching cut.

Everything is a pure function of its inputs and the frame rate: the same shot, the same tracks.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Any

DEFAULT_POP_DEG = (
    9.0  # a one-frame jump bigger than this is a pop (a real run's fastest swing is ~6)
)
DEFAULT_SIGMA = 2.2  # frames: width of the smoothing around a pop
DEFAULT_MAX_DPS = 900.0  # deg/s: nothing in a children's film turns faster

# Rhubarb mouth letters as shape numbers (open, width, round, teeth, tongue), see face_flat
VISEME_PARAMS: dict[str, dict[str, float]] = {
    "A": {"open": 0.0, "width": 1.0, "round": 0.0, "teeth": 0.0, "tongue": 0.0},
    "B": {"open": 0.22, "width": 1.18, "round": 0.0, "teeth": 1.0, "tongue": 0.0},
    "C": {"open": 0.52, "width": 1.05, "round": 0.15, "teeth": 0.4, "tongue": 0.2},
    "D": {"open": 0.95, "width": 1.0, "round": 0.1, "teeth": 0.5, "tongue": 0.45},
    "E": {"open": 0.50, "width": 0.78, "round": 0.65, "teeth": 0.0, "tongue": 0.3},
    "F": {"open": 0.28, "width": 0.55, "round": 1.0, "teeth": 0.0, "tongue": 0.0},
    "G": {"open": 0.20, "width": 1.0, "round": 0.0, "teeth": 1.0, "tongue": 0.0},
    "H": {"open": 0.55, "width": 1.0, "round": 0.0, "teeth": 0.3, "tongue": 0.9},
    "X": {"open": 0.0, "width": 1.0, "round": 0.0, "teeth": 0.0, "tongue": 0.0},
}
# expression: (smile, brow_raise, brow_tilt)
EXPRESSIONS: dict[str, tuple[float, float, float]] = {
    "neutral": (0.20, 0.0, 0.0),
    "happy": (0.60, 0.15, 0.0),
    "excited": (0.85, 0.45, 0.0),
    "surprised": (0.10, 0.90, 0.25),
    "sad": (-0.50, 0.10, 0.65),
    "worried": (-0.20, 0.25, 0.70),
    "grumpy": (-0.30, -0.30, -0.55),
}
EYE_VALUE = {"open": 1.0, "half": 0.5, "closed": 0.0}


def smootherstep(t: float) -> float:
    """0 -> 1 with zero speed AND zero acceleration at both ends (smoother than smoothstep)."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


# ----------------------------------------------------------------------------- series maths


def gaussian(values: Sequence[float], sigma: float) -> list[float]:
    """Zero-phase Gaussian smoothing; the ends are held (the first/last value repeats)."""
    if sigma <= 0 or len(values) < 2:
        return list(values)
    r = max(1, math.ceil(3 * sigma))
    k = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-r, r + 1)]
    total = sum(k)
    n = len(values)
    return [
        sum(k[j] * values[min(n - 1, max(0, i + j - r))] for j in range(2 * r + 1)) / total
        for i in range(n)
    ]


def pop_frames(values: Sequence[float], threshold: float) -> list[int]:
    """Frames i where the value jumps by more than `threshold` between i-1 and i."""
    return [i for i in range(1, len(values)) if abs(values[i] - values[i - 1]) > threshold]


def blend_pops(
    values: Sequence[float], threshold: float = DEFAULT_POP_DEG, sigma: float = DEFAULT_SIGMA
) -> list[float]:
    """Smooth around the pops only: out = (1-w) * original + w * smoothed, w = 1 at a pop and
    falling off as a Gaussian of the distance. No pop, no change (byte-identical)."""
    pops = pop_frames(values, threshold)
    if not pops:
        return list(values)
    soft = gaussian(values, sigma)
    out = []
    for i, v in enumerate(values):
        w = max(math.exp(-0.5 * ((i - (p - 0.5)) / (sigma * 1.4)) ** 2) for p in pops)
        out.append(v + (soft[i] - v) * w)
    return out


def limit_step(values: Sequence[float], max_step: float, passes: int = 80) -> list[float]:
    """Cap the frame-to-frame change at `max_step` by alternating forward and backward slew
    limits until none is exceeded (each pass only moves values toward their neighbours, so it
    converges); a peak is shaved, a fast ramp is stretched over more frames."""
    out = list(values)
    for _ in range(passes):
        worst = 0.0
        for i in range(1, len(out)):
            lo, hi = out[i - 1] - max_step, out[i - 1] + max_step
            new = min(hi, max(lo, out[i]))
            worst = max(worst, abs(new - out[i]))
            out[i] = new
        for i in range(len(out) - 2, -1, -1):
            lo, hi = out[i + 1] - max_step, out[i + 1] + max_step
            new = min(hi, max(lo, out[i]))
            worst = max(worst, abs(new - out[i]))
            out[i] = new
        if worst < 1e-9:
            break
    return out


def max_step_per_frame(max_dps: float, fps: int) -> float:
    return max_dps / fps


def smooth_offsets(
    offsets: list[dict[str, float]],
    fps: int,
    *,
    pop_deg: float = DEFAULT_POP_DEG,
    sigma: float = DEFAULT_SIGMA,
    max_dps: float | dict[str, float] = DEFAULT_MAX_DPS,
) -> list[dict[str, float]]:
    """`frame_offsets` output with pops blended away and every bone under its speed cap.
    `max_dps` is one number or {bone: deg/s} (`Clip.max_speed_dps` merged by `speed_caps`)."""
    if not offsets:
        return offsets
    bones = list(offsets[0])
    cols = {}
    for b in bones:
        series = [f[b] for f in offsets]
        cap = max_dps.get(b, DEFAULT_MAX_DPS) if isinstance(max_dps, dict) else max_dps
        series = blend_pops(series, pop_deg, sigma)
        cols[b] = limit_step(series, max_step_per_frame(cap, fps))
    return [{b: cols[b][i] for b in bones} for i in range(len(offsets))]


def speed_caps(clips: Sequence[Any]) -> dict[str, float]:
    """The tightest `Clip.max_speed_dps` any playing clip declares, per bone."""
    caps: dict[str, float] = {}
    for c in clips:
        for bone, dps in getattr(c, "max_speed_dps", {}).items():
            caps[bone] = min(dps, caps.get(bone, dps))
    return caps


# ----------------------------------------------------------------------------- tracks


def eased_track(keys: Sequence[tuple[float, float]], fps: int, n: int) -> list[float]:
    """Per-frame values through (time_s, value) keys, easing in and out of every change with a
    smootherstep (a head turn, a camera move): the value holds before the first and after the
    last key."""
    ks = sorted(keys)
    out = []
    for f in range(n):
        t = f / fps
        if not ks:
            out.append(0.0)
        elif t <= ks[0][0]:
            out.append(ks[0][1])
        elif t >= ks[-1][0]:
            out.append(ks[-1][1])
        else:
            for (t0, v0), (t1, v1) in itertools.pairwise(ks):
                if t0 <= t <= t1:
                    out.append(v0 + (v1 - v0) * smootherstep((t - t0) / (t1 - t0)))
                    break
    return out


def _one_pole(values: Sequence[float], down: float, up: float) -> list[float]:
    """Exponential smoothing with one rate when the value falls and another when it rises."""
    out, y = [], values[0] if values else 0.0
    for v in values:
        a = down if v < y else up
        y += (v - y) * a
        out.append(y)
    return out


def eye_series(
    states: Sequence[str], fps: int, close_ms: float = 70, open_ms: float = 120
) -> list[float]:
    """Eye openness (0 closed .. 1 open) from open/half/closed switch states: lids close quickly
    and open slower, each through two cascaded smoothing stages (no hard edge, no overshoot)."""
    target = [EYE_VALUE.get(s, 1.0) for s in states]
    a_close = 1 - math.exp(-1000 / fps / close_ms * 2)
    a_open = 1 - math.exp(-1000 / fps / open_ms * 2)
    return _one_pole(_one_pole(target, a_close, a_open), a_close, a_open)


def mouth_series(
    letters: Sequence[str], fps: int, lead_frames: int = 1, tau_ms: float = 55
) -> list[dict[str, float]]:
    """Mouth shape numbers per frame from Rhubarb letters: the mouth leads the sound by
    `lead_frames` (speech is seen before it is heard) and each number eases toward the next
    shape through two cascaded smoothing stages, so shapes blend instead of swapping."""
    n = len(letters)
    led = [letters[min(n - 1, i + lead_frames)] for i in range(n)]
    a = 1 - math.exp(-1000 / fps / tau_ms)
    cols = {}
    for key in ("open", "width", "round", "teeth", "tongue"):
        target = [VISEME_PARAMS.get(c, VISEME_PARAMS["X"])[key] for c in led]
        cols[key] = _one_pole(_one_pole(target, a, a), a, a)
    return [{k: cols[k][i] for k in cols} for i in range(n)]


def expression_series(
    keys: Sequence[dict[str, Any]], fps: int, n: int, ease_s: float = 0.35
) -> list[tuple[float, float, float]]:
    """(smile, brow_raise, brow_tilt) per frame from [{expr, start_s}]: each change crosses over
    `ease_s` with a smootherstep, so no expression pops."""
    ks = sorted(keys, key=lambda k: k["start_s"]) or [{"expr": "neutral", "start_s": 0.0}]

    def target(i: int) -> tuple[float, float, float]:
        return EXPRESSIONS.get(ks[i]["expr"], EXPRESSIONS["neutral"])

    out = []
    for f in range(n):
        t = f / fps
        k = max((i for i, key in enumerate(ks) if key["start_s"] <= t), default=0)
        cur = target(k)
        if k > 0 and t < ks[k]["start_s"] + ease_s:
            w = smootherstep((t - ks[k]["start_s"]) / ease_s)
            cur = tuple(a + (b - a) * w for a, b in zip(target(k - 1), cur, strict=True))  # type: ignore[assignment]
        out.append(cur)
    return out


def face_series(
    eyes: Sequence[str],
    mouth: Sequence[str],
    expressions: Sequence[dict[str, Any]],
    yaw_keys: Sequence[tuple[float, float]],
    fps: int,
) -> list[dict[str, Any]]:
    """The continuous face state per frame (see `engines/face_flat.FaceState`), plus the head
    turn (`yaw`, -1..1, eased)."""
    n = len(eyes)
    eo = eye_series(eyes, fps)
    ms = mouth_series(mouth, fps)
    ex = expression_series(expressions, fps, n)
    yaw = eased_track(yaw_keys, fps, n) if yaw_keys else [0.0] * n
    # the eyes follow the turn a few frames before the head arrives, as a person looks first
    lead = 3
    look = [yaw[min(n - 1, i + lead)] for i in range(n)]
    return [
        {
            "eye_open": round(eo[i], 4),
            "smile": round(ex[i][0], 4),
            "brow_raise": round(ex[i][1], 4),
            "brow_tilt": round(ex[i][2], 4),
            "mouth": {k: round(v, 4) for k, v in ms[i].items()},
            "look": [round(look[i], 4), 0.0],
            "yaw": round(yaw[i], 4),
        }
        for i in range(n)
    ]


def crossfade_alpha(frame: int, start: int, length: int) -> float:
    """Opacity of the incoming shot at `frame` for a cross-fade that starts at `start` and
    lasts `length` frames (0 before, 1 after, a smootherstep between)."""
    if length <= 0:
        return 1.0 if frame >= start else 0.0
    return smootherstep((frame - start) / length)


MAX_DISSOLVE_SCALE_RATIO = (
    1.25  # a dissolve may not blend two framings whose character scales differ more
)


def transition_for(zoom_a: float, zoom_b: float, character_in_both: bool) -> str:
    """ "crossfade" or "cut" for a shot change. Rule (D-096): never dissolve two scenes that both
    contain the character at different scales: the blend shows two figures, doubled backgrounds
    and a ghost (the review of the first clip, 3.0-3.2 s). Such a change is a hard cut, or better
    a real camera push-in (one continuous framing). A dissolve stays fine when the character is
    in only one scene, or the scales are close."""
    if not character_in_both:
        return "crossfade"
    ratio = max(zoom_a, zoom_b) / max(1e-6, min(zoom_a, zoom_b))
    return "cut" if ratio > MAX_DISSOLVE_SCALE_RATIO else "crossfade"
