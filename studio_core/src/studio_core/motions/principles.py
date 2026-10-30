"""Animation principles as small deterministic functions on per-frame value lists.

Real motion data already carries some of this; a children's puppet wants it a little exaggerated,
and the older hand-keyed motions never had it. Each function takes a list of values (one per
frame), returns a new list of the same length, and does nothing at amount 0.

- `anticipate`: wind up opposite to a move before it starts
- `overshoot_settle`: go past where a move arrives and settle back (a damped spring)
- `lead` / `drag`: the head and eyes lead a move, the arms and ears trail it
- `contact_dips`: the body sinks when a foot lands or the character lands from a jump
- `breathing`: a slow rise and fall under everything

`apply_principles(clip, fps, amount)` runs them over any Clip (opt-in with `principles` in an
action's params), so the old motions can get the same treatment as the mocap ones.
"""

from __future__ import annotations

import math

from studio_core.motions.timeline import Channel, Clip, Key, sample
from studio_core.sif import Interp, Vec


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def velocity(values: list[float]) -> list[float]:
    n = len(values)
    return [
        (values[min(i + 1, n - 1)] - values[max(i - 1, 0)]) / (min(i + 1, n - 1) - max(i - 1, 0))
        if n > 1
        else 0.0
        for i in range(n)
    ]


def anticipate(
    values: list[float], depth: float, frames: int = 4, threshold: float = 1.0
) -> list[float]:
    """Dip against the direction of the first real move (speed above `threshold` per frame) in
    the `frames` before it, by `depth` times the size of the move's first few frames. The dip
    is a smooth bump that ends where the move starts, so the move itself is unchanged."""
    if depth <= 0 or len(values) < 3:
        return list(values)
    v = velocity(values)
    start = next((i for i, x in enumerate(v) if abs(x) > threshold), None)
    if start is None or start < 1:
        return list(values)
    push = sum(v[start : start + 3]) * depth
    out = list(values)
    for k in range(1, frames + 1):
        i = start - k
        if i < 0:
            break
        w = math.sin(math.pi * (1 - (k - 1) / frames) / 2) ** 2 if frames > 1 else 1.0
        out[i] -= push * w * (frames - k + 1) / frames * 0.5
    return out


def overshoot_settle(
    values: list[float],
    gain: float,
    freq_frames: float = 6.0,
    damping: float = 0.28,
    threshold: float = 1.0,
    settle: int = 14,
) -> list[float]:
    """After a fast move comes to rest, carry on a little and come back: a damped cosine whose
    size is `gain` times a quarter of the move's last four frames, for up to `settle` frames."""
    if gain <= 0 or len(values) < 4:
        return list(values)
    v = velocity(values)
    out = list(values)
    i = 1
    while i < len(values) - 1:
        if abs(v[i - 1]) > threshold and abs(v[i]) <= abs(v[i - 1]) * 0.5 and abs(v[i]) < threshold:
            amp = gain * 0.25 * (values[i] - values[max(i - 4, 0)])  # a quarter of the last stretch
            for k in range(1, settle + 1):
                if i + k >= len(out):
                    break
                out[i + k] += amp * math.exp(-damping * k) * math.sin(2 * math.pi * k / freq_frames)
            i += settle
        i += 1
    return out


def lead(values: list[float], frames: int) -> list[float]:
    """Earlier by `frames` (the head or eyes move first); the last value is held."""
    n = len(values)
    return [values[min(i + frames, n - 1)] for i in range(n)]


def drag(values: list[float], frames: int, mix: float = 1.0) -> list[float]:
    """Later by `frames` (arms, ears and tails follow); `mix` blends with the original."""
    n = len(values)
    return [values[i] * (1 - mix) + values[max(i - frames, 0)] * mix for i in range(n)]


def contact_dips(n: int, impacts: list[int], depth: float, frames: int = 5) -> list[float]:
    """The body sinks by `depth` at each impact frame and recovers over `frames` (a quick drop
    in one frame, a smooth rise back): add to the body's vertical shift."""
    out = [0.0] * n
    for at in impacts:
        for k in range(frames + 1):
            if 0 <= at + k < n:
                out[at + k] -= depth * (1 - smoothstep(k / frames))
    return out


def breathing(
    n: int, fps: int, amp: float, period_s: float = 3.4, phase: float = 0.0
) -> list[float]:
    """A slow rise and fall (px) that never stops; half a period is the breath in."""
    return [
        amp * (0.5 - 0.5 * math.cos(2 * math.pi * (i / fps / period_s + phase))) for i in range(n)
    ]


def landing_frames(values: list[float], threshold: float = 2.0) -> list[int]:
    """Frames where a falling value (a jump coming down) hits its floor: the speed was downward
    and fast, and is now small."""
    v = velocity(values)
    return [i for i in range(1, len(values)) if v[i - 1] < -threshold and v[i] > -threshold * 0.25]


# --------------------------------------------------------------------------- over a whole clip


def _dense(clip: Clip, channel: Channel) -> tuple[list[float], list[Key]] | None:
    keys = clip.channels[channel]
    if not isinstance(keys[0].value, (int, float)):
        return None
    frames = range(clip.start, clip.end + 1)
    return [float(sample(keys, f)) for f in frames], keys  # type: ignore[arg-type]


def apply_principles(clip: Clip, fps: int, amount: float = 0.5, head: str | None = None) -> Clip:
    """Return `clip` with the principles layered on. Angle channels get anticipation and an
    overshoot where they arrive; the `head` angle channel leads the other angles; a vertical
    shift on any bone gets a dip when it lands. Sizes scale with `amount` (0 = unchanged)."""
    if amount <= 0 or clip.additive:
        return clip
    out: dict[Channel, list[Key]] = {}
    for channel, keys in clip.channels.items():
        kind, bone = channel
        dense = _dense(clip, channel) if kind == "angle" else None
        if dense is not None:
            vals, _ = dense
            vals = anticipate(vals, 0.5 * amount)
            vals = overshoot_settle(vals, 0.55 * amount)
            if bone == head:
                vals = lead(vals, round(2 * amount))
            out[channel] = [Key(clip.start + i, v, Interp.LINEAR) for i, v in enumerate(vals)]
        elif kind == "shift" and isinstance(keys[0].value, Vec):
            ys = [sample(keys, f) for f in range(clip.start, clip.end + 1)]
            vy = [y.y for y in ys]  # type: ignore[union-attr]
            dips = contact_dips(len(vy), landing_frames(vy), 14 * amount)
            out[channel] = [
                Key(clip.start + i, Vec(y.x, y.y + d), Interp.LINEAR)  # type: ignore[union-attr]
                for i, (y, d) in enumerate(zip(ys, dips, strict=True))
            ]
        else:
            out[channel] = keys
    return Clip(
        clip.motion,
        clip.start,
        clip.end,
        out,
        clip.additive,
        dict(clip.limits),
        dict(clip.max_speed_dps),
    )
