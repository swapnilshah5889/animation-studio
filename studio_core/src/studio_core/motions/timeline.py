"""Motion clips and how they combine (D-028: per-bone overrides + additive idle layers).

A motion produces a **clip**: keys on **channels** over a frame window.

- `("angle", bone)`: degrees of offset from the rest pose, relative to the parent bone
- `("shift", bone)`: a Vec in art pixels (y up) moving the bone's joint, e.g. a nod lowers the
  head; on the root bone it moves the whole character (a jump)
- `("eyes", "")`: eye states for the face switch (blinks)

`compose` merges clips per channel: a later override clip owns a channel for its window (earlier
keys inside the window are dropped); additive clips (idle breathing) are summed on top at every
key time. `sample` evaluates a key list the way Synfig will interpolate it closely enough for
those sums: `halt` as a smoothstep, `linear` as a line, `constant` (and strings) as a step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from studio_core.sif import Interp, Vec

Channel = tuple[str, str]
Value = float | Vec | str


@dataclass(frozen=True, order=True)
class Key:
    frame: int
    value: Value = field(compare=False)
    interp: Interp = field(default=Interp.EASE, compare=False)


@dataclass
class Clip:
    motion: str
    start: int
    end: int  # last frame the clip affects (inclusive)
    channels: dict[Channel, list[Key]]
    additive: bool = False
    # angle ranges (degrees) this clip needs beyond a bone's default `limits_deg`, per bone, e.g. a
    # real walk bends the knee the way a person does, not the way the front-view rig allows
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for channel, keys in self.channels.items():
            frames = [k.frame for k in keys]
            if frames != sorted(set(frames)):
                raise ValueError(
                    f"{self.motion}: keys on {channel} are not strictly increasing: {frames}"
                )
            if keys and (keys[0].frame < self.start or keys[-1].frame > self.end):
                raise ValueError(
                    f"{self.motion}: keys on {channel} fall outside [{self.start}, {self.end}]"
                )


def _smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def _lerp(a: Value, b: Value, t: float) -> Value:
    if isinstance(a, Vec) and isinstance(b, Vec):
        return Vec(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a + (b - a) * t
    return a  # strings step


def sample(keys: list[Key], frame: float) -> Value:
    """The value of a key list at `frame` (holds the first/last value outside the keys)."""
    if not keys:
        raise ValueError("no keys to sample")
    if frame <= keys[0].frame:
        return keys[0].value
    if frame >= keys[-1].frame:
        return keys[-1].value
    for k0, k1 in pairwise(keys):
        if k0.frame <= frame <= k1.frame:
            t = (frame - k0.frame) / (k1.frame - k0.frame)
            if k0.interp is Interp.CONSTANT or isinstance(k0.value, str):
                return k0.value if frame < k1.frame else k1.value
            if k0.interp is Interp.EASE:
                t = _smoothstep(t)
            return _lerp(k0.value, k1.value, t)
    return keys[-1].value  # unreachable


def _zero_like(v: Value) -> Value:
    return Vec(0, 0) if isinstance(v, Vec) else 0.0


def _add(a: Value, b: Value) -> Value:
    if isinstance(a, Vec) and isinstance(b, Vec):
        return Vec(a.x + b.x, a.y + b.y)
    return a + b  # type: ignore[operator]


def _additive_at(clip: Clip, channel: Channel, frame: int) -> Value:
    keys = clip.channels[channel]
    if frame < keys[0].frame or frame > keys[-1].frame:
        return _zero_like(keys[0].value)
    return sample(keys, frame)


def compose(clips: list[Clip]) -> dict[Channel, list[Key]]:
    """Merge clips into one key list per channel (see the module docstring)."""
    channels = sorted({ch for c in clips for ch in c.channels})
    out: dict[Channel, list[Key]] = {}
    for channel in channels:
        overrides = sorted(
            (c for c in clips if not c.additive and channel in c.channels), key=lambda c: c.start
        )
        base: list[Key] = []
        for clip in overrides:
            keep = [k for k in base if not clip.start <= k.frame <= clip.end]
            base = sorted(keep + clip.channels[channel])
        additives = [c for c in clips if c.additive and channel in c.channels]
        if additives:
            frames = sorted(
                {k.frame for k in base} | {k.frame for c in additives for k in c.channels[channel]}
            )
            interp_at = {k.frame: k.interp for c in additives for k in c.channels[channel]}
            interp_at.update({k.frame: k.interp for k in base})
            merged = []
            for f in frames:
                first = (base or additives[0].channels[channel])[0].value
                value = sample(base, f) if base else _zero_like(first)
                for c in additives:
                    value = _add(value, _additive_at(c, channel, f))
                merged.append(Key(f, value, interp_at[f]))
            base = merged
        out[channel] = base
    return out
